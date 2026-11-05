"""Candidate generation (blocking): which pairs are worth scoring. Only pairs that touch a query record (one an
earlier stage left unresolved) are produced, so leftovers can still join existing clusters. `query=None` makes every
record a query; with `clusters`, pairs already inside one cluster are then dropped, so two clusters can join too.

KeyBlocker            all keys equal                                    O(N + P)
SortedNeighbourhood   sort by key, pair records within `window` places  O(N log N + N·w)
TfidfNeighbours       char n-gram TF-IDF, k nearest by cosine           O(N·L + U·N·q), brute force; q = n-grams per record
DeletionKeys          the value or a one-character deletion of it equal  O(N·L + P); any two values one edit apart share a key
"""
import re
import time
from collections.abc import Iterable

import numpy as np
import pandas as pd

from er.config import Blocker, Budget, DeletionKeys, KeyBlocker, OverBudget, SortedNeighbourhood, TfidfNeighbours
from er.evaluate import c2


def ordered(a: np.ndarray, b: np.ndarray, uid: str) -> pd.DataFrame:  # canonical uid_l < uid_r, no self / repeats
    a, b = np.asarray(a, dtype=object), np.asarray(b, dtype=object)
    lo, hi = np.where(a < b, a, b), np.where(a < b, b, a)
    out = pd.DataFrame({f"{uid}_l": lo, f"{uid}_r": hi}).astype("string")
    return out[out[f"{uid}_l"] != out[f"{uid}_r"]].drop_duplicates(ignore_index=True)


def deletions(s: str) -> list[str]:  # the value and each one-character deletion: two values one edit apart share one
    return list({s, *(s[:i] + s[i + 1:] for i in range(len(s)))})


def variants(b: DeletionKeys, df: pd.DataFrame, keep: tuple[str, ...] = ()) -> pd.DataFrame:  # one row per record and key
    within = [k.name for k in b.within]
    base = df.dropna(subset=[b.key.name, *within])
    return base[[*keep, *within]].assign(__key=base[b.key.name].map(deletions).to_numpy()).explode("__key")


def estimate(b: Blocker, df: pd.DataFrame, n_query: int) -> dict[str, object]:
    """Work before running: candidate pairs (upper bound) and the largest block."""
    n = len(df)
    match b:
        case KeyBlocker():
            blocks = df.dropna(subset=[k.name for k in b.keys]).groupby([k.name for k in b.keys]).size()
            p = c2(blocks)
            return dict(big_o="O(N + P)", filled=f"O({n:,} + {p:,})", est_pairs=p, largest_block=int(blocks.max()) if len(blocks) else 0)
        case SortedNeighbourhood():
            m = int(df[b.key.name].notna().sum())
            return dict(big_o="O(N log N + N·w)", filled=f"O({m:,}·log {m:,} + {m:,}·{b.window})",
                        est_pairs=m * (b.window - 1), largest_block=b.window)
        case DeletionKeys():  # Σ C(k,2) over the key blocks, less the repeats: identical values share all their keys
            on = [k.name for k in b.within]
            blocks = variants(b, df).groupby(["__key", *on]).size()
            same = df.dropna(subset=[b.key.name, *on]).groupby([b.key.name, *on]).size()
            repeats = same.index.get_level_values(0).map(lambda v: len(deletions(v)) - 1).to_numpy()
            p = c2(blocks) - int((repeats * same.to_numpy() * (same.to_numpy() - 1) // 2).sum())
            return dict(big_o="O(N·L + P)", filled=f"O({n:,}·L + {p:,})", est_pairs=p, largest_block=int(blocks.max()) if len(blocks) else 0)
        case TfidfNeighbours():
            m = int(df[b.key.name].notna().sum())
            q = df[b.key.name].dropna().str.len().mean() * (b.ngram[1] - b.ngram[0] + 1)  # n-grams per record, roughly
            return dict(big_o="O(N·L + U·N·q)", filled=f"O({m:,}·L + {n_query:,}·{m:,}·{q:.0f})",
                        est_pairs=n_query * b.k, largest_block=b.k + 1)


def generate(b: Blocker, df: pd.DataFrame, uid: str, query: set[str] | None) -> pd.DataFrame:
    def asked(x: pd.DataFrame) -> pd.DataFrame:  # the query side; None skips a costly isin when every record is a query
        return x if query is None else x[x[uid].isin(query)]
    match b:
        case KeyBlocker():
            cols = [k.name for k in b.keys]
            base = df.dropna(subset=cols)[[uid, *cols]]
            pairs = asked(base).merge(base, on=cols, suffixes=("_q", "_o"))
            return ordered(pairs[f"{uid}_q"], pairs[f"{uid}_o"], uid)
        case SortedNeighbourhood():
            base = df.dropna(subset=[b.key.name]).sort_values([b.key.name, uid], kind="stable")[uid].to_numpy()
            a = np.concatenate([base[:-o] for o in range(1, b.window) if o < len(base)] or [np.array([], dtype=object)])
            c = np.concatenate([base[o:] for o in range(1, b.window) if o < len(base)] or [np.array([], dtype=object)])
            if query is None:
                return ordered(a, c, uid)
            keep = pd.Series(a).isin(query).to_numpy() | pd.Series(c).isin(query).to_numpy()
            return ordered(a[keep], c[keep], uid)
        case DeletionKeys():
            on = ["__key", *(k.name for k in b.within)]
            base = variants(b, df, (uid,))
            pairs = asked(base).merge(base, on=on, suffixes=("_q", "_o"))
            return ordered(pairs[f"{uid}_q"], pairs[f"{uid}_o"], uid)
        case TfidfNeighbours():
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.neighbors import NearestNeighbors
            base = df.dropna(subset=[b.key.name])[[uid, b.key.name]].reset_index(drop=True)
            qi = np.arange(len(base)) if query is None else np.flatnonzero(base[uid].isin(query).to_numpy())
            if not len(qi) or len(base) < 2:
                return ordered(np.array([]), np.array([]), uid)
            x = TfidfVectorizer(analyzer="char", ngram_range=b.ngram).fit_transform(base[b.key.name].astype(str))
            dist, idx = NearestNeighbors(n_neighbors=min(b.k + 1, len(base)), metric="cosine").fit(x).kneighbors(x[qi])
            ids = base[uid].to_numpy(dtype=object)
            keep = (1 - dist) >= b.min_cosine
            return ordered(np.repeat(ids[qi], idx.shape[1])[keep.ravel()], ids[idx.ravel()][keep.ravel()], uid)


def found_by(cands: pd.DataFrame, names: Iterable[str]) -> np.ndarray:  # the pairs any of these generators found
    whole = "(?:^|\\+)(?:" + "|".join(map(re.escape, names)) + ")(?:\\+|$)"  # whole names: person_name ≠ sn_person_name
    return cands["sources"].str.contains(whole, regex=True).to_numpy(bool)


def candidates(blockers: tuple[Blocker, ...], df: pd.DataFrame, uid: str, query: set[str] | None,
               budget: Budget, clusters: pd.Series | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Union of all generators, with the generators that found each pair in `sources`, and a per-generator report.
    With `clusters` (uid → previous cluster), pairs already inside one cluster are dropped before the union."""
    l, r = f"{uid}_l", f"{uid}_r"
    report, found = [], []
    for b in blockers:
        est = estimate(b, df, len(df) if query is None else len(query))
        if est["est_pairs"] > budget.max_candidate_pairs or est["largest_block"] > budget.max_block_size:
            raise OverBudget(f"{b.name}: {est}")
        t = time.perf_counter()
        pairs = generate(b, df, uid, query)
        if clusters is not None:
            pairs = pairs[pairs[l].map(clusters).to_numpy() != pairs[r].map(clusters).to_numpy()]
        report.append(dict(generator=b.name, **est, pairs=len(pairs), seconds=round(time.perf_counter() - t, 3)))
        found.append(pairs.assign(bit=1 << len(found)))
    if not found:
        return pd.DataFrame(columns=[l, r, "sources"], dtype="string"), pd.DataFrame(report)
    assert len(found) < 63, "one bit per generator"
    # a pair's generators as one bit each, summed in C: a "+".join per pair took most of the candidate time at scale
    bits = pd.concat(found, ignore_index=True).groupby([l, r], sort=False)["bit"].sum()
    names = {m: "+".join(g.name for i, g in enumerate(blockers) if m >> i & 1) for m in bits.unique()}
    return bits.map(names).rename("sources").reset_index().astype("string"), pd.DataFrame(report)

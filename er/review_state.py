"""What people have said of a written run, read from its folder: each pair's latest decision, applied (decisions/)
or typed into the sheet and not applied yet (said); where the trust line stands and how far people are (trust_state);
and how much is left to check, range by range (review_workload)."""
import math
from pathlib import Path

import duckdb
import pandas as pd

from er.config import Pipeline, bits, lit, q
from er.folder import DECISIONS
from er.io import read_parquet
from er.kind import sheet_parts


def said(out: Path, uid: str) -> pd.DataFrame:
    """Each pair's latest decision: applied (decisions/), else typed into the sheet and not applied yet (applied False)."""
    l, r = f"{uid}_l", f"{uid}_r"
    done = applied(out, uid)[[l, r, "decision"]].assign(applied=True)
    sheet = out / "review.parquet"
    typed = read_parquet(sheet, columns=[l, r, "decision"]).dropna(subset=["decision"]).assign(applied=False) if sheet.exists() else done.iloc[:0]
    kept = set(zip(done[l], done[r], done["decision"]))  # the sheet keeps what was applied: only a different answer is newer
    typed = typed[[x not in kept for x in zip(typed[l], typed[r], typed["decision"])]]
    both = pd.concat([typed, done], ignore_index=True).astype({l: "string", r: "string"})
    return both.drop_duplicates([l, r], keep="first")  # a decision typed since overrides the applied one


def _trust_links(out: Path, uid: str, decided: str) -> list[str]:
    """The links a trust line counts, as SQL parts to union (DISTINCT ON the pair): the run's matches, proposed and
    rules' pairs, and the scored pairs people decided (`decided`, a table), at the line or above in neither."""
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    parts = [f"SELECT {l}, {r}, match_weight FROM {read(out, f'{x}/*.parquet')}"
             for x in ("matches", "proposed", "rule_kept") if any((out / x).glob("*.parquet"))]
    if parts and any((out / "scored").glob("*.parquet")):
        parts.append(f"SELECT s.{l}, s.{r}, s.match_weight FROM {read(out, 'scored/*.parquet')} s JOIN {decided} USING ({l}, {r})")
    return parts


def trust_state(con: duckdb.DuckDBPyConnection, out: Path, p: Pipeline, uid: str) -> dict | None:
    """The trust line of the run in `out` (p.trust, the workspace's method.toml), and how far people are: the range
    they check next (from the next step down to the line), its links (the rules' and the model's, in the run's
    files), how many they decided and how many they found false, and whether the line may step down (`checks`
    decided, or the whole range, none false); and the same for the links above the line, its spot-checks. None: no
    trust line. O(E + D)."""
    trust = p.trust
    if trust.line is None:
        return None
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    decided = applied(out, uid)[[f"{uid}_l", f"{uid}_r", "decision"]]
    con.register("er_trust_decided", decided)
    typed = said(out, uid)
    con.register("er_trust_typed", typed[~typed["applied"] & (typed["decision"] == "no_match")])  # marked different on the sheet, not applied yet
    parts = _trust_links(out, uid, "er_trust_decided")

    def count(where: str) -> dict:
        if not parts:
            return dict(pairs=0, checked=0, false=0, typed_false=0)
        pairs, checked, false, typed_false = con.execute(f"""SELECT count(*), count(d.decision), count(*) FILTER (WHERE d.decision = 'no_match'), count(t.decision)
            FROM (SELECT DISTINCT ON ({l}, {r}) * FROM ({' UNION ALL '.join(parts)})) x LEFT JOIN er_trust_decided d USING ({l}, {r})
            LEFT JOIN er_trust_typed t USING ({l}, {r}) WHERE {where}""").fetchall()[0]
        return dict(pairs=pairs, checked=checked, false=false, typed_false=typed_false)
    span = trust.below(lambda lo, hi: count(f"x.match_weight >= {bits(lo)} AND x.match_weight < {bits(hi)}")["pairs"] > 0)  # an empty range passed
    within = f"x.match_weight >= {bits(span[0])} AND x.match_weight < {bits(span[1])}" if span else "FALSE"
    near = count(within) if span else dict(pairs=0, checked=0, false=0, typed_false=0)
    above = count(f"x.match_weight >= {bits(trust.line)}")
    gold = lit(out / "gold.parquet")
    askable = con.execute(f"""SELECT count(*) FROM (SELECT DISTINCT ON ({l}, {r}) * FROM ({' UNION ALL '.join(parts)})) x
        LEFT JOIN er_trust_decided d USING ({l}, {r}) JOIN read_parquet({gold}) ga ON ga.{q(uid)} = x.{l} JOIN read_parquet({gold}) gb ON gb.{q(uid)} = x.{r}
        WHERE {within} AND (d.decision IS NOT NULL OR ga.cluster_id <> gb.cluster_id)""").fetchall()[0][0] if near["false"] and parts else 0
    con.unregister("er_trust_decided")
    con.unregister("er_trust_typed")
    needed = askable if near["false"] else min(trust.checks, near["pairs"])  # found false: every pair people can still be asked
    return dict(line="none" if math.isinf(trust.line) else trust.line,
                next=dict(down_to=span[0], up_to=None if math.isinf(span[1]) else span[1]) if span else None,
                **near, needed=needed, may_lower=span is not None and near["checked"] >= needed and not near["false"] and not near["typed_false"],
                above=above, checks=trust.checks)



def review_workload(con: duckdb.DuckDBPyConnection, out: Path, p: Pipeline, uid: str, seconds_per_pair: float = 10.0) -> dict:
    """How much people must check, without labels. Each range of the trust line's steps ([20, ∞), [12, 20), …, [0, 6)):
    its pairs (the rules' and the model's links, as trust_state counts them), how many people decided and said
    different, the sample it needs (checks, or all of a smaller range), the false links the model expects in it (the
    sum of 1 − p of its weights), the chance its sample comes back clean, the false rate a clean sample bounds (rule of
    three: 1 − 0.05^(1/sample)), the reviews left to merge it and every range above it, and the reviews if its sample
    isn't clean (people then decide all of it): none for a range above the line, which merges; all of a range below it
    found false and of every range below that, since the line never steps past it. Then what waits whatever the line: the pairs below the last step, the
    model's pairs with no name compared; the spot-checks a round; the person/company sheet; and the hours at
    `seconds_per_pair`, an assumption, not a measure. O(E + D)."""
    l, r = q(f"{uid}_l"), q(f"{uid}_r")
    steps, trust = sorted(p.trust.steps, reverse=True), p.trust
    tops = [math.inf, *steps[:-1]]
    band = "CASE " + " ".join(f"WHEN x.match_weight >= {bits(lo)} THEN {i}" for i, lo in enumerate(steps)) + f" ELSE {len(steps)} END"
    con.register("er_review_decided", applied(out, uid)[[f"{uid}_l", f"{uid}_r", "decision"]])
    parts = _trust_links(out, uid, "er_review_decided")  # as trust_state counts them
    got = {b: (n, c, f, e) for b, n, c, f, e in con.execute(f"""SELECT {band} AS b, count(*), count(d.decision), count(*) FILTER (WHERE d.decision = 'no_match'),
        sum(1 / (1 + pow(2, least(x.match_weight, 60)))) FROM (SELECT DISTINCT ON ({l}, {r}) * FROM ({' UNION ALL '.join(parts)})) x
        LEFT JOIN er_review_decided d USING ({l}, {r}) GROUP BY 1""").fetchall()} if parts else {}
    sheet = out / "review.parquet"
    unnamed = con.execute(f"""SELECT count(*) FROM read_parquet({lit(sheet)}) s WHERE s.why = 'decide' AND NOT EXISTS
        (SELECT 1 FROM ({' UNION ALL '.join(parts)}) x WHERE x.{l} = s.{l} AND x.{r} = s.{r})
        AND NOT EXISTS (SELECT 1 FROM er_review_decided d WHERE d.{l} = s.{l} AND d.{r} = s.{r})""").fetchall()[0][0] if parts and sheet.exists() else 0
    con.unregister("er_review_decided")
    ranges, total, stuck = [], 0, False
    for i, (lo, hi) in enumerate(zip(steps, tops)):
        pairs, checked, different, expected = got.get(i, (0, 0, 0, 0.0))
        sample = min(trust.checks, pairs)
        rate = expected / pairs if pairs else 0.0
        above = trust.line is not None and lo >= trust.line  # merging already
        stuck |= bool(different) and not above  # the line never steps past a range below it found false: it and every range below stay with people, whole
        left = 0 if above else int(pairs - checked) if stuck else max(sample - checked, 0)
        total += left
        ranges.append(dict(down_to=lo, up_to=None if math.isinf(hi) else hi, pairs=int(pairs), checked=int(checked), different=int(different), sample=sample,
                           expected_false=round(float(expected), 1), chance_clean=round((1 - rate) ** sample, 3) if sample and not stuck else None,
                           bound=round(1 - 0.05 ** (1 / sample), 4) if sample else None, reviews_left=left, reviews_to_here=total,
                           if_not_clean=int(pairs - checked)))
    below = int(got.get(len(steps), (0,))[0])
    sheet = read_parquet(out / "kind_review.parquet") if (out / "kind_review.parquet").exists() else pd.DataFrame(columns=["why", "kind"])
    part, open_ = sheet_parts(sheet) if len(sheet) else sheet["why"], sheet["kind"].isna()
    hours = lambda n: round(n * seconds_per_pair / 3600, 1)
    return dict(ranges=ranges, below_last_step=below, unnamed=int(unnamed), watch=trust.watch,
                kinds=dict(measure=int((part == "measure").sum()), decide=int((part == "decide").sum()), answered=int((~open_).sum())), seconds_per_pair=seconds_per_pair,
                hours=dict(to_each_line=[hours(x["reviews_to_here"]) for x in ranges], unnamed=hours(unnamed), kinds=hours(int(((part == "decide") & open_).sum()))))



def applied(out: Path, uid: str) -> pd.DataFrame:  # each pair's latest decision the folder holds
    parts = sorted((out / DECISIONS).glob("part-*.parquet"))
    if not parts:
        return pd.DataFrame(columns=[f"{uid}_l", f"{uid}_r", "decision"])
    return pd.concat([read_parquet(f) for f in parts]).drop_duplicates([f"{uid}_l", f"{uid}_r"], keep="last")



def read(out: Path, name: str) -> str:  # SQL: the run's files under `name` (a glob of parts, or one file), their columns by name
    return f"read_parquet({lit(out / name)}, union_by_name = true)"

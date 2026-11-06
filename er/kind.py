"""Person or company: each record's kind, from its name and what else the record holds (config/pipeline.toml [kind]).

    legal form   written where banks write it (er.standardize.legal_pattern): a company, near certain
    name model   logistic regression on the name's character n-grams (1 to KindSpec.ngram), legal forms and spaces
                 removed; trained once on public reference data (er.generate.kind_training_names) and cached
    combiner     gradient-boosted trees on the name model's score, the file's flag, the birth year and the legal form,
                 fitted on people's labels (kind_review.parquet, filled in); none without labels
    lines        company: no labelled error above it (out of fold), then margin_steps stricter; person: the labelled
                 error above it at most half its budget. Without labels: a company only where a legal form is
                 written, never a sure person.

Each record gets kind_p, the probability that it is a company's (empty when nothing speaks to it), and kind: company,
person or unsure. A name routed by kind (er.standardize.prepare) goes to the side kind_p leans to. scripts/choose_kind.py
chose these parts. O(N·L·g) to score N records (g n-gram lengths), O(T·L·g) once to train on T reference names,
O(Λ·trees) for Λ labels.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from er.config import KindSpec, Standardization
from er.standardize import legal_pattern, normalize

VERSION = 1  # of the name model's training: a change here trains it again


def legal(names: pd.Series, std: Standardization) -> np.ndarray:
    """Whether each name holds a legal form where banks write one."""
    s = normalize(names.astype("string"), ("strip_spaces", "nfkc"), std)
    return s.str.contains(legal_pattern(std), regex=True).fillna(False).to_numpy(dtype=bool)


def text(names: pd.Series, std: Standardization) -> pd.Series:
    """What the name model reads: the name folded, without spaces or legal forms."""
    return normalize(names.astype("string"), ("strip_spaces", "nfkc", "strip_legal_form", "kana_fold"), std)


class NameModel:
    """Logistic regression on a name's character n-grams; saved as its terms and weights, no pickle."""

    def __init__(self, terms: list[str], coef: np.ndarray, intercept: float, ngram: int):
        self.terms, self.coef, self.intercept, self.ngram = terms, coef, intercept, ngram
        self.vec = CountVectorizer(analyzer="char", ngram_range=(1, ngram), binary=True, vocabulary=terms)

    @classmethod
    def fit(cls, texts: pd.Series, y: np.ndarray, ngram: int) -> "NameModel":
        vec = CountVectorizer(analyzer="char", ngram_range=(1, ngram), binary=True, min_df=2)
        m = LogisticRegression(C=1.0, max_iter=3000).fit(vec.fit_transform(texts.fillna("")), y)
        return cls(vec.get_feature_names_out().tolist(), m.coef_[0], float(m.intercept_[0]), ngram)

    def logit(self, texts: pd.Series) -> np.ndarray:  # log-odds of a company; NaN where there is no name
        has = texts.notna().to_numpy()
        out = np.full(len(texts), np.nan)
        if has.any():
            out[has] = self.vec.transform(texts[has]) @ self.coef + self.intercept
        return out

    def save(self, path: Path, key: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, terms=np.array(self.terms), coef=self.coef, intercept=self.intercept, ngram=self.ngram, key=key)

    @classmethod
    def load(cls, path: Path, key: str) -> "NameModel | None":
        if not path.exists():
            return None
        z = np.load(path)
        return cls(z["terms"].tolist(), z["coef"], float(z["intercept"]), int(z["ngram"])) if str(z["key"]) == key else None


def name_model(settings, spec: KindSpec) -> NameModel:
    """The name model for these settings: trained on the reference data (personas and the registry), cached in the
    models folder under a key of everything it depends on."""
    from er.generate import kind_training_names, load_reference, load_registry, load_spec  # the generator's data, read once
    ref = settings.paths["reference"]
    std = settings.standardize
    h = hashlib.sha256(f"{VERSION}|{spec.ngram}|{std.legal_forms}|{std.legal_front}|{std.legal_end}|{sorted(std.kana_fold.items())}".encode())
    for f in ("individual.json", "registry.json"):
        h.update((ref / f).read_bytes())
    key, path = h.hexdigest(), settings.paths["models"] / "kind_names.npz"
    if (m := NameModel.load(path, key)) is not None:
        return m
    spec_g = load_spec(settings.root / "config" / "generator.toml")[0]
    names = kind_training_names(load_reference(ref)[0], load_registry(ref), std.legal_front, std.legal_end, spec_g.kana_confusions, spec_g.branches)
    m = NameModel.fit(text(names["name"], std), names["y"].to_numpy(), spec.ngram)
    m.save(path, key)
    return m


@dataclass
class Classifier:
    spec: KindSpec
    std: Standardization
    flag_company: tuple[str, ...]
    names: NameModel
    combiner: HistGradientBoostingClassifier | None = None
    labels: int = 0                           # people's labels the combiner and the lines rest on
    line_company: float = 1.01                # above 1: never
    line_person: float = 1.01
    person_error: float | None = None         # the labels' wrong share above the person line
    flag_error: float | None = None           # how often the file's flag is wrong, on the labels drawn at random
    flag_checked: int = 0                     # ... on this many of them

    def features(self, name: pd.Series, flag: pd.Series | None, birth: pd.Series | None) -> np.ndarray:
        """Per record: the name model's log-odds, the flag (1 company, 0 person), the birth year, a legal form."""
        n = len(name)
        f = np.full(n, np.nan) if flag is None else np.where(flag.isna(), np.nan, flag.astype("string").isin(self.flag_company).astype(float))
        year = np.full(n, np.nan) if birth is None else pd.to_numeric(birth.astype("string").str[:4], errors="coerce").to_numpy(dtype=float)
        return np.column_stack([self.names.logit(text(name, self.std)), f, year, legal(name, self.std).astype(float)])

    def classify(self, name: pd.Series, flag: pd.Series | None = None, birth: pd.Series | None = None) -> pd.DataFrame:
        X = self.features(name, flag, birth)
        if self.spec.trust_flag:
            p = X[:, 1]
            kind = np.where(p == 1, "company", np.where(p == 0, "person", "unsure"))
        elif self.combiner is not None:
            p = self.combiner.predict_proba(X)[:, 1]
            kind = np.where(p >= self.line_company, "company", np.where(1 - p >= self.line_person, "person", "unsure"))
        else:  # no labels: a written legal form decides; the name model only says where a name leans
            p = np.where(X[:, 3] == 1, 1.0, 1 / (1 + np.exp(-X[:, 0])))
            kind = np.where(X[:, 3] == 1, "company", "unsure")
        return pd.DataFrame({"kind_p": p, "kind": pd.Series(kind, dtype="string").to_numpy()}, index=name.index)


def lines(p: np.ndarray, company: np.ndarray, spec: KindSpec) -> tuple[float, float, float | None]:
    """Each side's line from out-of-fold probabilities on people's labels: the company line is the lowest grid point with
    no labelled person above it, then margin_steps stricter; the person line the lowest whose labelled wrong share is
    at most half of person_wrong_at_most, on 30 labels or more. Above 1: never."""
    grid = list(spec.grid)
    clean = [g for g in grid if not ((p >= g) & ~company).any() and (p >= g).any()]
    line_c = grid[min(grid.index(clean[0]) + spec.margin_steps, len(grid) - 1)] if clean else 1.01
    line_p, error = 1.01, None
    for g in grid:
        above = (1 - p) >= g
        if above.sum() >= 30 and (above & company).sum() / above.sum() <= spec.person_wrong_at_most / 2:
            line_p, error = g, float((above & company).sum() / above.sum())
            break
    return line_c, line_p, error


def classifier(settings, spec: KindSpec, labels: pd.DataFrame | None = None) -> Classifier:
    """The kind for a run: with people's labels (columns name, kind_flag, birth_date, kind = company or person), the
    combiner fitted on them and each side's line; without, the name model and written legal forms only."""
    c = Classifier(spec=spec, std=settings.standardize, flag_company=settings.flag_company, names=name_model(settings, spec))
    if labels is None:
        return c
    lab = labels[labels["kind"].isin(["company", "person"])]
    drawn = lab[(lab["drawn"] == "at random") if "drawn" in lab else np.ones(len(lab), dtype=bool)]
    if "kind_flag" in drawn and drawn["kind_flag"].notna().any():  # the flag against people, where the draw didn't look at scores
        d = drawn[drawn["kind_flag"].notna()]
        c.flag_error, c.flag_checked = float((d["kind_flag"].astype("string").isin(c.flag_company) != (d["kind"] == "company")).mean()), len(d)
    if spec.trust_flag:
        return c
    y = (lab["kind"] == "company").to_numpy()
    if len(lab) < 50 or y.all() or not y.any():  # too few to fit and to place a line on
        return c
    col = lambda f: lab[f] if f in lab else None
    X = c.features(lab["name"], col("kind_flag"), col("birth_date"))
    make = lambda: HistGradientBoostingClassifier(max_depth=spec.depth, max_iter=100, learning_rate=0.1, random_state=0)
    oof = cross_val_predict(make(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")[:, 1]
    c.line_company, c.line_person, c.person_error = lines(oof, y, spec)
    c.combiner, c.labels = make().fit(X, y), len(lab)
    return c


def label_sheet(records: pd.DataFrame, uid: str, n: int, labelled: set[str] = frozenset()) -> pd.DataFrame:
    """Records for people to label, n of them: a third at random, a third where the score leans company (kind_p ≥ 0.9),
    a third where it leans person (≤ 0.1), none already labelled; an empty `kind` column (company or person) to fill.
    The draw follows a hash of the record ID, so the same file gives the same sheet. O(N)."""
    r = records[~records[uid].isin(labelled)].assign(_h=lambda d: pd.util.hash_pandas_object(d[uid], index=False).to_numpy())
    k, parts = n // 3, []
    for drawn, which, size in (("at random", lambda d: np.ones(len(d), dtype=bool), k), ("leans company", lambda d: d["kind_p"] >= 0.9, k),
                               ("leans person", lambda d: d["kind_p"] <= 0.1, n - 2 * k)):
        pick = r[which(r)].nsmallest(size, "_h")
        parts.append(pick.assign(drawn=drawn))
        r = r.drop(pick.index)  # each third from the records not drawn yet
    sheet = pd.concat(parts).drop(columns="_h")
    return sheet.assign(kind=pd.Series(pd.NA, index=sheet.index, dtype="string")).reset_index(drop=True)

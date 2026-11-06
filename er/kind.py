"""Person or company: each record's kind, from its name and what else the record holds (config/pipeline.toml [kind]).

    legal form   written where banks write it (er.standardize.legal_pattern): a company, near certain
    name model   logistic regression on the name's character n-grams (1 to KindSpec.ngram), legal forms and spaces
                 removed; trained once on public reference data (er.generate.kind_training_names) and cached
    combiner     gradient-boosted trees on the name model's score, the file's flag, the birth year and the legal form,
                 fitted on people's labels (kind_review.parquet, filled in); none without labels
    lines        company: no labelled error above it (out of fold), then margin_steps stricter; person: the labelled
                 error above it at most half its budget. Without labels: a company only where a legal form is
                 written, never a sure person.

Each record gets kind (2 company, 1 person, 0 not sure: the codes a person/company flag uses), kind_p (the probability
of a company), kind_by (engine, or people: their answer stands) and name_p (what its name alone says). A name routed by
kind (er.standardize.prepare) goes to the side kind_p leans to. The review sheet (review_sheet) sends people the
records where the engine or the name disagrees with the file's flag, and a draw that measures both.
scripts/choose_kind.py chose these parts. O(N·L·g) to score N records (g n-gram lengths), O(T·L·g) once to train on T reference names,
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


PERSON, COMPANY, UNSURE = 1, 2, 0  # the codes of kind, customer_kind and people's answers: as a person/company flag writes them
SAYS = {PERSON: "1 person", COMPANY: "2 company", UNSURE: "0 not sure"}


@dataclass
class Classifier:
    spec: KindSpec
    std: Standardization
    flag_company: tuple[str, ...]
    names: NameModel
    uid: str = ""
    combiner: HistGradientBoostingClassifier | None = None
    labels: int = 0                           # people's answers the combiner rests on (1 or 2)
    measured: int = 0                         # ... of them drawn to measure: the lines and error rates rest on these only
    decided: dict[str, int] | None = None     # record → people's answer, 1 or 2: it stands, whatever the engine says
    line_company: float = 1.01                # above 1: never
    line_person: float = 1.01
    person_error: float | None = None         # the measured wrong share above the person line
    flag_error: float | None = None           # how often the file's flag is wrong, on the answers drawn at random
    flag_checked: int = 0                     # ... on this many of them
    blank: np.ndarray | None = None           # features the answers never fill (a file without a flag): held at 0

    def flag_code(self, flag: pd.Series | None, n: int) -> np.ndarray:  # the flag as 2 (company), 1 (person), NaN (none)
        if flag is None:
            return np.full(n, np.nan)
        return np.where(flag.isna(), np.nan, np.where(flag.astype("string").isin(self.flag_company), COMPANY, PERSON)).astype(float)

    def features(self, name: pd.Series, flag: pd.Series | None, birth: pd.Series | None) -> np.ndarray:
        """Per record: the name model's log-odds, the flag (1 company, 0 person), the birth year, a legal form."""
        n = len(name)
        year = np.full(n, np.nan) if birth is None else pd.to_numeric(birth.astype("string").str[:4], errors="coerce").to_numpy(dtype=float)
        return np.column_stack([self.names.logit(text(name, self.std)), self.flag_code(flag, n) - 1, year, legal(name, self.std).astype(float)])

    def classify(self, name: pd.Series, flag: pd.Series | None = None, birth: pd.Series | None = None,
                 ids: pd.Series | None = None) -> pd.DataFrame:
        """Per record: kind (2 company, 1 person, 0 not sure), kind_p (the probability of a company), kind_by (engine or
        people), name_p (what the name and its legal form alone say, the flag aside: the review sheet's other view) and
        kind_held: the engine leans one way, the file's flag says the other, and no person has decided. A held record's
        name goes to neither side (er.standardize.prepare): a company sent to the person side could merge into its
        representative's own records, and nothing tells which of the two is right until a person looks."""
        X = self.features(name, flag, birth)
        name_p = np.where(X[:, 3] == 1, 1.0, 1 / (1 + np.exp(-X[:, 0])))
        if self.spec.trust_flag:
            p = X[:, 1]
            kind = np.where(p == 1, COMPANY, np.where(p == 0, PERSON, UNSURE))
        elif self.combiner is not None:
            p = self.combiner.predict_proba(np.where(self.blank, 0.0, X))[:, 1]
            kind = np.where(p >= self.line_company, COMPANY, np.where(1 - p >= self.line_person, PERSON, UNSURE))
        else:  # no labels: a written legal form decides; the name model only says where a name leans
            p = name_p
            kind = np.where(X[:, 3] == 1, COMPANY, UNSURE)
        nameless = name.isna().to_numpy()  # nothing a person could judge, nor a line was placed on: not sure, no lean
        kind, p = np.where(nameless, UNSURE, kind), np.where(nameless, np.nan, p)
        by = np.full(len(name), "engine", dtype=object)
        if self.decided and ids is not None:  # people's answers stand
            said = ids.map(self.decided).to_numpy(dtype=float)
            hit = ~np.isnan(said)
            kind, p, by = np.where(hit, said, kind), np.where(hit, said == COMPANY, p).astype(float), np.where(hit, "people", by)
        flag_code = X[:, 1] + 1
        held = (by != "people") & ~nameless & ~np.isnan(flag_code) & (np.where(p >= 0.5, COMPANY, PERSON) != flag_code)
        if self.spec.trust_flag:
            held[:] = False
        return pd.DataFrame({"kind": kind.astype(np.int8), "kind_p": p, "kind_by": by, "name_p": name_p, "kind_held": held,
                             "kind_name": name.astype("string").to_numpy()}, index=name.index)


def lines(p: np.ndarray, company: np.ndarray, spec: KindSpec) -> tuple[float, float, float | None]:
    """Each side's line from out-of-fold probabilities on people's answers: the company line is the lowest grid point
    with no labelled person above it, then margin_steps stricter; the person line the lowest whose labelled wrong share
    is at most half of person_wrong_at_most, on 30 answers or more. Above 1: never."""
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
    """The kind for a run. People's answers (a filled-in kind_review.parquet: kind = 1 or 2; 0, can't tell, is kept out)
    stand for their records, and train the combiner. Only the answers drawn to measure (why = measure) place the lines
    and measure the flag: the records sent to decide were picked because they look wrong, so every error rate on them
    would look worse than it is. Without answers: the name model and written legal forms only."""
    uid = settings.data.unique_id
    c = Classifier(spec=spec, std=settings.standardize, flag_company=settings.flag_company, names=name_model(settings, spec), uid=uid)
    if labels is None or not len(labels):
        return c
    lab = labels.assign(kind=pd.to_numeric(labels["kind"], errors="coerce"))
    lab = lab[lab["kind"].isin([PERSON, COMPANY])]
    c.decided = dict(zip(lab[uid].astype("string"), lab["kind"].astype(int))) if uid in lab else None
    measure = (lab["why"] == "measure").to_numpy() if "why" in lab else np.ones(len(lab), dtype=bool)
    at_random = measure & ((lab["drawn"] == "at random").to_numpy() if "drawn" in lab else True)
    col = lambda *names: next((lab[n] for n in names if n in lab), None)  # the sheet shows the flag as `flag`
    flag = col("kind_flag", "flag")
    if flag is not None and flag[at_random].notna().any():  # the flag against people, where the draw didn't look
        d = at_random & flag.notna().to_numpy()
        c.flag_error, c.flag_checked = float((c.flag_code(flag[d], int(d.sum())) != lab["kind"].to_numpy()[d]).mean()), int(d.sum())
    y = (lab["kind"] == COMPANY).to_numpy()
    if spec.trust_flag or len(lab) < 50 or y.all() or not y.any():  # too few to fit and to place a line on
        return c
    X = c.features(lab["name"], flag, col("birth_date"))
    c.blank = np.isnan(X).all(axis=0)
    X = np.where(c.blank, 0.0, X)
    make = lambda: HistGradientBoostingClassifier(max_depth=spec.depth, max_iter=100, learning_rate=0.1, random_state=0)
    oof = cross_val_predict(make(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")[:, 1]
    if measure.sum() >= 50 and y[measure].any() and not y[measure].all():
        c.line_company, c.line_person, c.person_error = lines(oof[measure], y[measure], spec)
    c.combiner, c.labels, c.measured = make().fit(X, y), len(lab), int(measure.sum())
    return c


def review_sheet(records: pd.DataFrame, uid: str, spec: KindSpec, flag_company: tuple[str, ...], answered: set[str] = frozenset()) -> pd.DataFrame:
    """Records for people, as matching's review sheet holds pairs. `records`: uid, name (as written: kind_name), kind_flag (if any), birth_date
    (if any), kind, kind_p, kind_by, name_p, kind_held. Two kinds of row, none already answered or decided by people:

        decide    the engine and the file's flag disagree: the record is held back from matching until a person decides
                  (sure contradictions first); then records the engine and the flag agree on but the name alone says
                  the other kind (name_p beyond spec.name_line), the flag's likely errors. At most spec.review_max.
        measure   spec.labels_to_draw records drawn to measure the flag and the engine: a third at random, a third the
                  engine leans company (kind_p ≥ 0.9), a third it leans person (≤ 0.1). The draw follows a hash of
                  the record ID: the same file gives the same sheet. A record without a name has nothing to judge: it is left out.

    Each row says in words why it is there (reason), what the engine says, what the name alone says and what the flag
    says; people write kind: 1 person, 2 company, 0 can't tell. O(N)."""
    r = records[~records[uid].isin(answered) & (records["kind_by"] != "people") & records["name"].notna()].copy()  # a name to judge
    r["_h"] = pd.util.hash_pandas_object(r[uid], index=False).to_numpy()
    flag = (np.where(r["kind_flag"].isna(), np.nan, np.where(r["kind_flag"].astype("string").isin(flag_company), COMPANY, PERSON))
            if "kind_flag" in r else np.full(len(r), np.nan))
    held = r["kind_held"].fillna(False).to_numpy(dtype=bool) if "kind_held" in r else np.zeros(len(r), dtype=bool)
    sure = r["kind"].isin([PERSON, COMPANY]).to_numpy()
    lean = np.where(r["kind_p"] >= 0.5, COMPANY, PERSON)
    name_says = np.where(r["name_p"] >= spec.name_line, COMPANY, np.where(r["name_p"] <= 1 - spec.name_line, PERSON, UNSURE))
    against = ~held & (name_says != UNSURE) & ~np.isnan(flag) & (name_says != flag)
    pct = lambda x: f"{max(x, 1 - x):.1%}"
    r["reason"] = np.select(
        [held & sure, held, against],
        [[f"the engine is sure it is {SAYS[k]}, the flag says {int(f)}: held back from matching until you decide" for k, f in zip(r["kind"], np.nan_to_num(flag))],
         [f"the engine is not sure, it leans to {SAYS[n]} ({pct(x)}); the flag says {int(f)}: held back from matching until you decide"
          for n, x, f in zip(lean, r["kind_p"], np.nan_to_num(flag))],
         [f"the name looks like {SAYS[n]} ({pct(x)}), the flag says {int(f)}; the engine says {SAYS[k]}"
          for n, x, f, k in zip(name_says, r["name_p"], np.nan_to_num(flag), r["kind"])]], "")
    r["_s"] = np.where(held, 2.0, 0.0) + np.where(held & sure, 1.0, 0.0) + np.abs(r["name_p"].fillna(0.5).to_numpy() - 0.5)
    r["_decide"] = held | against
    rest, k, parts = r, spec.labels_to_draw // 3, []
    for drawn, which, size, words in (  # the measuring draw first, from every record: what it measures must not depend on decide
            ("at random", lambda d: np.ones(len(d), dtype=bool), k, "drawn at random, to measure the flag and the engine"),
            ("leans company", lambda d: d["kind_p"] >= 0.9, k, "drawn among records the engine leans to 2 company, to measure it"),
            ("leans person", lambda d: d["kind_p"] <= 0.1, spec.labels_to_draw - 2 * k, "drawn among records the engine leans to 1 person, to measure it")):
        pick = rest[which(rest)].nsmallest(size, "_h")
        parts.append(pick.assign(why="measure", drawn=drawn, reason=np.where(pick["_decide"], words + "; also: " + pick["reason"], words)))
        rest = rest.drop(pick.index)  # each third from the records not drawn yet
    decide = rest[rest["_decide"]].sort_values(["_s", "_h"], ascending=[False, True]).head(spec.review_max)
    sheet = pd.concat([decide.assign(why="decide", drawn=""), *parts]).drop(columns=["_h", "_s", "_decide"])
    sheet["engine_says"] = sheet["kind"].map(SAYS)
    sheet["name_says"] = [f"{SAYS[COMPANY if x >= 0.5 else PERSON]} ({pct(x)})" if pd.notna(x) else "" for x in sheet["name_p"]]
    sheet = sheet.rename(columns={"kind": "engine", "kind_p": "engine_p", "kind_flag": "flag"} if "kind_flag" in sheet else {"kind": "engine", "kind_p": "engine_p"})
    front = ["why", "reason", "engine_says", "name_says", *(["flag"] if "flag" in sheet else []), "name", *(["birth_date"] if "birth_date" in sheet else [])]
    sheet = sheet[[uid, *front, "engine", "engine_p", "name_p", "drawn"]].assign(kind=pd.Series(pd.NA, index=sheet.index, dtype="Int8"))
    return sheet.reset_index(drop=True)

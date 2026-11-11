"""Person or company: each record's kind, from its name and what else the record holds (config/pipeline.toml [kind]).

    legal form   written where banks write it (er.config.legal_pattern): a company, near certain
    name model   logistic regression on the name's character n-grams (1 to KindSpec.ngram), legal forms and spaces
                 removed; trained once on public reference data by scripts/train_name_model.py: config/kind_names.npz
    combiner     gradient-boosted trees on the name model's score, the file's flag, the birth year and the legal form,
                 fitted on people's labels (kind_review.parquet, filled in), once 50 of them, of both kinds, were
                 drawn to measure: what its lines are placed on
    lines        company: no labelled error above it (out of fold), then margin_steps stricter, one more on fewer
                 answers than a measuring draw; person: the labelled
                 error above it within its budget at 95% confidence. Without them: a written legal form, or a name
                 past name_line either way.

Each record gets kind (2 company, 1 person, 0 not sure: the codes a person/company flag uses): the engine's call where
it is sure, else the file's flag. kind_p (the probability of a company), kind_by (engine, flag, or people: their
answer stands), name_p (what its name alone says), kind_flagged (the engine sure against the flag). A name routed by kind
(er.standardize.prepare) goes to the side of its kind. The review sheet (kind_review_sheet) lists people the flagged
records, and an optional draw that measures the flag and the engine.
scripts/choose_kind.py chose these parts. O(N·L·g) to score N records (g n-gram lengths), O(T·L·g) once to train on T reference names,
O(Λ·trees) for Λ labels.
"""
import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from er.config import InputError, KindSpec, Standardization, legal_pattern, lit, q
from er.standardize import normalize
from er.strings import connect

VERSION = 2  # of the name model's training: a change here trains it again


def legal(names: pd.Series, std: Standardization) -> np.ndarray:
    """Whether each name holds a legal form where banks write one."""
    s = normalize(names.astype("string"), ("strip_spaces", "nfkc"), std)
    return s.str.contains(legal_pattern(std), regex=True).fillna(False).to_numpy(dtype=bool)


def text(names: pd.Series, std: Standardization) -> pd.Series:
    """What the name model reads: the name folded, without spaces or legal forms."""
    return normalize(names.astype("string"), ("strip_spaces", "nfkc", "strip_legal_form", "kana_fold"), std)


class NameModel:
    """Logistic regression on a name's character n-grams; saved as its terms and weights, no pickle. It scores in
    DuckDB: every name's distinct n-grams in one query, joined to the weights, the same sums as scikit-learn's
    vectorizer builds one name at a time in Python, three times faster."""

    def __init__(self, terms: list[str], coef: np.ndarray, intercept: float, ngram: int, compute: dict | None = None):
        self.terms, self.coef, self.intercept, self.ngram = terms, coef, intercept, ngram
        self.con = connect(compute)[0]  # the run's limits: it scores every chunk's names
        self.con.register("er_weights", pd.DataFrame({"term": terms, "w": coef}))
        self.con.execute("CREATE TABLE weights AS SELECT * FROM er_weights")
        self.con.unregister("er_weights")

    @classmethod
    def fit(cls, texts: pd.Series, y: np.ndarray, ngram: int) -> "NameModel":
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.linear_model import LogisticRegression
        vec = CountVectorizer(analyzer="char", ngram_range=(1, ngram), binary=True, min_df=2)
        m = LogisticRegression(C=1.0, max_iter=3000).fit(vec.fit_transform(texts.fillna("")), y)
        return cls(vec.get_feature_names_out().tolist(), m.coef_[0], float(m.intercept_[0]), ngram)

    def logit(self, texts: pd.Series) -> np.ndarray:  # log-odds of a company; NaN where there is no name
        has = texts.notna().to_numpy()
        out = np.where(has, self.intercept, np.nan)
        if has.any():  # lower case and each n-gram once, as the vectorizer that trained it counts them; each distinct name once
            codes, names = pd.factorize(texts[has].str.lower())
            self.con.register("er_names", pd.DataFrame({"r": np.arange(len(names)), "t": np.asarray(names, dtype=object)}))
            sums = self.con.execute(f"""SELECT r, sum(w ORDER BY term) AS s FROM (SELECT DISTINCT r, substr(t, i, n) AS term FROM
                (SELECT r, t, n, unnest(range(1, length(t) - n + 2)) AS i FROM er_names, (SELECT unnest(range(1, {self.ngram} + 1)) AS n)))
                JOIN weights USING (term) GROUP BY r""").fetchnumpy()
            self.con.unregister("er_names")
            each = np.zeros(len(names))
            each[sums["r"]] = sums["s"]  # summed in term order: the same bits every run
            out[np.flatnonzero(has)] += each[codes]
        return out

    def save(self, path: Path, key: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp.npz")  # complete before it replaces the old file: a run may be reading it
        np.savez_compressed(tmp, terms=np.array(self.terms), coef=self.coef, intercept=self.intercept, ngram=self.ngram, key=key)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path, key: str, compute: dict | None = None) -> "NameModel | None":
        if not path.exists():
            return None
        z = np.load(path)
        return cls(z["terms"].tolist(), z["coef"], float(z["intercept"]), int(z["ngram"]), compute) if str(z["key"]) == key else None


KIND_COLUMNS = ("kind", "kind_p", "kind_by", "name_p", "kind_flagged", "kind_held", "kind_name", "customer_kind")  # what a run writes on each record and customer
NAME_MODEL = Path("config") / "kind_names.npz"  # trained by scripts/train_name_model.py, tracked in git: every run loads it


def name_key(settings, spec: KindSpec) -> str:
    """What of a run's settings the name model was trained under: a run refuses a model trained under others."""
    std = settings.standardize
    return hashlib.sha256(f"{VERSION}|{spec.ngram}|{std.legal_forms}|{std.legal_front}|{std.legal_end}|"
                          f"{sorted(std.kana_fold.items())}".encode()).hexdigest()


def name_model(settings, spec: KindSpec) -> NameModel:
    """The name model a run loads, config/kind_names.npz: trained once, on public data only, by
    scripts/train_name_model.py (er.generate.train_name_model). A run never trains it."""
    if (m := NameModel.load(settings.root / NAME_MODEL, name_key(settings, spec), settings.compute)) is None:
        raise InputError(f"{NAME_MODEL}: missing, or trained under other settings (the legal forms, the kana folding or [kind] ngram)",
                         fix="run scripts/train_name_model.py and commit config/kind_names.npz")
    return m


def century() -> int:  # a birth date's 2-digit year: up to this year's two digits, 20yy; past them, 19yy: never a year to come
    return date.today().year % 100


def birth_year(birth: pd.Series) -> np.ndarray:
    """The year of a date that starts with it: 1993-05-25, 19930525, 1993/5/2 → 1993; a 2-digit one, 93-05-25 or 930525,
    by century(); 199305, its month past 12 as yymmdd, → 1993; a day or month first, 25/05/1993, its 4-digit year. Else NaN
    (H05.05.25: an era's year). O(N)."""
    s = birth.astype("string")
    lead, four = s.str.extract(r"^\s*(\d+)", expand=False), s.str.extract(r"(?:^|\D)(\d{4})(?:\D|$)", expand=False)
    n = lead.str.len().fillna(0).to_numpy(dtype=int)
    num = lambda x: pd.to_numeric(x, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    yy, month, later = num(lead.str[:2]), num(lead.str[2:4]), num(four)
    short = (((n == 2) & np.isnan(later)) | ((n == 6) & ~(np.isin(yy, (19, 20)) & (month > 12))))
    return np.where(short, yy + np.where(yy <= century(), 2000, 1900), np.where(n >= 4, num(lead.str[:4]), later))


PERSON, COMPANY, UNSURE = 1, 2, 0  # the codes of kind, customer_kind and people's answers: as a person/company flag writes them
SAYS = {PERSON: "1 person", COMPANY: "2 company", UNSURE: "0 not sure"}


@dataclass(frozen=True)
class Fitted:  # the combiner and the lines placed on its out-of-fold answers: one without the other can't be
    combiner: "HistGradientBoostingClassifier"  # noqa: F821 — scikit-learn and SciPy are imported where a model is fitted: a second off every command that fits none
    line_company: float                       # above 1: never
    line_person: float
    person_error: float | None                # the measured wrong share above the person line


@dataclass
class Classifier:
    spec: KindSpec
    std: Standardization
    flag_company: tuple[str, ...]
    names: NameModel
    uid: str = ""
    fitted: Fitted | None = None              # None: no line placed, so the engine's own rule decides (classify)
    labels: int = 0                           # people's answers, 1 or 2: what the combiner rests on
    measured: int = 0                         # ... of them drawn to measure: the lines and error rates rest on these only
    decided: dict[str, int] | None = None     # record → people's answer, 1 or 2: it stands, whatever the engine says
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
        year = np.full(n, np.nan) if birth is None else birth_year(birth)
        return np.column_stack([self.names.logit(text(name, self.std)), self.flag_code(flag, n) - 1, year, legal(name, self.std).astype(float)])

    def classify(self, name: pd.Series, flag: pd.Series | None = None, birth: pd.Series | None = None,
                 ids: pd.Series | None = None) -> pd.DataFrame:
        """Per record: kind (2 company, 1 person, 0 not sure), kind_p (the probability of a company), kind_by (engine,
        flag or people), name_p (what the name and its legal form alone say, the flag aside: the review sheet's other view),
        kind_flagged and kind_held. The engine calls a kind it is sure of: past its lines, fitted on people's answers;
        without them, a written legal form or a name past spec.name_line. Else the file's flag decides; with none, not
        sure. kind_flagged: the engine's sure call against the flag, no person has answered: matched as the engine says,
        and listed for people (kind_review_sheet). kind_held: people looked and can't tell (0): the name goes to neither
        side (er.standardize.prepare), so its pairs have no name compared and go to people."""
        X = self.features(name, flag, birth)
        name_p = np.where(X[:, 3] == 1, 1.0, 1 / (1 + np.exp(-X[:, 0])))
        flag_code = X[:, 1] + 1  # 2 company, 1 person, NaN none
        if (f := self.fitted) is not None:
            p = f.combiner.predict_proba(np.where(self.blank, 0.0, X))[:, 1]
            sure = np.where(p >= f.line_company, COMPANY, np.where(1 - p >= f.line_person, PERSON, UNSURE))
        else:  # no answers: a written legal form, or a name the model is sure of
            p, line = name_p, self.spec.name_line
            sure = np.where((X[:, 3] == 1) | (p >= line), COMPANY, np.where(p <= 1 - line, PERSON, UNSURE))
        nameless = name.isna().to_numpy()  # nothing to judge, nor a line was placed on: the flag alone, no lean
        p = X[:, 1] if self.spec.trust_flag else p  # the flag taken as it is: it is the engine's word
        sure, p = np.where(nameless | self.spec.trust_flag, UNSURE, sure), np.where(nameless, np.nan, p)
        kind = np.where(sure != UNSURE, sure, np.nan_to_num(flag_code, nan=UNSURE))
        by = np.where((sure == UNSURE) & ~np.isnan(flag_code), "flag", "engine").astype(object)  # where the kind came from
        unknown = np.zeros(len(name), dtype=bool)
        if self.decided and ids is not None:  # people's answers stand; 0, they can't tell, keeps the engine's lean
            said = ids.map(self.decided).to_numpy(dtype=float)
            hit, unknown = ~np.isnan(said), said == UNSURE
            kind, by = np.where(hit, said, kind), np.where(hit, "people", by)
            p = np.where(hit & ~unknown, said == COMPANY, p).astype(float)
        flagged = (by != "people") & (sure != UNSURE) & ~np.isnan(flag_code) & (sure != np.nan_to_num(flag_code))
        return pd.DataFrame({"kind": kind.astype(np.int8), "kind_p": p, "kind_by": by, "name_p": name_p, "kind_flagged": flagged,
                             "kind_held": ~nameless & unknown, "kind_name": name.astype("string").to_numpy()}, index=name.index)


def merge_answers(kept: pd.DataFrame | None, given: pd.DataFrame | None, uid: str) -> pd.DataFrame | None:
    """People's answers over several sheets: per record the newest filled answer (kind 1, 2 or 0, can't tell). A blank
    row answers nothing, so it never erases an older answer, and its record comes back on the next sheet. O(answers)."""
    parts = [d[pd.to_numeric(d["kind"], errors="coerce").isin([PERSON, COMPANY, UNSURE]).to_numpy()] for d in (given, kept) if d is not None and len(d)]
    parts = [d for d in parts if len(d)]
    return pd.concat(parts, ignore_index=True).drop_duplicates(uid, keep="first").reset_index(drop=True) if parts else None


def lines(p: np.ndarray, company: np.ndarray, spec: KindSpec) -> tuple[float, float, float | None]:
    """Each side's line from out-of-fold probabilities on people's answers: the company line is the lowest grid point
    with no labelled person above it, then margin_steps stricter, one more on fewer answers than labels_to_draw (at
    1,000 answers, 2 steps broke the budget in 4 of 60 trials); the person line the lowest whose labelled wrong share
    has a one-sided 95% upper bound (Clopper–Pearson) within person_wrong_at_most: with none wrong, 300 answers above
    it. A share measured on few answers can hide a rate over budget (reports/choose_kind.md). Above 1: never."""
    from scipy.stats import beta
    grid = list(spec.grid)
    clean = [g for g in grid if not ((p >= g) & ~company).any() and (p >= g).any()]
    steps = spec.margin_steps + (len(p) < spec.labels_to_draw)  # fewer answers than the measuring draw: one step stricter
    line_c = grid[min(grid.index(clean[0]) + steps, len(grid) - 1)] if clean else 1.01
    line_p, error = 1.01, None
    for g in grid:
        above = (1 - p) >= g
        n, wrong = int(above.sum()), int((above & company).sum())
        if wrong < n and beta.ppf(0.95, wrong + 1, n - wrong) <= spec.person_wrong_at_most:
            line_p, error = g, wrong / n
            break
    return line_c, line_p, error


def classifier(settings, spec: KindSpec, labels: pd.DataFrame | None = None) -> Classifier:
    """The kind for a run. People's answers (a filled-in kind_review.parquet: kind = 1, 2, or 0 can't tell) stand for
    their records; 1 and 2 train the combiner. Only the answers drawn to measure (why = measure) place the lines
    and measure the flag: the records sent to decide were picked because they look wrong, so every error rate on them
    would look worse than it is. Without answers: the name model and written legal forms only."""
    uid = settings.data.unique_id
    c = Classifier(spec=spec, std=settings.standardize, flag_company=settings.flag_company, names=name_model(settings, spec), uid=uid)
    if labels is None or not len(labels):
        return c
    lab = labels.assign(kind=pd.to_numeric(labels["kind"], errors="coerce"))
    lab = lab[lab["kind"].isin([PERSON, COMPANY, UNSURE])]
    c.decided = dict(zip(lab[uid].astype("string"), lab["kind"].astype(int))) if uid in lab else None
    lab = lab[lab["kind"] != UNSURE]  # can't tell: it stands for its record, and teaches the engine nothing
    measure = (lab["why"] == "measure").to_numpy() if "why" in lab else np.ones(len(lab), dtype=bool)
    at_random = measure & ((lab["drawn"] == "at random").to_numpy() if "drawn" in lab else True)
    col = lambda *names: next((lab[n] for n in names if n in lab), None)  # the sheet shows the flag as `flag`
    flag = col("kind_flag", "flag")
    if flag is not None and flag[at_random].notna().any():  # the flag against people, where the draw didn't look
        d = at_random & flag.notna().to_numpy()
        c.flag_error, c.flag_checked = float((c.flag_code(flag[d], int(d.sum())) != lab["kind"].to_numpy()[d]).mean()), int(d.sum())
    y = (lab["kind"] == COMPANY).to_numpy()
    c.labels, c.measured = len(lab), int(measure.sum())
    # no line without 50 answers drawn to measure, of both kinds: a combiner then would call nothing, so the engine's own rule decides
    if spec.trust_flag or c.measured < 50 or y[measure].all() or not y[measure].any():
        return c
    if "name" not in lab:  # a file of IDs and kinds: they stand for their records, and teach the engine nothing without a name
        return c
    X = c.features(lab["name"], flag, col("birth_date"))
    c.blank = np.isnan(X).all(axis=0)
    X = np.where(c.blank, 0.0, X)
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    make = lambda: HistGradientBoostingClassifier(max_depth=spec.depth, max_iter=100, learning_rate=0.1, random_state=0)
    oof = cross_val_predict(make(), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")[:, 1]
    c.fitted = Fitted(make().fit(X, y), *lines(oof[measure], y[measure], spec))
    return c


def kind_review_sheet(con: duckdb.DuckDBPyConnection, records: str, uid: str, spec: KindSpec, flag_company: tuple[str, ...],
                      answered: Iterable[str] = ()) -> pd.DataFrame:
    """Records for people, as matching's review sheet holds pairs, from the table `records` (each record's kind, kind_p,
    kind_by, name_p, kind_flagged and kind_name, the name as written; kind_flag and birth_date if the file has them). Two
    kinds of row, none already answered (`answered`) or decided by people:

        decide    flagged: the engine is sure of a kind the file's flag contradicts; the record is matched as the engine
                  says, and an answer sets it right if the engine is wrong. Surest first, at most spec.review_max.
        measure   optional: spec.labels_to_draw records drawn at random, a flagged one among them flagged too (sheet_parts), to measure the flag and the engine, and to
                  place the engine's lines on this file (Classifier.fitted) once 50 hold both kinds: not stratified, since
                  a draw that over-represents the records the engine is surest of makes the error above a line look
                  smaller than it is (reports/choose_kind.md). The draw follows a hash of the record ID: the same file
                  gives the same sheet. A record without a name has nothing to judge: it is left out.

    The rows are picked in DuckDB, so only they reach Python. Each says in words why it is there (reason), what the
    engine says, what the name alone says and what the flag says; people write kind: 1 person, 2 company, 0 can't tell.
    O(N) in SQL, O(rows) in Python."""
    u, cols = q(uid), {c for c, *_ in con.execute(f"DESCRIBE {records}").fetchall()}
    has_flag, dated = "kind_flag" in cols, "birth_date" in cols
    says = ", ".join(map(lit, flag_company)) or "NULL"
    code = f"CASE WHEN kind_flag IS NULL THEN NULL WHEN kind_flag IN ({says}) THEN {COMPANY} ELSE {PERSON} END" if has_flag else "NULL::INT"
    con.register("er_answered", pd.DataFrame({uid: pd.Series(list(answered), dtype="string").dropna()}))  # one NULL: NOT IN keeps no row
    rows = con.sql(f"""WITH r AS (
            SELECT {u}, kind_name AS name, {"kind_flag, " if has_flag else ""}{"birth_date, " if dated else ""}kind, kind_p, name_p,
                   coalesce(kind_flagged, FALSE) AS flagged, {code} AS flag_code, hash({u}) AS h
            FROM {records} WHERE kind_name IS NOT NULL AND kind_by <> 'people' AND {u} NOT IN (SELECT {u} FROM er_answered)),
        m AS (SELECT 'measure' AS why, *, row_number() OVER (ORDER BY h) AS k FROM r ORDER BY h LIMIT {spec.labels_to_draw}),
        d AS (SELECT 'decide' AS why, *, row_number() OVER (ORDER BY abs(coalesce(kind_p, 0.5) - 0.5) DESC, h) AS k
              FROM r WHERE flagged AND {u} NOT IN (SELECT {u} FROM m))
        SELECT * FROM m UNION ALL SELECT * FROM d WHERE k <= {spec.review_max} ORDER BY why, k""").df()  # decide first
    con.unregister("er_answered")
    pct = lambda x: f"{max(x, 1 - x):.1%}"
    flag = rows["flag_code"].fillna(0).astype(int)
    reason = np.where(rows["flagged"].to_numpy(dtype=bool),
                      [f"the engine is sure it is {SAYS[k]} ({pct(x)}), the flag says {SAYS[f] if f else f}: matched as the engine says" for k, x, f in zip(rows["kind"], rows["kind_p"], flag)], "")
    words = "drawn at random, to measure the flag and the engine"
    measure = (rows["why"] == "measure").to_numpy()
    rows["reason"] = np.where(reason != "", reason, words)  # a flagged record says why it is flagged, drawn or not (drawn says that)
    rows["drawn"] = np.where(measure, "at random", "")
    rows["engine_says"] = rows["kind"].map(SAYS)
    rows["name_says"] = [f"{SAYS[COMPANY if x >= 0.5 else PERSON]} ({pct(x)})" if pd.notna(x) else "" for x in rows["name_p"]]
    sheet = rows.rename(columns={"kind": "engine", "kind_p": "engine_p", "kind_flag": "flag"})
    front = ["why", "reason", "engine_says", "name_says", *(["flag"] if has_flag else []), "name", *(["birth_date"] if dated else [])]
    return sheet[[uid, *front, "engine", "engine_p", "name_p", "drawn", "flagged"]].assign(kind=pd.Series(pd.NA, index=sheet.index, dtype="Int8"))


def sheet_parts(sheet: pd.DataFrame) -> pd.Series:
    """Each row of a person/company sheet by what it asks of people: decide, a flagged record, drawn at random or not;
    measure, one drawn at random only, optional. O(rows)."""
    flagged = sheet["flagged"].fillna(False).astype(bool) if "flagged" in sheet else sheet["why"].eq("decide")
    return pd.Series(np.where(flagged, "decide", sheet["why"]), index=sheet.index)

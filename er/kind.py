"""Person or company: each record's kind, from its name and the file's flag (config/pipeline.toml [kind]).

    legal form   written where banks write it (er.config.legal_pattern): a company, near certain
    name model   logistic regression on the name's character n-grams (1 to KindSpec.ngram), legal forms and spaces
                 removed; trained once on public reference data by scripts/train_name_model.py: config/kind_names.npz

Each record gets kind (2 company, 1 person, 0 not sure: the codes a person/company flag uses): the engine's call where
it is sure (a written legal form, or a name past name_line either way; a person's name never against a company
flag), else the file's flag. kind_p (the probability of a company), kind_by (engine or flag), name_p (what its name
alone says), kind_flagged (the engine sure against the flag: matched as the engine says). A name routed by kind (er.standardize.prepare) goes to the side of its kind.
Chosen at design time, on labelled synthetic data. O(N·L·g) to score N records (g n-gram lengths), O(T·L·g) once to train on T
reference names.
"""
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from er.config import InputError, KindSpec, Standardization, legal_pattern
from er.standardize import normalize
from er.engine.duckdb import connect

VERSION = 2  # of the name model's training: a change here trains it again


def legal(names: pd.Series, std: Standardization) -> np.ndarray:
    """Whether each name holds a legal form where banks write one."""
    s = normalize(names.astype("string"), ("strip_spaces", "nfkc", "katakana"), std)  # かぶしきがいしゃ is カブシキガイシャ
    return s.str.contains(legal_pattern(std), regex=True).fillna(False).to_numpy(dtype=bool)


def text(names: pd.Series, std: Standardization) -> pd.Series:
    """What the name model reads: the name folded, without spaces or legal forms."""
    return normalize(names.astype("string"), ("strip_spaces", "nfkc", "katakana", "strip_legal_form", "kana_fold"), std)  # as any_name reads it


class NameModel:
    """Logistic regression on a name's character n-grams; saved as its terms and weights, no pickle. It scores in
    DuckDB: every name's distinct n-grams in one query, joined to the weights, the same sums as scikit-learn's
    vectorizer builds one name at a time in Python, three times faster."""

    def __init__(self, terms: list[str], coef: np.ndarray, intercept: float, ngram: int, compute: dict | None = None):
        self.terms, self.coef, self.intercept, self.ngram, self.compute = terms, coef, intercept, ngram, compute
        self.engine = connect(compute)  # the run's limits: it scores every chunk's names
        self.engine.register("er_weights", pd.DataFrame({"term": terms, "w": coef}))
        self.engine.run("CREATE TABLE weights AS SELECT * FROM er_weights")
        self.engine.unregister("er_weights")

    def __reduce__(self) -> tuple:  # sent to a process cleaning chunks beside others (steps.load): built again there, on one thread
        return NameModel, (self.terms, self.coef, self.intercept, self.ngram, {**(self.compute or {}), "threads": "1"})

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
            self.engine.register("er_names", pd.DataFrame({"r": np.arange(len(names)), "t": np.asarray(names, dtype=object)}))
            sums = self.engine.numpy(f"""SELECT r, sum(w ORDER BY term) AS s FROM (SELECT DISTINCT r, substr(t, i, n) AS term FROM
                (SELECT r, t, n, unnest(range(1, length(t) - n + 2)) AS i FROM er_names, (SELECT unnest(range(1, {self.ngram} + 1)) AS n)))
                JOIN weights USING (term) GROUP BY r""")
            self.engine.unregister("er_names")
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


KIND_COLUMNS = ("kind", "kind_p", "kind_by", "name_p", "kind_flagged", "kind_name", "customer_kind")  # what a run writes on each record and customer
NAME_MODEL = Path("config") / "kind_names.npz"  # trained by scripts/train_name_model.py, tracked in git: every run loads it


def name_key(settings, spec: KindSpec) -> str:
    """What of a run's settings the name model was trained under: a run refuses a model trained under others."""
    std = settings.standardize
    return hashlib.sha256(f"{VERSION}|{spec.ngram}|{std.legal_forms}|{std.legal_front}|{std.legal_end}|"
                          f"{sorted(std.kana_fold.items())}".encode()).hexdigest()


def name_model(settings, spec: KindSpec) -> NameModel:
    """The name model a run loads, config/kind_names.npz: trained once, on public data only, by
    scripts/train_name_model.py (design.generate.train_name_model). A run never trains it."""
    if (m := NameModel.load(settings.root / NAME_MODEL, name_key(settings, spec), settings.compute)) is None:
        raise InputError(f"{NAME_MODEL}: missing, or trained under other settings (the legal forms, the kana folding or [kind] ngram)",
                         fix="run scripts/train_name_model.py and commit config/kind_names.npz")
    return m


PERSON, COMPANY, UNSURE = 1, 2, 0  # the codes of kind and customer_kind: as a person/company flag writes them
SAYS = {PERSON: "1 person", COMPANY: "2 company", UNSURE: "0 not sure"}


@dataclass
class Classifier:
    spec: KindSpec
    std: Standardization
    flag_company: tuple[str, ...]
    names: NameModel

    def flag_code(self, flag: pd.Series | None, n: int) -> np.ndarray:  # the flag as 2 (company), 1 (person), NaN (none)
        if flag is None:
            return np.full(n, np.nan)
        said = flag.astype("string").str.normalize("NFKC").str.strip()  # "２" and "2 " (a padded field) are 2
        return np.where(flag.isna(), np.nan, np.where(said.isin(self.flag_company), COMPANY, PERSON)).astype(float)

    def classify(self, name: pd.Series, flag: pd.Series | None = None) -> pd.DataFrame:
        """Per record: kind (2 company, 1 person, 0 not sure), kind_p (the probability of a company), kind_by (engine or
        flag: where the kind came from), name_p (what the name and its legal form alone say), kind_flagged (the engine
        sure against the flag: matched as the engine says) and kind_name, the name as written. The engine calls a kind
        it is sure of: a written legal form, or a name past spec.name_line either way; but a name that reads as a
        person's never overrides a company flag (a company's records under its representative's name read so, and
        matched as a person they merge into the representative's own). Else the file's flag decides; with none, not
        sure. With spec.trust_flag, the flag decides every record."""
        written = legal(name, self.std)
        name_p = np.where(written, 1.0, 1 / (1 + np.exp(-self.names.logit(text(name, self.std)))))
        flag_code = self.flag_code(flag, len(name))  # 2 company, 1 person, NaN none
        line = self.spec.name_line
        sure = np.where(written | (name_p >= line), COMPANY, np.where(name_p <= 1 - line, PERSON, UNSURE))
        sure = np.where((sure == PERSON) & (flag_code == COMPANY), UNSURE, sure)  # the company flag stands
        nameless = name.isna().to_numpy()  # nothing to judge: the flag alone, no lean
        p = flag_code - 1 if self.spec.trust_flag else name_p  # the flag taken as it is: it is the engine's word
        sure, p = np.where(nameless | self.spec.trust_flag, UNSURE, sure), np.where(nameless, np.nan, p)
        kind = np.where(sure != UNSURE, sure, np.nan_to_num(flag_code, nan=UNSURE))
        by = np.where((sure == UNSURE) & ~np.isnan(flag_code), "flag", "engine").astype(object)
        flagged = (sure != UNSURE) & ~np.isnan(flag_code) & (sure != np.nan_to_num(flag_code))
        return pd.DataFrame({"kind": kind.astype(np.int8), "kind_p": p, "kind_by": by, "name_p": name_p, "kind_flagged": flagged,
                             "kind_name": name.astype("string").to_numpy()}, index=name.index)


def classifier(settings, spec: KindSpec) -> Classifier:
    """The kind for a run: the name model and the written legal forms, then the file's flag."""
    return Classifier(spec=spec, std=settings.standardize, flag_company=settings.flag_company, names=name_model(settings, spec))

"""Typed, frozen configuration. Notebooks build these in their Configuration cell; nothing here names a column."""
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from er.strings import FUNCTIONS, Function

Normalizer = Literal["nfkc", "strip_spaces", "kana_fold", "strip_legal_form", "address"]


class OverBudget(Exception):
    """A rule or candidate generator would exceed the Budget; raised before any join runs."""


def column_name(base: str, normalize: tuple[Normalizer, ...]) -> str:
    """The derived column holding normalized values. Plain identifier characters only: Splink builds unquoted
    table names (term-frequency tables) from column names."""
    return f"{base}__{'_'.join(normalize)}" if normalize else base


# ---------- standardization ----------

@dataclass(frozen=True, kw_only=True)
class Derived:
    name: str
    sources: tuple[tuple[str, ...], ...]      # first source whose columns are all filled wins (concatenated)
    normalize: tuple[Normalizer, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Standardization:
    kana_fold: Mapping[str, str]              # character → replacement
    legal_forms: tuple[str, ...]
    prefectures: tuple[str, ...]
    address_replacements: tuple[tuple[str, str], ...]  # regex → replacement, after NFKC
    address_cut_at: str                       # drop everything after this (building / room)
    derived: tuple[Derived, ...]


@dataclass(frozen=True)
class Key:
    column: str
    normalize: tuple[Normalizer, ...] = ()

    @property
    def name(self) -> str:
        return column_name(self.column, self.normalize)


def keys_sql(keys: tuple[Key, ...]) -> str:
    return " AND ".join(f'l."{k.name}" = r."{k.name}"' for k in keys)


# ---------- matching ----------

@dataclass(frozen=True)
class Comparator:
    function: Function
    threshold: float | None = None            # similarity floor or distance ceiling; unused for exact
    normalize: tuple[Normalizer, ...] = ()    # applied in order, once per record

    def column(self, base: str) -> str:       # the (derived) column the SQL compares
        return column_name(base, self.normalize)

    def sql(self, base: str, level: bool = False) -> str:
        """Blocking-rule SQL (l."c" / r."c"), or with level=True Splink comparison-level SQL ("c_l" / "c_r")."""
        c = self.column(base)
        a, b = (f'"{c}_l"', f'"{c}_r"') if level else (f'l."{c}"', f'r."{c}"')
        if self.function == "exact":
            return f"{a} = {b}"
        return f'cl_{self.function}({a}, {b}) {">=" if FUNCTIONS[self.function].similarity else "<="} {self.threshold}'


@dataclass(frozen=True, kw_only=True)
class Rule:
    name: str
    exact: tuple[str, ...]                    # raw equality
    fuzzy: tuple[str, ...] = ()               # compared with the stage's comparator for that column


@dataclass(frozen=True, kw_only=True)
class Stage:
    name: str
    rules: tuple[Rule, ...]
    comparators: Mapping[str, Comparator] = field(default_factory=dict)

    def keys(self, rule: Rule) -> list[str]:  # equi-join columns: they decide the blocks, so the work P
        return [*rule.exact, *(self.comparators[c].column(c) for c in rule.fuzzy if self.comparators[c].function == "exact")]

    def sql(self, rule: Rule) -> str:
        return " AND ".join([f'l."{c}" = r."{c}"' for c in rule.exact] + [self.comparators[c].sql(c) for c in rule.fuzzy])


@dataclass(frozen=True, kw_only=True)
class Budget:
    max_candidate_pairs: int                  # per rule / generator; above this the run stops before any join
    max_block_size: int
    target_rows: int                          # production row count, for the P projection
    benchmark_pairs: int                      # pairs timed per (column, function) to estimate seconds


# ---------- resolution ----------

@dataclass(frozen=True, kw_only=True)
class Resolver:
    method: Literal["connected_components", "constrained"]
    cannot_link: tuple[str, ...] = ()         # constrained: refuse a merge whose clusters hold disjoint values here


@dataclass(frozen=True, kw_only=True)
class RulesSpec:
    standardize: Standardization
    stages: tuple[Stage, ...]
    resolver: Resolver
    budget: Budget

    def __post_init__(self) -> None:
        names = [r.name for s in self.stages for r in s.rules]
        assert len(set(names)) == len(names), "duplicate rule names"
        assert len({s.name for s in self.stages}) == len(self.stages), "duplicate stage names"
        for s in self.stages:
            for r in s.rules:
                missing = [c for c in r.fuzzy if c not in s.comparators]
                assert not missing, f"{r.name}: no comparator in stage {s.name} for {missing}"
                assert s.keys(r), f"{r.name}: needs an exact column, or every pair is compared (O(N²))"
            for c, comp in s.comparators.items():
                assert comp.function == "exact" or comp.threshold is not None, f"{s.name}.{c}: threshold missing"

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        return [(c, comp.normalize) for s in self.stages for c, comp in s.comparators.items() if comp.normalize]

    def used(self) -> set[str]:
        return {c for s in self.stages for r in s.rules for c in (*r.exact, *r.fuzzy)}


def with_comparators(spec: RulesSpec, stage: str, comparators: Mapping[str, Comparator]) -> RulesSpec:
    return replace(spec, stages=tuple(replace(s, comparators={**s.comparators, **comparators}) if s.name == stage else s
                                      for s in spec.stages))


# ---------- candidates (probabilistic stage) ----------

@dataclass(frozen=True, kw_only=True)
class KeyBlocker:
    name: str
    keys: tuple[Key, ...]                     # all equal → candidate pair


@dataclass(frozen=True, kw_only=True)
class SortedNeighbourhood:
    name: str
    key: Key
    window: int                               # records within this many positions after sorting


@dataclass(frozen=True, kw_only=True)
class TfidfNeighbours:
    name: str
    key: Key
    ngram: tuple[int, int]                    # character n-gram range
    k: int                                    # neighbours per query record
    min_cosine: float


Blocker = KeyBlocker | SortedNeighbourhood | TfidfNeighbours


# ---------- Fellegi–Sunter (probabilistic stage) ----------

@dataclass(frozen=True, kw_only=True)
class Level:
    label: str
    any_of: tuple[tuple[str, Comparator], ...]  # (column, comparator) conditions, OR'd
    tf: bool = False                          # term-frequency adjust this level (on the comparison's tf key)


@dataclass(frozen=True, kw_only=True)
class Comparison:
    name: str
    levels: tuple[Level, ...]                 # most to least similar; an else level is added
    null_if_missing: tuple[str, ...]          # null level when none of these is filled on both sides
    tf: Key | None = None


@dataclass(frozen=True, kw_only=True)
class FSModel:
    name: str
    comparisons: tuple[Comparison, ...]
    prior_rules: tuple[tuple[Key, ...], ...]  # near-certain rules for the prior λ
    prior_recall: float                       # their assumed recall
    u_max_pairs: float
    m_method: Literal["em", "labels"]
    em_rules: tuple[tuple[Key, ...], ...]     # one EM session per rule
    seed: int

    def u_keys(self) -> dict[str, str]:
        """What each comparison's u depends on, besides the fitting records: the comparison (term-frequency adjustment
        aside), the sample size and the seed. Equal keys give identical u, also across models."""
        return {c.name: repr((replace(c, tf=None), self.u_max_pairs, self.seed)) for c in self.comparisons}

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        out = [(col, comp.normalize) for c in self.comparisons for lv in c.levels for col, comp in lv.any_of if comp.normalize]
        keys = [k for c in self.comparisons if c.tf for k in [c.tf]] + [k for rule in (*self.prior_rules, *self.em_rules) for k in rule]
        return out + [(k.column, k.normalize) for k in keys if k.normalize]


@dataclass(frozen=True, kw_only=True)
class ProbSpec:
    standardize: Standardization
    previous_stage: str                       # whose clusters / pairs this stage builds on
    stage: str
    blockers: tuple[Blocker, ...]
    model: FSModel
    min_match_weight: float                   # accept a pair at or above this (bits); probability = 1 / (1 + 2^−w)
    resolver: Resolver
    budget: Budget

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        keys = [k for b in self.blockers for k in (b.keys if isinstance(b, KeyBlocker) else (b.key,))]
        return [(k.column, k.normalize) for k in keys if k.normalize] + self.model.normalized()

    def used(self) -> set[str]:  # every column the SQL or the generators read, after normalization
        m = self.model
        cols = {k.name for b in self.blockers for k in (b.keys if isinstance(b, KeyBlocker) else (b.key,))}
        cols |= {comp.column(col) for c in m.comparisons for lv in c.levels for col, comp in lv.any_of}
        cols |= {col for c in m.comparisons for col in c.null_if_missing} | {c.tf.name for c in m.comparisons if c.tf}
        return cols | {k.name for rule in (*m.prior_rules, *m.em_rules) for k in rule}


def with_level(model: FSModel, comparison: str, label: str, **changes: object) -> FSModel:
    """Change the non-exact comparators of one level, e.g. with_level(m, "name", "fold JW high", threshold=0.95)
    or function="levenshtein", threshold=1."""
    def level(lv: Level) -> Level:
        return replace(lv, any_of=tuple((col, comp if comp.function == "exact" else replace(comp, **changes))
                                        for col, comp in lv.any_of)) if lv.label == label else lv
    found = [lv for c in model.comparisons if c.name == comparison for lv in c.levels if lv.label == label]
    assert found, f"no level {label!r} in comparison {comparison!r}"
    return replace(model, comparisons=tuple(replace(c, levels=tuple(map(level, c.levels))) if c.name == comparison else c
                                            for c in model.comparisons))


def without_tf(model: FSModel) -> FSModel:
    return replace(model, comparisons=tuple(replace(c, tf=None) for c in model.comparisons))


# ---------- data, search ----------

@dataclass(frozen=True, kw_only=True)
class Data:
    silver_dir: Path                          # <dataset>.csv: input records
    labels_dir: Path                          # <dataset>.csv: truth, read only to evaluate
    gold_dir: Path                            # <dataset>.csv: resolved entities, written by the last stage
    artifacts_dir: Path                       # {matched,resolved,unresolved}/<dataset>/<stage>_*.csv
    experiments_dir: Path                     # leaderboard.csv
    models_dir: Path
    datasets: tuple[str, ...]                 # every dataset a notebook writes outputs for: train, val, test
    unique_id: str
    entity_id: str                            # truth column
    show_rows: int


@dataclass(frozen=True, kw_only=True)
class ThresholdRule:
    """Pick min_match_weight on out-of-fold (cross-validated) train scores: the lowest grid weight with at most
    `max_fp` false-positive pairs and an FP-rate upper bound ≤ `max_fp_rate_hi`, then `margin_steps` grid steps
    stricter, as a safety margin against noise."""
    grid: tuple[float, ...]
    max_fp: int
    max_fp_rate_hi: float
    margin_steps: int


@dataclass(frozen=True)
class Candidate:
    function: Function
    normalize: tuple[Normalizer, ...] = ()
    low: float | None = None                  # threshold range; unused for exact
    high: float | None = None
    step: float | None = None

    @property
    def label(self) -> str:
        return f"{'+'.join(self.normalize) or 'raw'}→{self.function}"


@dataclass(frozen=True, kw_only=True)
class Tune:
    stage: str                                # the stage whose comparators are searched
    space: Mapping[str, tuple[Candidate, ...]]
    n_trials: int                             # the only bound: a wall-clock timeout would make the front depend on machine speed
    seed: int
    storage_path: Path                        # SQLite file the study is saved to; optuna-dashboard reads it
    study_prefix: str                         # each run is a new study: <prefix>_<timestamp>
    dashboard_host: str
    dashboard_port: int


@dataclass(frozen=True, kw_only=True)
class ProbTune:
    """Search over whole components of the probabilistic stage, not just thresholds."""
    toggle_blockers: tuple[str, ...]          # generators a trial may switch off
    m_methods: tuple[Literal["em", "labels"], ...]
    tf_options: tuple[bool, ...]
    level_thresholds: Mapping[tuple[str, str], tuple[float, float, float]]  # (comparison, level) → low, high, step
    resolvers: Mapping[str, Resolver]
    n_trials: int                             # the only bound, as in Tune
    seed: int
    storage_path: Path
    study_prefix: str
    dashboard_host: str
    dashboard_port: int

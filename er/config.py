"""Typed, frozen configuration, loaded from config/pipeline.toml (load_pipeline) and written back (dump_pipeline).
Everything is in field names (config/settings.toml [columns]); nothing here names a file's column."""
import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from er.strings import FUNCTIONS, Function

Normalizer = Literal["nfkc", "strip_spaces", "kana_fold", "strip_legal_form", "address", "initial", "first3", "reverse"]


class InputError(ValueError):
    """Something in the input, or in how its columns are mapped, that people must fix; `fix` says how. scripts/resolve.py
    prints the two as lines, not a traceback."""

    def __init__(self, message: str, fix: str = ""):
        super().__init__(message)
        self.fix = fix


class OverBudget(InputError):
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
        test = f'cl_{self.function}({a}, {b}) {">=" if FUNCTIONS[self.function].similarity else "<="} {self.threshold}'
        return test if level else f"({a} = {b} OR {test})"  # a rule: equal values pass without the Python call


@dataclass(frozen=True, kw_only=True)
class Rule:
    name: str
    exact: tuple[str, ...]                    # raw equality
    fuzzy: tuple[str, ...] = ()               # compared with the stage's comparator for that column
    blocking: tuple[Key, ...] = ()            # extra exact keys that only limit the join, e.g. a name initial


@dataclass(frozen=True, kw_only=True)
class Stage:
    name: str
    rules: tuple[Rule, ...]
    comparators: Mapping[str, Comparator] = field(default_factory=dict)

    def keys(self, rule: Rule) -> list[str]:  # equi-join columns: they decide the blocks, so the work P
        return [*rule.exact, *(self.comparators[c].column(c) for c in rule.fuzzy if self.comparators[c].function == "exact"),
                *(k.name for k in rule.blocking)]

    def sql(self, rule: Rule) -> str:
        return " AND ".join([f'l."{c}" = r."{c}"' for c in (*rule.exact, *(k.name for k in rule.blocking))]
                            + [self.comparators[c].sql(c) for c in rule.fuzzy])


@dataclass(frozen=True, kw_only=True)
class Budget:
    max_pairs_per_record: float               # design time (scripts/choose.py): a rule / generator's pairs, now and projected to
                                              # target_rows, above this × records refuse the key; per record, so it means the same
                                              # at any size. A run on a file never stops on it: it samples oversized blocks instead
    max_block_size: int                       # design time: the most records one key value may hold in the labelled files
    target_rows: int                          # the size the cost checks project to
    benchmark_pairs: int                      # pairs timed per (column, function) to estimate seconds
    sample_pairs: int = 2_000                 # a run on a file: a block with more pairs than this is checked on a sample of them
                                              # first (er.candidates); no hit in 2,000 bounds its yield under 0.15%

    def min_oversized(self) -> int:  # the fewest records a block needs to have more pairs than the check sample
        return next(b for b in range(2, 10**9) if b * (b - 1) // 2 > self.sample_pairs)

    def max_pairs(self, n: int) -> int:
        return int(self.max_pairs_per_record * n)


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
        return ([(c, comp.normalize) for s in self.stages for c, comp in s.comparators.items() if comp.normalize]
                + [(k.column, k.normalize) for s in self.stages for r in s.rules for k in r.blocking if k.normalize])

    def used(self) -> set[str]:
        return {c for s in self.stages for r in s.rules for c in (*r.exact, *r.fuzzy, *(k.name for k in r.blocking))}


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


@dataclass(frozen=True, kw_only=True)
class DeletionKeys:
    name: str
    key: Key                                  # the value and each one-character deletion of it are its keys
    within: tuple[Key, ...] = ()              # all equal too: limits chance pairs between short values


Blocker = KeyBlocker | SortedNeighbourhood | TfidfNeighbours | DeletionKeys


def keys_of(b: Blocker) -> tuple[Key, ...]:  # every column a generator reads
    return b.keys if isinstance(b, KeyBlocker) else (b.key, *b.within) if isinstance(b, DeletionKeys) else (b.key,)


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
    u_from_scored: bool = False               # u measured on each scored file, m and λ from the fit (er.match.with_scored_u; an increment: refreshed_u)
    u_exact_by_counts: bool = False           # u of the leading exact levels from value counts, not the sample (er.match.exact_u)
    u_near_by_keys: bool = False              # and a one-edit level right after them, counted through one-deletion keys
    fit_u_max_pairs: float | None = None      # the fit's own u sample, if it differs (with u_from_scored its u feed only EM)

    def u_keys(self) -> dict[str, str]:
        """What each comparison's u depends on, besides the fitting records: the comparison (term-frequency adjustment
        aside), the sample size and the seed. Equal keys give identical u, also across models."""
        return {c.name: repr((replace(c, tf=None), self.u_max_pairs, self.seed)) for c in self.comparisons}

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        out = [(col, comp.normalize) for c in self.comparisons for lv in c.levels for col, comp in lv.any_of if comp.normalize]
        keys = [k for c in self.comparisons if c.tf for k in [c.tf]] + [k for rule in (*self.prior_rules, *self.em_rules) for k in rule]
        return out + [(k.column, k.normalize) for k in keys if k.normalize]


@dataclass(frozen=True, kw_only=True)
class FSSpec:
    standardize: Standardization
    previous_stage: str                       # whose clusters / pairs this stage builds on
    stage: str
    blockers: tuple[Blocker, ...]
    model: FSModel
    min_match_weight: float                   # accept a pair at or above this (bits); probability = 1 / (1 + 2^−w)
    resolver: Resolver
    budget: Budget
    bridge: bool = False                      # may join two clusters the previous stage formed
    needs: tuple[str, ...] = ()               # comparisons of which one must be compared for a merge without people

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        keys = [k for b in self.blockers for k in keys_of(b)]
        return [(k.column, k.normalize) for k in keys if k.normalize] + self.model.normalized()

    def used(self) -> set[str]:  # every column the SQL or the generators read, after normalization
        m = self.model
        cols = {k.name for b in self.blockers for k in keys_of(b)}
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
    bronze_dir: Path                          # <dataset>.parquet: records as they arrive, the input
    labels_dir: Path                          # <dataset>.parquet: truth, read only to choose and evaluate
    gold_dir: Path                            # <dataset>/: each dataset resolved, a run folder (er.run)
    experiments_dir: Path                     # leaderboard.parquet
    models_dir: Path
    datasets: tuple[str, ...]                 # every dataset scripts/choose.py writes outputs for: train, val, test
    unique_id: str
    entity_id: str                            # truth column
    synthetic: bool                           # True for generated data; real (personal) data must not be exported


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
    enabled: bool = False                     # off by default: FINAL keeps the suggestions already adopted (config/experiments.py)
    seed: int
    storage_path: Path                        # SQLite file the study is saved to; optuna-dashboard reads it
    study_prefix: str                         # each run is a new study: <prefix>_<timestamp>
    dashboard_host: str
    dashboard_port: int


@dataclass(frozen=True, kw_only=True)
class FSTune:
    """Search over whole components of the probabilistic stage, not just thresholds."""
    toggle_blockers: tuple[str, ...]          # generators a trial may switch off
    m_methods: tuple[Literal["em", "labels"], ...]
    tf_options: tuple[bool, ...]
    level_thresholds: Mapping[tuple[str, str], tuple[float, float, float]]  # (comparison, level) → low, high, step
    resolvers: Mapping[str, Resolver]
    n_trials: int                             # the only bound, as in Tune
    enabled: bool = False                     # as in Tune
    seed: int
    storage_path: Path
    study_prefix: str
    dashboard_host: str
    dashboard_port: int


# ---------- config/pipeline.toml: load, check the fields a file holds, write back ----------

@dataclass(frozen=True, kw_only=True)
class Fields:
    mandatory: tuple[str, ...]                # the run stops if any is absent
    one_of: tuple[tuple[str, ...], ...]       # ... or if every field of one group is absent
    optional: tuple[str, ...]                 # absent: whatever reads it is disabled
    labels: tuple[str, ...]                   # read only by labelled runs (choosing, evaluation)

    def declared(self) -> set[str]:
        return {*self.mandatory, *(f for g in self.one_of for f in g), *self.optional, *self.labels}


@dataclass(frozen=True, kw_only=True)
class Pipeline:
    fields: Fields
    rules: RulesSpec
    fs: FSSpec
    generators: Mapping[str, Blocker]         # every generator defined, by name; fs.blockers uses some of them
    threshold: ThresholdRule
    cv_folds: int
    cv_seed: int
    decision_p: float
    explain_show: tuple[str, ...]             # the worked example's fields
    explain_filled: tuple[str, ...]
    fit_rows: int = 30_000                    # an unlabelled run fits on a sample of this many records (er.run)


def _norm(value: object, chains: Mapping[str, tuple[Normalizer, ...]]) -> tuple[Normalizer, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if value not in chains:
            raise ValueError(f"unknown normalization chain {value!r}; [locale.chains] has {sorted(chains)}")
        return chains[value]
    return tuple(value)


def _key(v: object, chains: Mapping[str, tuple[Normalizer, ...]]) -> Key:
    return Key(v) if isinstance(v, str) else Key(v["field"], _norm(v.get("normalize"), chains))


def _comparator(d: dict, chains: Mapping[str, tuple[Normalizer, ...]]) -> Comparator:
    return Comparator(d["function"], d.get("threshold"), _norm(d.get("normalize"), chains))


def _generator(name: str, d: dict, chains: Mapping[str, tuple[Normalizer, ...]]) -> Blocker:
    match d["kind"]:
        case "keys":
            return KeyBlocker(name=name, keys=tuple(_key(k, chains) for k in d["keys"]))
        case "sorted":
            return SortedNeighbourhood(name=name, key=_key(d["key"], chains), window=d["window"])
        case "tfidf":
            return TfidfNeighbours(name=name, key=_key(d["key"], chains), ngram=tuple(d["ngram"]), k=d["k"], min_cosine=d["min_cosine"])
        case "deletions":
            return DeletionKeys(name=name, key=_key(d["key"], chains), within=tuple(_key(k, chains) for k in d.get("within", ())))
    raise ValueError(f"generator {name}: unknown kind {d['kind']!r} (keys, sorted, tfidf, deletions)")


def _resolver(d: dict) -> Resolver:
    return Resolver(method=d["method"], cannot_link=tuple(d.get("cannot_link", ())))


def pipeline_from(cfg: dict, std: Standardization, chains: Mapping[str, tuple[Normalizer, ...]]) -> Pipeline:
    """The parsed config/pipeline.toml → typed config."""
    f, b, m = cfg["fields"], cfg["budget"], cfg["model"]
    budget = Budget(**b)
    rules = RulesSpec(standardize=std, resolver=_resolver(cfg["rules"]["resolver"]), budget=budget, stages=tuple(
        Stage(name=s["name"], comparators={c: _comparator(d, chains) for c, d in s.get("comparators", {}).items()},
              rules=tuple(Rule(name=r["name"], exact=tuple(r["exact"]), fuzzy=tuple(r.get("fuzzy", ())),
                               blocking=tuple(_key(k, chains) for k in r.get("blocking", ()))) for r in s["rules"]))
        for s in cfg["rules"]["stages"]))
    generators = {name: _generator(name, d, chains) for name, d in cfg["generators"].items()}
    unknown = [g for g in m["generators"] if g not in generators]
    if unknown:
        raise ValueError(f"[model] generators: {unknown} are not defined in [generators]")
    comparisons = tuple(Comparison(
        name=c["name"], null_if_missing=tuple(c["null_if_missing"]), tf=_key(c["tf"], chains) if "tf" in c else None,
        levels=tuple(Level(label=lv["label"], tf=lv.get("tf", False),
                           any_of=tuple((a["field"], _comparator(a, chains)) for a in lv["any_of"])) for lv in c["levels"]))
        for c in m["comparisons"])
    model = FSModel(name=m["name"], comparisons=comparisons, prior_recall=m["prior_recall"], u_max_pairs=m["u_max_pairs"],
                    prior_rules=tuple(tuple(_key(k, chains) for k in r) for r in m["prior_rules"]), m_method=m["m_method"],
                    em_rules=tuple(tuple(_key(k, chains) for k in r) for r in m["em_rules"]), seed=m["seed"],
                    u_from_scored=m.get("u_from_scored", False), u_exact_by_counts=m.get("u_exact_by_counts", False),
                    u_near_by_keys=m.get("u_near_by_keys", False), fit_u_max_pairs=m.get("fit_u_max_pairs"))
    unknown = [c for c in m.get("needs", ()) if c not in {c.name for c in comparisons}]
    if unknown:
        raise ValueError(f"[model] needs: {unknown} are not comparisons in [[model.comparisons]]")
    fs = FSSpec(standardize=std, previous_stage=m["previous_stage"], stage=m["stage"], model=model,
                  blockers=tuple(generators[g] for g in m["generators"]), min_match_weight=m["min_match_weight"],
                  resolver=_resolver(m["resolver"]), budget=budget, bridge=m.get("bridge", False), needs=tuple(m.get("needs", ())))
    t, sel, d = cfg["threshold"], cfg["selection"], cfg["display"]
    return Pipeline(fields=Fields(mandatory=tuple(f["mandatory"]), one_of=tuple(map(tuple, f["one_of"])),
                                  optional=tuple(f["optional"]), labels=tuple(f["labels"])),
                    rules=rules, fs=fs, generators=generators,
                    threshold=ThresholdRule(grid=tuple(t["grid"]), max_fp=t["max_fp"], max_fp_rate_hi=t["max_fp_rate_hi"],
                                            margin_steps=t["margin_steps"]),
                    cv_folds=sel["cv_folds"], cv_seed=sel["cv_seed"], decision_p=sel["decision_p"],
                    explain_show=tuple(d["explain_show"]), explain_filled=tuple(d["explain_filled"]), fit_rows=m.get("fit_rows", 30_000))


def load_pipeline(path: Path, std: Standardization, chains: Mapping[str, tuple[Normalizer, ...]],
                  columns: Mapping[str, object]) -> Pipeline:
    """config/pipeline.toml (or a written FINAL) → typed config. Every field it reads must be declared in [fields]
    and mapped in config/settings.toml [columns]."""
    p = pipeline_from(tomllib.loads(Path(path).read_text(encoding="utf-8")), std, chains)
    read, declared = fields_read(p), p.fields.declared()
    if read - declared:
        raise ValueError(f"{path}: fields read but not declared in [fields]: {sorted(read - declared)}")
    if declared - set(columns):
        raise ValueError(f"{path}: fields not mapped in config/settings.toml [columns]: {sorted(declared - set(columns))}")
    return p


def fields_read(p: Pipeline) -> set[str]:  # every field the rules, the generators and the model read
    r, m = p.rules, p.fs.model
    out = {c for s in r.stages for rule in s.rules for c in (*rule.exact, *rule.fuzzy, *(k.column for k in rule.blocking))}
    out |= set(r.stages[-1].comparators) if r.stages else set()
    out |= {k.column for b in p.generators.values() for k in keys_of(b)}
    out |= {col for c in m.comparisons for lv in c.levels for col, _ in lv.any_of} | {col for c in m.comparisons for col in c.null_if_missing}
    out |= {c.tf.column for c in m.comparisons if c.tf} | {k.column for rule in (*m.prior_rules, *m.em_rules) for k in rule}
    out |= {*p.explain_show, *p.explain_filled} | {c for s in r.stages for c in s.comparators}
    return out


def sources_text(alternatives: object) -> str:  # a field's sources as people read them: "A, or B + C"
    return ", or ".join(" + ".join(alt) for alt in alternatives) if alternatives else "no column (unmapped)"


def check_fields(fields: Fields, present: set[str], expected: Mapping[str, object], labelled: bool = False) -> None:
    """Stop when a mandatory field, every field of a one_of group, or (for a labelled run) a label is absent; the error
    names the columns config/settings.toml [columns] expects for each."""
    fix = "map the field to the file's column in config/settings.toml [columns]"
    missing = [f for f in (*fields.mandatory, *(fields.labels if labelled else ())) if f not in present]
    if missing:
        raise InputError("the file lacks a field every run needs: " + "; ".join(f"{f} (expected in {sources_text(expected.get(f))})" for f in missing), fix)
    empty = [g for g in fields.one_of if not set(g) & present]
    if empty:
        raise InputError("the file holds none of these fields, and a run needs one: " + "; ".join(
            " / ".join(f"{f} (expected in {sources_text(expected.get(f))})" for f in g) for g in empty), fix)


def restrict(p: Pipeline, present: set[str]) -> tuple[Pipeline, list[str]]:
    """The pipeline without whatever reads an absent field, and the list of what was disabled. A level that ORs
    several conditions keeps the conditions it can still check."""
    gone: list[str] = []
    has = lambda cols: all(c in present for c in cols)
    stages = []
    for s in p.rules.stages:
        keep = []
        for r in s.rules:
            cols = (*r.exact, *r.fuzzy, *(k.column for k in r.blocking))
            (keep.append(r) if has(cols) else gone.append(f"rule {r.name} (needs {sorted(set(cols) - present)})"))
        if keep:
            stages.append(replace(s, rules=tuple(keep), comparators={c: x for c, x in s.comparators.items() if c in present}))
    if not stages:
        raise ValueError("no rule can run: every rule reads an absent field")
    blockers = []
    for b in p.fs.blockers:
        cols = [k.column for k in keys_of(b)]
        (blockers.append(b) if has(cols) else gone.append(f"generator {b.name} (needs {sorted(set(cols) - present)})"))
    if not blockers:
        raise ValueError("no candidate generator can run: every one reads an absent field")
    comparisons = []
    for c in p.fs.model.comparisons:
        levels = []
        for lv in c.levels:
            any_of = tuple((col, comp) for col, comp in lv.any_of if col in present)
            if any_of:
                levels.append(replace(lv, any_of=any_of))
            else:
                gone.append(f"level {c.name}: {lv.label} (needs {sorted({col for col, _ in lv.any_of})})")
        null = tuple(col for col in c.null_if_missing if col in present)
        if levels and null:
            tf = c.tf if c.tf and c.tf.column in present else None
            comparisons.append(replace(c, levels=tuple(levels) if tf else tuple(replace(lv, tf=False) for lv in levels),
                                       null_if_missing=null, tf=tf))
        else:
            gone.append(f"comparison {c.name}")
    m = p.fs.model
    prior = tuple(r for r in m.prior_rules if has(k.column for k in r))
    em = tuple(r for r in m.em_rules if has(k.column for k in r))
    if not prior:
        raise ValueError("no prior rule can run (λ needs one): every one reads an absent field")
    if m.m_method == "em" and not em:
        raise ValueError("no EM blocking rule can run: every one reads an absent field")
    gone += [f"prior rule {[k.column for k in r]}" for r in m.prior_rules if r not in prior]
    gone += [f"EM rule {[k.column for k in r]}" for r in m.em_rules if r not in em]
    model = replace(m, comparisons=tuple(comparisons), prior_rules=prior, em_rules=em)
    needs = tuple(n for n in p.fs.needs if n in {c.name for c in comparisons})  # [fields] one_of keeps a name comparison
    return replace(p, rules=replace(p.rules, stages=tuple(stages)), fs=replace(p.fs, blockers=tuple(blockers), model=model, needs=needs),
                   explain_show=tuple(f for f in p.explain_show if f in present),
                   explain_filled=tuple(f for f in p.explain_filled if f in present)), gone


def pipeline_dict(p: Pipeline, chains: Mapping[str, tuple[Normalizer, ...]]) -> dict:
    """The inverse of pipeline_from, with normalizations written as chain names where one matches."""
    name_of = {v: k for k, v in reversed(list(chains.items()))}  # the first chain defined wins
    norm = lambda n: name_of.get(tuple(n), list(n))
    key = lambda k: k.column if not k.normalize else {"field": k.column, "normalize": norm(k.normalize)}
    comp = lambda c: {"function": c.function, **({"threshold": c.threshold} if c.threshold is not None else {}),
                      **({"normalize": norm(c.normalize)} if c.normalize else {})}

    def gen(b: Blocker) -> dict:
        match b:
            case KeyBlocker():
                return {"kind": "keys", "keys": [key(k) for k in b.keys]}
            case SortedNeighbourhood():
                return {"kind": "sorted", "key": key(b.key), "window": b.window}
            case TfidfNeighbours():
                return {"kind": "tfidf", "key": key(b.key), "ngram": list(b.ngram), "k": b.k, "min_cosine": b.min_cosine}
            case DeletionKeys():
                return {"kind": "deletions", "key": key(b.key), **({"within": [key(k) for k in b.within]} if b.within else {})}

    resolver = lambda r: {"method": r.method, **({"cannot_link": list(r.cannot_link)} if r.cannot_link else {})}
    fs, m = p.fs, p.fs.model
    f, t = p.fields, p.threshold
    return {
        "fields": {"mandatory": list(f.mandatory), "one_of": [list(g) for g in f.one_of], "optional": list(f.optional), "labels": list(f.labels)},
        "budget": {"max_pairs_per_record": fs.budget.max_pairs_per_record, "max_block_size": fs.budget.max_block_size,
                   "target_rows": fs.budget.target_rows, "benchmark_pairs": fs.budget.benchmark_pairs, "sample_pairs": fs.budget.sample_pairs},
        "rules": {"resolver": resolver(p.rules.resolver), "stages": [
            {"name": s.name, **({"comparators": {c: comp(x) for c, x in s.comparators.items()}} if s.comparators else {}),
             "rules": [{"name": r.name, "exact": list(r.exact), **({"fuzzy": list(r.fuzzy)} if r.fuzzy else {}),
                        **({"blocking": [key(k) for k in r.blocking]} if r.blocking else {})} for r in s.rules]}
            for s in p.rules.stages]},
        "generators": {name: gen(b) for name, b in p.generators.items()},
        "model": {"previous_stage": fs.previous_stage, "stage": fs.stage, "generators": [b.name for b in fs.blockers],
                  "min_match_weight": fs.min_match_weight, "resolver": resolver(fs.resolver), "bridge": fs.bridge, "needs": list(fs.needs), "name": m.name,
                  "prior_rules": [[key(k) for k in r] for r in m.prior_rules], "prior_recall": m.prior_recall,
                  "u_max_pairs": m.u_max_pairs, "m_method": m.m_method, "em_rules": [[key(k) for k in r] for r in m.em_rules],
                  "seed": m.seed, "u_from_scored": m.u_from_scored, "u_exact_by_counts": m.u_exact_by_counts, "u_near_by_keys": m.u_near_by_keys,
                  **({"fit_u_max_pairs": m.fit_u_max_pairs} if m.fit_u_max_pairs else {}), "fit_rows": p.fit_rows,
                  "comparisons": [{"name": c.name, "null_if_missing": list(c.null_if_missing), **({"tf": key(c.tf)} if c.tf else {}),
                                   "levels": [{"label": lv.label, "any_of": [{"field": col, **comp(x)} for col, x in lv.any_of],
                                               **({"tf": True} if lv.tf else {})} for lv in c.levels]} for c in m.comparisons]},
        "threshold": {"grid": list(t.grid), "max_fp": t.max_fp, "max_fp_rate_hi": t.max_fp_rate_hi, "margin_steps": t.margin_steps},
        "selection": {"cv_folds": p.cv_folds, "cv_seed": p.cv_seed, "decision_p": p.decision_p},
        "display": {"explain_show": list(p.explain_show), "explain_filled": list(p.explain_filled)},
    }


def _toml(v: object, inline: bool = False) -> str:  # one TOML value; tables inside a section are written inline
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON's string escapes are valid TOML basic-string escapes
    if isinstance(v, dict):
        keys = lambda k: k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)
        return "{ " + ", ".join(f"{keys(k)} = {_toml(x, inline=True)}" for k, x in v.items()) + " }" if v else "{}"
    if not inline and any(isinstance(x, dict) for x in v):  # a list of tables, one per line
        return "[\n" + "".join(f"  {_toml(x, inline=True)},\n" for x in v) + "]"
    return "[" + ", ".join(_toml(x, inline=True) for x in v) + "]"


def dump_toml(cfg: dict, header: str = "") -> str:
    """A pipeline dict as TOML, in the layout of config/pipeline.toml: one [section] per top-level key, a section's
    lists of tables as [[section.key]], everything deeper inline."""
    out = [header] if header else []
    for section, body in cfg.items():
        out.append(f"\n[{section}]")
        arrays = {k: v for k, v in body.items() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)
                  and k in ("stages", "comparisons")}
        out += [f"{k} = {_toml(v)}" for k, v in body.items() if k not in arrays]
        for k, items in arrays.items():
            for item in items:
                out.append(f"\n[[{section}.{k}]]")
                out += [f"{kk} = {_toml(vv)}" for kk, vv in item.items()]
    return "\n".join(out) + "\n"


def dump_pipeline(p: Pipeline, chains: Mapping[str, tuple[Normalizer, ...]], path: Path, header: str = "") -> None:
    text = dump_toml(pipeline_dict(p, chains), header)
    assert pipeline_from(tomllib.loads(text), p.rules.standardize, chains) == p, "the written pipeline must load back unchanged"
    Path(path).write_text(text, encoding="utf-8")

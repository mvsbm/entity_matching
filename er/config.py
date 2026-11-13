"""Typed, frozen configuration, loaded from config/pipeline.toml (load_pipeline) and written back (dump_pipeline).
Everything is in field names (config/settings.toml [columns]); nothing here names a file's column."""
import json
import math
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, get_args

from er.strings import FUNCTIONS, Function

Normalizer = Literal["nfkc", "strip_spaces", "kana_fold", "strip_legal_form", "address", "initial", "first3", "reverse", "casefold", "one_byte", "one_byte_hash",
                     "katakana", "strip_separators", "long_vowel", "last3"]


class InputError(ValueError):
    """Something in the input, or in how its columns are mapped, that people must fix; `fix` says how, and `hints`
    (field → column) what the file's values suggest. nayose prints the two as lines, not a traceback."""

    def __init__(self, message: str, fix: str = "", hints: dict[str, str] | None = None):
        super().__init__(message)
        self.fix, self.hints = fix, hints or {}


def q(name: str) -> str:  # a quoted SQL identifier
    return '"' + name.replace('"', '""') + '"'


def lit(value: object) -> str:  # a value, a path or text, as an SQL string literal
    return "'" + str(value).replace("'", "''") + "'"


def bits(v: float) -> str:  # a weight in SQL; the trust line above everything is infinity
    return "'Infinity'::DOUBLE" if math.isinf(v) else repr(float(v))


def toml_of(path: Path | str) -> dict:  # a TOML file people edit, or the mistake in it as an InputError
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))  # with or without the mark an editor may put first
    except FileNotFoundError:
        raise InputError(f"{path}: no such file", fix="check the path") from None
    except OSError as e:  # a folder, or a file this user can't read
        raise InputError(f"{path}: can't be read ({e.strerror})", fix="name a TOML file you can read") from None
    except UnicodeDecodeError:
        raise InputError(f"{path}: not UTF-8 text", fix="save it as UTF-8 (in Notepad or Excel: Save As, UTF-8)") from None
    except tomllib.TOMLDecodeError as e:
        raise InputError(f"{path}: not valid TOML ({e})", fix="correct that line; quote text, and write lists as [\"a\", \"b\"]") from None


def checked(ok: object, message: str, path: Path | str = "config/settings.toml") -> None:  # a rule a settings file breaks, as an InputError
    if not ok:
        raise InputError(f"{path}: {message}", fix="correct it there")


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
    kind: str | None = None                   # "person" or "company": kept only on records that lean that kind (er.kind)


@dataclass(frozen=True, kw_only=True)
class Standardization:
    kana_fold: Mapping[str, str]              # character → replacement
    legal_forms: tuple[str, ...]              # removed wherever they stand
    legal_front: tuple[str, ...] = ()         # bank abbreviations that stand first: カ)〇〇
    legal_end: tuple[str, ...] = ()           # and last: 〇〇(カ
    prefectures: tuple[str, ...]
    address_replacements: tuple[tuple[str, str], ...]  # regex → replacement, after NFKC
    address_cut_at: str                       # drop everything after this (building / room)
    derived: tuple[Derived, ...]


SMALL_KANA = str.maketrans("ァィゥェォッャュョヮ", "アイウエオツヤユヨワ")  # banks write no small kana


def legal_pattern(std: Standardization) -> str:
    """A legal form anywhere (its reading, also with small kana written large), or a bank abbreviation where it may
    stand: first, カ)〇〇, or last, 〇〇(カ. Longest first, so 医療法人社団 isn't cut to 医療法人. On NFKC text."""
    forms = sorted({f for x in std.legal_forms for f in (x, x.translate(SMALL_KANA))}, key=len, reverse=True)
    parts = [re.escape(f) for f in forms]
    if std.legal_front:
        parts.append(f"^(?:{'|'.join(map(re.escape, sorted(std.legal_front, key=len, reverse=True)))})\\)")
    if std.legal_end:
        parts.append(f"\\((?:{'|'.join(map(re.escape, sorted(std.legal_end, key=len, reverse=True)))})$")
    return "|".join(parts)


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

    def copied(self) -> tuple[Normalizer, ...] | None:  # the steps of the column with each character one byte (er.standardize) that DuckDB compares first:
        # a similarity's, katakana as they are (one_byte); an edit distance's, any character by a hash of it (one_byte_hash), never farther apart than they are
        step = {"jaro": "one_byte", "jaro_winkler": "one_byte", "levenshtein": "one_byte_hash", "damerau_levenshtein": "one_byte_hash"}.get(self.function)
        return (*self.normalize, step) if step else None

    def copy(self, base: str) -> str | None:  # that column
        return column_name(base, steps) if (steps := self.copied()) else None

    def sql(self, base: str, level: bool = False, settled: bool = False) -> str:
        """Blocking-rule SQL (l."c" / r."c"), or with level=True Splink comparison-level SQL ("c_l" / "c_r"). DuckDB's own
        Jaro, Jaro–Winkler and Hamming are rapidfuzz's C++, so on characters of one byte each (ASCII, or the one-byte
        copy) they give the Python function's score, on every thread and without Python, and so do its edit distances on
        ASCII; on other text, its edit distance of the hashed copy (or of the bytes) fails a pair first that no edit of as
        few characters makes.
        Whatever else, the Python function, pair by pair. Each guard is a CASE: DuckDB may reorder AND and OR, never a CASE.
        `settled` (a level): TRUE or FALSE as far as DuckDB settles it in C++, NULL where only the Python function could, or
        for an edit distance past one, a table of edits (er.match.bound_sql's); a missing value fails, as in the level."""
        c = self.column(base)
        side = (lambda x: (q(f"{x}_l"), q(f"{x}_r"))) if level else (lambda x: (f"l.{q(x)}", f"r.{q(x)}"))
        a, b = side(c)
        if self.function == "exact":
            return f"coalesce({a} = {b}, FALSE)" if settled else f"{a} = {b}"
        test = self.test(a, b, *(side(self.copy(base)) if self.copy(base) else ()), settled=settled)
        if settled:
            return f"(CASE WHEN {a} IS NULL OR {b} IS NULL THEN FALSE ELSE {test} END)"
        return test if level else f"({a} = {b} OR {test})"  # a rule: equal values pass without the Python call

    def test(self, a: str, b: str, a1: str | None = None, b1: str | None = None, settled: bool = False) -> str:
        """Whether values a and b pass, as SQL (sql's, with their one-byte copies a1 and b1 if any); `settled`: NULL where
        the Python function would be asked."""
        f, t = self.function, self.threshold
        python = "NULL" if settled else f"cl_{f}_cut({a}, {b}, {t})"  # stops once it knows
        # bytes = characters, and none empty (DuckDB: '' and '' are 0 apart for rapidfuzz's 1, and hamming refuses them)
        ascii_, same = f"strlen({a}) = length({a}) AND strlen({b}) = length({b}) AND strlen({a}) > 0 AND strlen({b}) > 0", f"length({a}) = length({b})"
        if f in ("jaro", "jaro_winkler"):
            native = lambda x, y: f"CAST(CAST({f}_similarity({x}, {y}) AS FLOAT) AS DOUBLE)"  # rapidfuzz's score is a float32
            copied = f"WHEN {a1} IS NOT NULL AND {b1} IS NOT NULL THEN {native(a1, b1)} " if a1 else ""
            test = f"(CASE {copied}WHEN {ascii_} THEN {native(a, b)} ELSE {python} END) >= {t}"
        elif f == "hamming":
            test = (f"(CASE WHEN abs(length({a}) - length({b})) > {t} THEN FALSE WHEN {ascii_} AND {same} THEN hamming({a}, {b}) <= {t} "
                    f"ELSE {python} <= {t} END)")
        elif f in ("levenshtein", "damerau_levenshtein"):  # never less than the lengths' difference
            # one edit keeping the length: a substitution, or (Damerau) a swap of two, so on ASCII the Hamming distance settles all
            # but a Damerau pair two apart; one changing it, an insertion or a deletion alike. On ASCII DuckDB's own is rapidfuzz's
            # (unrestricted Damerau too); on the hashed copies it is never more than the values' distance, so a pair past t there
            # can't pass; without copies, its count of bytes edited is at most 4 per character edited (a 4-byte character for a
            # 1-byte one) and 8 per swap
            quick = (f"WHEN {ascii_} THEN (CASE WHEN {same} THEN (CASE WHEN hamming({a}, {b}) <= 1 THEN TRUE "  # hamming only on equal lengths: a CASE
                     f"WHEN hamming({a}, {b}) > {2 if f == 'damerau_levenshtein' else 1} THEN FALSE ELSE {f}({a}, {b}) <= 1 END) "
                     f"ELSE levenshtein({a}, {b}) <= 1 END) " if t == 1 else "")
            if settled and t != 1:  # its length alone: a table of edits isn't cheap
                return f"(CASE WHEN abs(length({a}) - length({b})) > {t} THEN FALSE ELSE NULL END)"
            hashed = f"WHEN {a1} IS NOT NULL AND {b1} IS NOT NULL THEN (CASE WHEN {f}({a1}, {b1}) > {t} THEN FALSE ELSE {python} <= {t} END) " if a1 else ""
            test = (f"(CASE WHEN abs(length({a}) - length({b})) > {t} THEN FALSE {quick}WHEN {ascii_} THEN {f}({a}, {b}) <= {t} {hashed}"
                    f"WHEN levenshtein({a}, {b}) > {(4 if f == 'levenshtein' else 8) * t} THEN FALSE ELSE {python} <= {t} END)")
        else:
            test = f'{python} {">=" if FUNCTIONS[f].similarity else "<="} {t}'
        return test


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
    method: Literal["connected_components"]  # er.cluster.merge: the run's clustering, the only one
    cannot_link: tuple[str, ...] = ()         # read by no resolver; kept so the config hash of a stored run stays the same


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

    def each(self) -> Iterator[tuple[int, Stage, Rule]]:  # every rule in order, with its stage: a pair's first rule wins by i
        return ((i, s, r) for i, (s, r) in enumerate((s, r) for s in self.stages for r in s.rules))

    def blockers(self) -> list["KeyBlocker"]:  # each rule's equi-join as a key generator: what a budget counts
        return [KeyBlocker(name=r.name, keys=tuple(map(Key, s.keys(r)))) for _, s, r in self.each()]

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        return ([(c, comp.normalize) for s in self.stages for c, comp in s.comparators.items() if comp.normalize]
                + [(c, comp.copied()) for s in self.stages for c, comp in s.comparators.items() if comp.copied()]
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


@dataclass(frozen=True, kw_only=True)
class EditKeys:
    name: str
    key: Key                                  # values at most `edits` edits apart (Levenshtein) are a pair: found by PassJoin
    within: tuple[Key, ...] = ()              # all equal too
    edits: int = 2


Blocker = KeyBlocker | SortedNeighbourhood | TfidfNeighbours | DeletionKeys | EditKeys


def keys_of(b: Blocker) -> tuple[Key, ...]:  # every column a generator reads
    return b.keys if isinstance(b, KeyBlocker) else (b.key, *b.within) if isinstance(b, DeletionKeys | EditKeys) else (b.key,)


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
    u_from_scored: bool = False               # u measured on each scored file, m and λ from the fit (er.match.scored_u; an increment: refreshed_u)
    u_exact_by_counts: bool = False           # u of the leading exact levels from value counts, not the sample (er.match.exact_u)
    u_near_by_keys: bool = False              # and a one-edit level right after them, counted through one-deletion keys
    fit_u_max_pairs: float | None = None      # the fit's own u sample, if it differs (with u_from_scored its u feed only EM)
    em_median: bool = False                   # one EM session per rule, each level's m the median of the sessions that learned it (not Splink's mean)
    em_from_keys: bool = False                # the EM sessions blocked on the method's equality keys, not on em_rules (er.run.fit)

    def u_keys(self) -> dict[str, str]:
        """What each comparison's u depends on, besides the fitting records: the comparison (term-frequency adjustment
        aside), the sample size and the seed. Equal keys give identical u, also across models."""
        return {c.name: repr((replace(c, tf=None), self.u_max_pairs, self.seed)) for c in self.comparisons}

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        out = [(col, comp.normalize) for c in self.comparisons for lv in c.levels for col, comp in lv.any_of if comp.normalize]
        out += [(col, comp.copied()) for c in self.comparisons for lv in c.levels for col, comp in lv.any_of if comp.copied()]
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


def without_tf(model: FSModel) -> FSModel:  # no term frequencies: neither the comparisons' keys nor their levels' flags
    return replace(model, comparisons=tuple(replace(c, tf=None, levels=tuple(replace(lv, tf=False) for lv in c.levels)) for c in model.comparisons))


# ---------- data, search ----------

@dataclass(frozen=True, kw_only=True)
class Data:
    bronze_dir: Path                          # <dataset>.parquet: records as they arrive, the input
    labels_dir: Path                          # <dataset>.parquet: truth, read only to choose and evaluate
    gold_dir: Path                            # <dataset>/: each dataset resolved, a workspace (er.run)
    experiments_dir: Path                     # leaderboard.parquet
    models_dir: Path
    datasets: tuple[str, ...]                 # every dataset scripts/choose.py writes outputs for: train, val, test
    unique_id: str
    entity_id: str                            # truth column
    synthetic: bool                           # True for generated data; real (personal) data must not be exported
    household_id: str | None = None           # truth column naming each record's household: a pair of one household's people is neither true nor false


@dataclass(frozen=True, kw_only=True)
class ThresholdRule:
    """Pick min_match_weight on out-of-fold (cross-validated) train scores: the lowest grid weight with at most
    `max_fp` false-positive pairs and an FP-rate upper bound ≤ `max_fp_rate_hi`, then `margin_steps` grid steps
    stricter, as a safety margin against noise."""
    grid: tuple[float, ...]
    max_fp: int
    max_fp_rate_hi: float
    margin_steps: int


@dataclass(frozen=True, kw_only=True)
class TrustRule:
    """The trust line: pairs scoring at or above it merge without people, because a random sample of their range came
    back clean. It starts above every step (no line: nothing merges) and is lowered a step at a time, once `checks`
    answers on the next range down hold none false: at most 1% false at 95% for 300 (the rule of three). `line` is the
    workspace's (method.toml trust, through adjust): inf, nothing merges; None, no trust line, the method as tuned."""
    steps: tuple[float, ...] = (20.0, 12.0, 8.0, 6.0, 0.0)  # bits, high to low; a rule pair below the last never merges by itself
    checks: int = 300
    watch: int = 20                           # spot-checks a run of the pairs above the line
    line: float | None = None

    def below(self, holds: Callable[[float, float], bool] | None = None) -> tuple[float, float] | None:
        """The range people check next: [a step down, the line); None at the last. With `holds` (whether [step, line)
        holds a link), the first step whose range holds one: lowering the line past ranges that hold none merges
        nothing, so people never wait on an empty range."""
        if self.line is None:
            return None
        lower = sorted((s for s in self.steps if s < self.line), reverse=True)
        return next(((s, self.line) for s in lower if holds is None or holds(s, self.line)), (lower[-1], self.line) if lower else None)


@dataclass(frozen=True, kw_only=True)
class LearnKeys:
    """The keys learned on each file, no labels (er.keys): the pairs the run's model accepts, found by sampling through
    every atom (a column the method reads, equal, or within one or `edits` edits for a column it compares by a
    similarity), and the keys of up to `max_atoms` atoms that list most of them for their pairs, by weighted set cover
    within the budget. A file where the sample finds none runs [model] generators."""
    records: int = 50_000                     # the records sampled, about: their pairs through every atom are scored
    max_atoms: int = 3
    edits: int = 2
    min_gain: int = 1                         # a key is added while it lists at least this many sampled pairs no key chosen lists


@dataclass(frozen=True, kw_only=True)
class Probe:
    """Pairs no pair key lists, sampled within groups matches tend to share (er.probe): each stratum a group as a key
    names it (records with the same phone, say), and about `pairs` pairs scored in each. It measures, without labels,
    the matches the keys miss."""
    strata: tuple[tuple[str, tuple[Key, ...]], ...] = ()
    pairs: int = 1_000_000

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        return [(k.column, k.normalize) for _, keys in self.strata for k in keys if k.normalize]

    def used(self) -> set[str]:
        return {k.name for _, keys in self.strata for k in keys}


@dataclass(frozen=True, kw_only=True)
class Household:
    """A pair people see as maybe two people of one household: its records agree on one of `shared` and, filled on
    both sides, fail one test of `apart` (another given name, another birth date). A label only: no score changes."""
    shared: tuple[Key, ...] = ()
    apart: tuple[tuple[str, Comparator], ...] = ()

    def sql(self, have: set[str]) -> str:
        """Over records l and r holding the columns `have`, those parts it can read; FALSE when it can read none of one kind."""
        shared = [k for k in self.shared if k.name in have]
        apart = [(col, comp) for col, comp in self.apart if comp.column(col) in have and (not comp.copy(col) or comp.copy(col) in have)]
        if not shared or not apart:
            return "FALSE"
        share = " OR ".join(f'l."{k.name}" = r."{k.name}"' for k in shared)
        differ = " OR ".join(f'(l."{c}" IS NOT NULL AND r."{c}" IS NOT NULL AND NOT {comp.sql(col)})' for col, comp in apart for c in [comp.column(col)])
        return f"(({share}) AND ({differ}))"

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        return ([(k.column, k.normalize) for k in self.shared if k.normalize] + [(col, comp.normalize) for col, comp in self.apart if comp.normalize]
                + [(col, comp.copied()) for col, comp in self.apart if comp.copied()])

    def used(self) -> set[str]:
        return {k.name for k in self.shared} | {comp.column(col) for col, comp in self.apart} | {comp.copy(col) for col, comp in self.apart if comp.copy(col)}


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
    identifying: tuple[str, ...] = ()         # one entity's each (a customer ID): a value on many records is a placeholder, read as missing (Run.load)

    def declared(self) -> set[str]:
        return {*self.mandatory, *(f for g in self.one_of for f in g), *self.optional, *self.labels}


@dataclass(frozen=True, kw_only=True)
class KindSpec:
    """Person or company (er.kind): a name model, a combiner fitted on people's labels, and a line on each side."""
    name_field: str = "any_name"              # the field holding each record's name, a person's or a company's
    ngram: int = 3                            # the name model's character n-grams: 1 to this
    depth: int = 2                            # the combiner's trees (gradient boosting)
    company_wrong_at_most: float = 0.001      # the budget the company line is judged by (choose_kind): placed with no labelled error above it, then margin_steps stricter
    person_wrong_at_most: float = 0.01        # the person line: the labelled error above it within this, at 95% confidence
    margin_steps: int = 2                     # the company line: this many grid steps above the first clean one; one more on fewer than labels_to_draw answers
    labels_to_draw: int = 2000                # the review sheet's records drawn to measure the flag and the engine
    review_max: int = 1000                    # ... and at most this many it sends people to decide (the surest disagreements)
    name_line: float = 0.99                   # a name that says the other kind than the flag this surely is sent to decide
    grid: tuple[float, ...] = (0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.998, 0.999, 0.9995, 0.9999)
    trust_flag: bool = False                  # take the file's person/company flag as it is, instead of the model


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
    kind: KindSpec | None = None              # person or company, on every record; None: not told apart
    trust: TrustRule = TrustRule()            # what merges without people (er.run._accept)
    probe: Probe = Probe()                    # how the matches no key lists are measured (er.probe)
    household: Household = Household()        # which pairs people see labelled "maybe one household"
    keys: LearnKeys | None = None             # learn the keys on each file; None: [model] generators


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


def generator(name: str, d: dict, chains: Mapping[str, tuple[Normalizer, ...]]) -> Blocker:
    match d["kind"]:
        case "keys":
            return KeyBlocker(name=name, keys=tuple(_key(k, chains) for k in d["keys"]))
        case "sorted":
            return SortedNeighbourhood(name=name, key=_key(d["key"], chains), window=d["window"])
        case "tfidf":
            return TfidfNeighbours(name=name, key=_key(d["key"], chains), ngram=tuple(d["ngram"]), k=d["k"], min_cosine=d["min_cosine"])
        case "deletions":
            return DeletionKeys(name=name, key=_key(d["key"], chains), within=tuple(_key(k, chains) for k in d.get("within", ())))
        case "edits":
            return EditKeys(name=name, key=_key(d["key"], chains), within=tuple(_key(k, chains) for k in d.get("within", ())), edits=d.get("edits", 2))
    raise ValueError(f"generator {name}: unknown kind {d['kind']!r} (keys, sorted, tfidf, deletions, edits)")


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
    generators = {name: generator(name, d, chains) for name, d in cfg["generators"].items()}
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
                    u_near_by_keys=m.get("u_near_by_keys", False), fit_u_max_pairs=m.get("fit_u_max_pairs"), em_median=m.get("em_median", False), em_from_keys=m.get("em_from_keys", False))
    unknown = [c for c in m.get("needs", ()) if c not in {c.name for c in comparisons}]
    if unknown:
        raise ValueError(f"[model] needs: {unknown} are not comparisons in [[model.comparisons]]")
    fs = FSSpec(standardize=std, previous_stage=m["previous_stage"], stage=m["stage"], model=model,
                  blockers=tuple(generators[g] for g in m["generators"]), min_match_weight=m["min_match_weight"],
                  resolver=_resolver(m["resolver"]), budget=budget, bridge=m.get("bridge", False), needs=tuple(m.get("needs", ())))
    t, sel, d = cfg["threshold"], cfg["selection"], cfg["display"]
    return Pipeline(fields=Fields(mandatory=tuple(f["mandatory"]), one_of=tuple(map(tuple, f["one_of"])),
                                  optional=tuple(f["optional"]), labels=tuple(f["labels"]), identifying=tuple(f.get("identifying", ()))),
                    rules=rules, fs=fs, generators=generators,
                    threshold=ThresholdRule(grid=tuple(t["grid"]), max_fp=t["max_fp"], max_fp_rate_hi=t["max_fp_rate_hi"],
                                            margin_steps=t["margin_steps"]),
                    cv_folds=sel["cv_folds"], cv_seed=sel["cv_seed"], decision_p=sel["decision_p"],
                    explain_show=tuple(d["explain_show"]), explain_filled=tuple(d["explain_filled"]), fit_rows=m.get("fit_rows", 30_000),
                    kind=KindSpec(**{k: tuple(v) if k == "grid" else v for k, v in cfg["kind"].items()}) if "kind" in cfg else None,
                    trust=TrustRule(**{k: tuple(map(float, v)) if k == "steps" else v for k, v in cfg.get("trust", {}).items()}),
                    probe=Probe(strata=tuple((n, tuple(_key(k, chains) for k in keys)) for n, keys in cfg["probe"]["strata"].items()),
                                pairs=cfg["probe"].get("pairs", 1_000_000)) if "probe" in cfg else Probe(),
                    household=Household(shared=tuple(_key(k, chains) for k in cfg["household"]["shared"]),
                                        apart=tuple((d["field"], _comparator(d, chains)) for d in cfg["household"]["apart"])) if "household" in cfg else Household(),
                    keys=LearnKeys(**cfg["keys"]) if cfg.get("keys") else None)


def widen(p: "Pipeline", added: Iterable[tuple[str, str]]) -> "Pipeline":
    """The pipeline with a workspace's own fields beside the fields they stand with (added: pairs of (added field, the
    field it stands beside), e.g. ("person_name_2", "person_name")). Each comparison step that tests a field tests the
    added one the same way too, so a step is reached when either agrees, and the two are one piece of evidence, not two;
    a comparison is missing only when none of them is filled on both sides. Each generator keyed on a field gets a copy
    keyed on the added one, used when its original is. The added fields are declared optional, so a file without them
    turns off only what reads them. Rules are unchanged. Nothing added: the same pipeline, so the same config hash.
    O(steps + generators)."""
    beside: dict[str, list[str]] = {}
    for new, old in added:
        beside.setdefault(old, []).append(new)
    if not beside:
        return p
    level = lambda lv: replace(lv, any_of=lv.any_of + tuple((n, comp) for col, comp in lv.any_of for n in beside.get(col, ())))
    model = replace(p.fs.model, comparisons=tuple(
        replace(c, levels=tuple(level(lv) for lv in c.levels), null_if_missing=c.null_if_missing + tuple(n for col in c.null_if_missing for n in beside.get(col, ())))
        for c in p.fs.model.comparisons))

    def rekeyed(b: Blocker, old: str, new: str) -> Blocker:  # the generator, reading the added field where it read the old
        swap = lambda k: replace(k, column=new) if k.column == old else k
        changes: dict = {"name": f"{b.name}@{new}"}
        if isinstance(b, KeyBlocker):
            changes["keys"] = tuple(swap(k) for k in b.keys)
        else:
            changes["key"] = swap(b.key)
        if isinstance(b, DeletionKeys):
            changes["within"] = tuple(swap(k) for k in b.within)
        return replace(b, **changes)
    copies = {b.name: [rekeyed(b, old, new) for old, news in beside.items() if old in {k.column for k in keys_of(b)} for new in news]
              for b in p.generators.values()}
    return replace(p, fields=replace(p.fields, optional=p.fields.optional + tuple(n for news in beside.values() for n in news)),
                   generators={**p.generators, **{c.name: c for cs in copies.values() for c in cs}},
                   fs=replace(p.fs, model=model, blockers=p.fs.blockers + tuple(c for b in p.fs.blockers for c in copies.get(b.name, ()))))


METHOD_KEYS = ("line", "drop_rules", "drop_keys", "trust", "add_keys", "merge")


def added_key(fields: list[str]) -> KeyBlocker:  # a pair key a workspace adds (method.toml add_keys): each field as `field` or `field:normalizer`
    keys = tuple(Key(f, tuple(n)) for f, *n in (x.split(":") for x in fields))
    return KeyBlocker(name="added_" + "_".join(k.name for k in keys), keys=keys)


def adjust(p: "Pipeline", method: Mapping[str, object]) -> "Pipeline":
    """The pipeline with a workspace's changes to the tuned method (method.toml): `line`, the weight pairs are accepted
    at; `drop_rules`, match rules left out; `drop_keys`, pair keys left out, each with the copies widen made of it
    (name@field); `trust`, the trust line (TrustRule): "none" (nothing merges without people) or one of its steps;
    `merge`, the conditions that merge pairs without people (er.results.check_merging), read by runs and set merging;
    `add_keys`, pair keys added, each a list of fields (`field` or `field:normalizer`), as describe method proposes them.
    Nothing changed: the same pipeline, so the same config hash. O(rules + generators)."""
    if not method:
        return p
    fix = "correct method.toml in the workspace, or go back to the tuned method: nayose reset method --workspace …"
    if unknown := set(method) - set(METHOD_KEYS):
        raise InputError(f"method.toml: unknown keys {sorted(unknown)}; it takes {', '.join(METHOD_KEYS)}", fix)
    line = method.get("line", p.fs.min_match_weight)
    if isinstance(line, bool) or not isinstance(line, int | float) or not all(isinstance(method.get(k, []), list) for k in METHOD_KEYS[1:3]):
        raise InputError("method.toml: line is a weight in bits, drop_rules and drop_keys lists of names", fix)
    trust = method.get("trust")
    if trust is not None and trust != "none" and (isinstance(trust, bool) or not isinstance(trust, int | float) or float(trust) not in p.trust.steps):
        raise InputError(f'method.toml: trust is "none" or one of the steps {list(p.trust.steps)}', fix)
    rules, keys = set(method.get("drop_rules", ())), set(method.get("drop_keys", ()))
    if bad := (rules - {r.name for _, _, r in p.rules.each()}) | (keys - {b.name for b in p.fs.blockers}):
        raise InputError(f"method.toml: no rule or pair key named {sorted(bad)}", fix)
    stages = tuple(s for s in (replace(s, rules=tuple(r for r in s.rules if r.name not in rules)) for s in p.rules.stages) if s.rules)
    blockers = tuple(b for b in p.fs.blockers if b.name not in keys and b.name.split("@")[0] not in keys)
    added = method.get("add_keys", [])
    if not isinstance(added, list) or not all(isinstance(k, list) and k and all(isinstance(f, str) for f in k) for k in added):
        raise InputError("method.toml: add_keys is a list of pair keys, each a list of fields (field or field:normalizer)", fix)
    new = [added_key(k) for k in added]
    if bad := sorted({k.column for b in new for k in b.keys} - p.fields.declared()) + sorted({n for b in new for k in b.keys for n in k.normalize} - (set(get_args(Normalizer)) - {"one_byte", "one_byte_hash"})):  # the comparisons' own copies, no key's
        raise InputError(f"method.toml: add_keys names {bad}: not a field the pipeline declares, nor a normalizer", fix)
    blockers += tuple(b for b in new if b.name not in {x.name for x in blockers})
    if not stages or not blockers:
        raise InputError(f"method.toml leaves no {'match rule' if not stages else 'pair key'}", fix)
    return replace(p, rules=replace(p.rules, stages=stages), fs=replace(p.fs, blockers=blockers, min_match_weight=float(line)),
                   trust=p.trust if trust is None else replace(p.trust, line=math.inf if trust == "none" else float(trust)))


def load_pipeline(path: Path, std: Standardization, chains: Mapping[str, tuple[Normalizer, ...]],
                  columns: Mapping[str, object]) -> Pipeline:
    """config/pipeline.toml (or a written FINAL) → typed config. Every field it reads must be declared in [fields]
    and mapped in config/settings.toml [columns]."""
    p = pipeline_from(toml_of(path), std, chains)
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
    out |= {k.column for k in p.household.shared} | {col for col, _ in p.household.apart}
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

    def lacking(what: str, needs: set[str]) -> InputError:  # refused in words: which fields would let it run, and how to give one
        missing = sorted(needs - present)
        return InputError(f"{what}: each way reads a field this file lacks ({', '.join(missing)})",
                          fix=f"map one to a column: in Your data, or nayose set columns {missing[0]}=COLUMN --workspace …; or give the file one")
    stages = []
    for s in p.rules.stages:
        keep = []
        for r in s.rules:
            cols = (*r.exact, *r.fuzzy, *(k.column for k in r.blocking))
            (keep.append(r) if has(cols) else gone.append(f"rule {r.name} (needs {sorted(set(cols) - present)})"))
        if keep:
            stages.append(replace(s, rules=tuple(keep), comparators={c: x for c, x in s.comparators.items() if c in present}))
    if not stages:
        raise lacking("no match rule can run", {c for s in p.rules.stages for r in s.rules for c in (*r.exact, *r.fuzzy, *(k.column for k in r.blocking))})
    blockers = []
    for b in p.fs.blockers:
        cols = [k.column for k in keys_of(b)]
        (blockers.append(b) if has(cols) else gone.append(f"generator {b.name} (needs {sorted(set(cols) - present)})"))
    if not blockers:
        raise lacking("no way of finding pairs can run", {k.column for b in p.fs.blockers for k in keys_of(b)})
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
    if not prior:  # λ, how often two records match, is first measured on near-certain pairs
        raise lacking("the model can't start", {k.column for r in m.prior_rules for k in r})
    if m.m_method == "em" and not em:
        raise lacking("the model can't be fitted", {k.column for r in m.em_rules for k in r})
    gone += [f"prior rule {[k.column for k in r]}" for r in m.prior_rules if r not in prior]
    gone += [f"EM rule {[k.column for k in r]}" for r in m.em_rules if r not in em]
    model = replace(m, comparisons=tuple(comparisons), prior_rules=prior, em_rules=em)
    needs = tuple(n for n in p.fs.needs if n in {c.name for c in comparisons})  # [fields] one_of keeps a name comparison
    strata = tuple((n, keys) for n, keys in p.probe.strata if has(k.column for k in keys))
    gone += [f"probe {n} (needs {sorted({k.column for k in keys} - present)})" for n, keys in p.probe.strata if (n, keys) not in strata]
    h = p.household
    household = Household(shared=tuple(k for k in h.shared if k.column in present), apart=tuple((c, x) for c, x in h.apart if c in present))
    gone += [f"household label: {c}" for c in sorted({k.column for k in h.shared} | {c for c, _ in h.apart}) if c not in present]
    return replace(p, rules=replace(p.rules, stages=tuple(stages)), fs=replace(p.fs, blockers=tuple(blockers), model=model, needs=needs),
                   explain_show=tuple(f for f in p.explain_show if f in present),
                   explain_filled=tuple(f for f in p.explain_filled if f in present), probe=replace(p.probe, strata=strata),
                   household=household), gone


def generator_dict(b: Blocker, chains: Mapping[str, tuple[Normalizer, ...]] = {}) -> dict:
    """A generator as config/pipeline.toml writes it (the inverse of generator), normalizations as chain names where one matches."""
    name_of = {v: k for k, v in reversed(list(chains.items()))}  # the first chain defined wins
    norm = lambda n: name_of.get(tuple(n), list(n))
    key = lambda k: k.column if not k.normalize else {"field": k.column, "normalize": norm(k.normalize)}
    match b:
        case KeyBlocker():
            return {"kind": "keys", "keys": [key(k) for k in b.keys]}
        case SortedNeighbourhood():
            return {"kind": "sorted", "key": key(b.key), "window": b.window}
        case TfidfNeighbours():
            return {"kind": "tfidf", "key": key(b.key), "ngram": list(b.ngram), "k": b.k, "min_cosine": b.min_cosine}
        case DeletionKeys():
            return {"kind": "deletions", "key": key(b.key), **({"within": [key(k) for k in b.within]} if b.within else {})}
        case EditKeys():
            return {"kind": "edits", "key": key(b.key), **({"within": [key(k) for k in b.within]} if b.within else {}), "edits": b.edits}


def pipeline_dict(p: Pipeline, chains: Mapping[str, tuple[Normalizer, ...]]) -> dict:
    """The inverse of pipeline_from, with normalizations written as chain names where one matches."""
    name_of = {v: k for k, v in reversed(list(chains.items()))}  # the first chain defined wins
    norm = lambda n: name_of.get(tuple(n), list(n))
    key = lambda k: k.column if not k.normalize else {"field": k.column, "normalize": norm(k.normalize)}
    comp = lambda c: {"function": c.function, **({"threshold": c.threshold} if c.threshold is not None else {}),
                      **({"normalize": norm(c.normalize)} if c.normalize else {})}

    gen = lambda b: generator_dict(b, chains)

    resolver = lambda r: {"method": r.method, **({"cannot_link": list(r.cannot_link)} if r.cannot_link else {})}
    fs, m = p.fs, p.fs.model
    f, t = p.fields, p.threshold
    return {
        "fields": {"mandatory": list(f.mandatory), "one_of": [list(g) for g in f.one_of], "optional": list(f.optional), "labels": list(f.labels),
                   **({"identifying": list(f.identifying)} if f.identifying else {})},
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
                  **({"fit_u_max_pairs": m.fit_u_max_pairs} if m.fit_u_max_pairs else {}), **({"em_median": True} if m.em_median else {}),
                  **({"em_from_keys": True} if m.em_from_keys else {}), "fit_rows": p.fit_rows,
                  "comparisons": [{"name": c.name, "null_if_missing": list(c.null_if_missing), **({"tf": key(c.tf)} if c.tf else {}),
                                   "levels": [{"label": lv.label, "any_of": [{"field": col, **comp(x)} for col, x in lv.any_of],
                                               **({"tf": True} if lv.tf else {})} for lv in c.levels]} for c in m.comparisons]},
        **({"kind": {k: list(v) if k == "grid" else v for k, v in vars(p.kind).items()}} if p.kind else {}),
        "threshold": {"grid": list(t.grid), "max_fp": t.max_fp, "max_fp_rate_hi": t.max_fp_rate_hi, "margin_steps": t.margin_steps},
        "trust": {"steps": list(p.trust.steps), "checks": p.trust.checks, "watch": p.trust.watch},  # its line is the workspace's
        **({"probe": {"pairs": p.probe.pairs, "strata": {n: [key(k) for k in keys] for n, keys in p.probe.strata}}} if p.probe.strata else {}),
        **({"household": {"shared": [key(k) for k in p.household.shared], "apart": [{"field": col, **comp(x)} for col, x in p.household.apart]}}
           if p.household.shared or p.household.apart else {}),
        "selection": {"cv_folds": p.cv_folds, "cv_seed": p.cv_seed, "decision_p": p.decision_p},
        "display": {"explain_show": list(p.explain_show), "explain_filled": list(p.explain_filled)},
        **({"keys": vars(p.keys)} if p.keys else {}),
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

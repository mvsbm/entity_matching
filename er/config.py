"""Typed, frozen configuration, loaded from config/pipeline.toml (load_pipeline) and written back (dump_pipeline).
Everything is in field names (config/settings.toml [columns]); nothing here names a file's column."""
import math
import re
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Literal

from er.strings import FUNCTIONS, Function

COPIES = ("one_byte", "one_byte_hash")  # the steps of a comparison's own copy (Comparator.copied), never a key's nor a feature's: er.standardize makes them
Normalizer = Literal["nfkc", "strip_spaces", "kana_fold", "strip_legal_form", "address", "initial", "first3", "reverse", "casefold", "one_byte", "one_byte_hash",
                     "katakana", "strip_separators", "long_vowel", "last3"]


class InputError(ValueError):
    """Something in the input, or in how its columns are mapped, that people must fix; `fix` says how, and `hints`
    (field → column) what the file's values suggest. a job prints the two, not a traceback."""

    def __init__(self, message: str, fix: str = "", hints: dict[str, str] | None = None):
        super().__init__(message)
        self.fix, self.hints = fix, hints or {}


def q(name: str) -> str:  # a quoted SQL identifier
    return '"' + name.replace('"', '""') + '"'


def hashed(*exprs: str) -> str:
    """The portable hash of these SQL expressions, as every engine computes it: er_hash, the first 60 bits of the MD5
    of their text (a NULL as ''), several joined by a unit separator. A BIGINT from 0 to 2^60 − 1: DuckDB and BigQuery
    draw the same samples and order rows alike by it."""
    sep = lit(chr(31))
    return f"er_hash({exprs[0] if len(exprs) == 1 else f' || {sep} || '.join(f'coalesce(CAST({e} AS VARCHAR), {lit(chr(39) * 0)})' for e in exprs)})"


def unpivoted(src: str, columns: list[str], name: str, value: str) -> str:
    """SQL: the rows of `src` (a table, or a query in parentheses), one per column of `columns` that holds a value, as
    (name: the column's, value): the standard UNPIVOT, which DuckDB and BigQuery both read."""
    cols = ", ".join(q(c) for c in columns)
    return f"(SELECT {name}, {value} FROM (SELECT {cols} FROM {src}) UNPIVOT ({value} FOR {name} IN ({cols})))"


def lit(value: object) -> str:  # a value, a path or text, as an SQL string literal
    return "'" + str(value).replace("'", "''") + "'"


def bits(v: float) -> str:  # a weight in SQL; infinity above everything
    return f"'{'-' if v < 0 else ''}Infinity'::DOUBLE" if math.isinf(v) else repr(float(v))


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


def column_name(base: str, normalize: tuple[Normalizer, ...]) -> str:
    """The derived column holding normalized values, in plain identifier characters."""
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
        """Blocking-rule SQL (l."c" / r."c"), or with level=True comparison-level SQL ("c_l" / "c_r"). DuckDB's own
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
    max_pairs_per_record: float               # design time: a rule / generator's pairs, now and projected to
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


# ---------- candidates (probabilistic stage) ----------

@dataclass(frozen=True, kw_only=True)
class KeyBlocker:
    name: str
    keys: tuple[Key, ...]                     # all equal → candidate pair


@dataclass(frozen=True, kw_only=True)
class DeletionKeys:
    name: str
    key: Key                                  # the value and each one-character deletion of it are its keys
    within: tuple[Key, ...] = ()              # all equal too: limits chance pairs between short values


Blocker = KeyBlocker | DeletionKeys


def keys_of(b: Blocker) -> tuple[Key, ...]:  # every column a generator reads
    return b.keys if isinstance(b, KeyBlocker) else (b.key, *b.within)


# ---------- Fellegi–Sunter (probabilistic stage) ----------

@dataclass(frozen=True, kw_only=True)
class Level:
    label: str
    any_of: tuple[tuple[str, Comparator], ...]  # (column, comparator) conditions, OR'd


@dataclass(frozen=True, kw_only=True)
class Comparison:
    name: str
    levels: tuple[Level, ...]                 # most to least similar; an else level is added
    null_if_missing: tuple[str, ...]          # null level when none of these is filled on both sides


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

    def normalized(self) -> list[tuple[str, tuple[Normalizer, ...]]]:
        out = [(col, comp.normalize) for c in self.comparisons for lv in c.levels for col, comp in lv.any_of if comp.normalize]
        out += [(col, comp.copied()) for c in self.comparisons for lv in c.levels for col, comp in lv.any_of if comp.copied()]
        keys = [k for rule in (*self.prior_rules, *self.em_rules) for k in rule]
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
        cols |= {col for c in m.comparisons for col in c.null_if_missing}
        return cols | {k.name for rule in (*m.prior_rules, *m.em_rules) for k in rule}


# ---------- data, search ----------

@dataclass(frozen=True, kw_only=True)
class Data:
    bronze_dir: Path                          # <dataset>.parquet: records as they arrive, the input
    labels_dir: Path                          # <dataset>.parquet: truth, read only to evaluate (scripts/benchmark.py)
    datasets: tuple[str, ...]                 # the generated population's splits: train, val, test (scripts/generate.py)
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
    search_floor: float = 0.0  # bits: the oversized-block gate aims here (er.match.search_floor)
    keep_from: float = field(default=0.0, repr=False)  # bits: a pair the best case says can't reach it is never stored; in the run's hash only when set (run_config)


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


# ---------- config/pipeline.toml: load, check the fields a file holds, write back ----------

@dataclass(frozen=True, kw_only=True)
class Fields:
    mandatory: tuple[str, ...]                # the run stops if any is absent
    one_of: tuple[tuple[str, ...], ...]       # ... or if every field of one group is absent
    optional: tuple[str, ...]                 # absent: whatever reads it is disabled
    labels: tuple[str, ...]                   # read only by labelled runs (choosing, evaluation)
    identifying: tuple[str, ...] = ()         # one entity's each (a customer ID): a value on many records is a placeholder, read as missing (Run.load)

    def needed(self) -> set[str]:  # the fields a run may stop without: every mandatory one and each of a one_of group
        return {*self.mandatory, *(f for g in self.one_of for f in g)}

    def lacking(self, has: Callable[[str], bool]) -> list[str]:  # what a run stops without, as said: a mandatory field, or "a or b" for a group of none
        return [f for f in self.mandatory if not has(f)] + [" or ".join(g) for g in self.one_of if not any(map(has, g))]

    def declared(self) -> set[str]:
        return {*self.mandatory, *(f for g in self.one_of for f in g), *self.optional, *self.labels}


@dataclass(frozen=True, kw_only=True)
class KindSpec:
    """Person or company (er.kind): a written legal form, or a name model sure past name_line; else the file's flag."""
    name_field: str = "any_name"              # the field holding each record's name, a person's or a company's
    ngram: int = 3                            # the name model's character n-grams: 1 to this
    name_line: float = 0.99                   # the name model calls a kind it is at least this sure of
    trust_flag: bool = False                  # take the file's person/company flag as it is, instead of the model


def kind_spec(d: Mapping[str, object]) -> KindSpec:  # [kind], refused when it sets what no field holds
    if unknown := sorted(set(d) - {f.name for f in fields(KindSpec)}):
        raise InputError(f"[kind]: {', '.join(unknown)} set nothing: a record's kind is a written legal form, a name the model is "
                         "sure of (name_line), or else the file's flag", fix=f"delete {', '.join(unknown)} from [kind]")
    return KindSpec(**d)


@dataclass(frozen=True, kw_only=True)
class Pipeline:
    fields: Fields
    rules: RulesSpec
    fs: FSSpec
    generators: Mapping[str, Blocker]         # every generator defined, by name; fs.blockers uses some of them
    threshold: ThresholdRule
    fit_rows: int = 100_000                   # an unlabelled run fits on a sample of this many records (er.run)
    kind: KindSpec | None = None              # person or company, on every record; None: not told apart
    household: Household = Household()        # which pairs people see labelled "maybe one household"


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
        case "deletions":
            return DeletionKeys(name=name, key=_key(d["key"], chains), within=tuple(_key(k, chains) for k in d.get("within", ())))
    raise ValueError(f"generator {name}: unknown kind {d['kind']!r} (keys, deletions)")


def _resolver(d: dict) -> Resolver:
    return Resolver(method=d["method"], cannot_link=tuple(d.get("cannot_link", ())))


def pipeline_from(cfg: dict, std: Standardization, chains: Mapping[str, tuple[Normalizer, ...]]) -> Pipeline:
    """The parsed config/pipeline.toml → typed config."""
    if "trust" in cfg:  # nothing merges by a sampled line: the rules' pairs, the model's at its threshold and people's decisions
        raise InputError("[trust] sets nothing: a run merges nothing by itself; people set a match run's threshold and decide its pairs",
                         fix="delete [trust]")
    if "keys" in cfg:  # a run lists pairs by the generators the method names, chosen at design time
        raise InputError("[keys] sets nothing: a run lists pairs by the [model] generators as given", fix="delete [keys]")
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
    if tf := [c["name"] for c in m["comparisons"] if "tf" in c or any("tf" in lv for lv in c["levels"])]:
        raise InputError(f"[model] comparisons {', '.join(tf)}: tf sets nothing: a level weighs the same whichever value agrees",
                         fix="delete tf from those comparisons and their levels")
    comparisons = tuple(Comparison(
        name=c["name"], null_if_missing=tuple(c["null_if_missing"]),
        levels=tuple(Level(label=lv["label"],
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
    t = cfg["threshold"]
    return Pipeline(fields=Fields(mandatory=tuple(f["mandatory"]), one_of=tuple(map(tuple, f["one_of"])),
                                  optional=tuple(f["optional"]), labels=tuple(f["labels"]), identifying=tuple(f.get("identifying", ()))),
                    rules=rules, fs=fs, generators=generators,
                    threshold=ThresholdRule(grid=tuple(t["grid"]), max_fp=t["max_fp"], max_fp_rate_hi=t["max_fp_rate_hi"],
                                            margin_steps=t["margin_steps"], search_floor=float(t.get("search_floor", 0.0)),
                                            keep_from=float(t.get("keep_from", 0.0))),
                    fit_rows=m.get("fit_rows", 100_000),
                    kind=kind_spec(cfg["kind"]) if "kind" in cfg else None,
                    household=Household(shared=tuple(_key(k, chains) for k in cfg["household"]["shared"]),
                                        apart=tuple((d["field"], _comparator(d, chains)) for d in cfg["household"]["apart"])) if "household" in cfg else Household())


GIVEN, PERSON = "given_name", "person_name"  # agreement on the given name tells one person's records from a household's; the full name, where it is sparse (er.match.judged)


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
    out |= {k.column for b in p.generators.values() for k in keys_of(b)}
    out |= {col for c in m.comparisons for lv in c.levels for col, _ in lv.any_of} | {col for c in m.comparisons for col in c.null_if_missing}
    out |= {k.column for rule in (*m.prior_rules, *m.em_rules) for k in rule}
    out |= {c for s in r.stages for c in s.comparators}
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
                          fix=f"map one to a column in config/settings.toml [columns] ({missing[0]} = \"COLUMN\"), or give the file one")
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
            comparisons.append(replace(c, levels=tuple(levels), null_if_missing=null))
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
    h = p.household
    household = Household(shared=tuple(k for k in h.shared if k.column in present), apart=tuple((c, x) for c, x in h.apart if c in present))
    gone += [f"household label: {c}" for c in sorted({k.column for k in h.shared} | {c for c, _ in h.apart}) if c not in present]
    return replace(p, rules=replace(p.rules, stages=tuple(stages)), fs=replace(p.fs, blockers=tuple(blockers), model=model, needs=needs),
                   household=household), gone

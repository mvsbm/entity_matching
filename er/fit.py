"""How the model learns, before it scores anything: Fellegi–Sunter fitted as Splink 5.0 fits it.

The model needs three kinds of numbers:
- λ: how likely two random records are the same customer. `prior` counts the pairs that near-certain rules find.
- u: how often two *different* customers land in each level. Given to this module (er.match counts and samples it).
- m: how often the *same* customer lands in each level. Learned here, by EM sessions on the pairs that share a key
  (`session`).

An EM session takes the pairs that share one key (a phone, say). Each round it guesses, for every pattern of levels
the pairs show, how likely such a pair is a match (the E-step), then counts m from those guesses (the M-step). It
stops when nothing moves by 1e-4, or after 25 rounds. A comparison the key chose the pairs by (the phone, when the
key is the phone) can't be learned from them, so it is left out of that session ("fixed").

`Trained` keeps what the sessions learned. Each level's m is the median of its sessions' m. A session starts from it,
or, before any, from Splink's guess: 0.95 for a comparison's first level, the rest shared by the others.

tests/test_fit.py checks every number here against Splink 5.0's. One difference by design: the sums run over the
patterns in a fixed order, so a fit repeats to the last bit (Splink's run in the order DuckDB's threads leave the rows).
"""
import copy
import math
import re
import statistics
from dataclasses import dataclass


from er.engine.engine import Engine
from er.config import InputError, q

START_M = 0.95           # Splink's first guess of m for a comparison's first level
UNSEEN_M = 1e-6          # the m Splink weighs a level with when no pair of the session reached it
MAX_ROUNDS = 25          # Splink's max_iterations
CONVERGED = 1e-4         # Splink's em_convergence: stop once no m and no λ moves by more
Level = tuple[str, str]  # (comparison, level label)
Gamma = tuple[str, int]  # (comparison, the level's gamma)


def prior(engine: Engine, records: str, rules: list[str], uid: str, recall: float) -> float:
    """λ: the pairs any of these rules find (SQL over l and r), counted once each, divided by the share of all
    matches they are thought to find (recall), over every pair of the records. O(n + P) per rule."""
    u = q(uid)
    n = engine.value(f"SELECT count(*) FROM {records}")
    every = int(n * (n - 1) / 2)
    found = 0
    for i, rule in enumerate(rules):  # each rule's pairs that no earlier rule found
        earlier = " OR ".join(f"coalesce(({r}), false)" for r in rules[:i])
        new = f" AND NOT ({earlier})" if earlier else ""
        found += engine.value(f"SELECT count(*) FROM {records} l JOIN {records} r ON ({rule}) AND l.{u} < r.{u}{new}")
    if found > every * recall:
        raise InputError(f"the near-certain rules find {found:,} of the {every:,} pairs, more than a recall of {recall} allows "
                         f"(at least {found / every:,.2f})", fix="raise [model] prior_recall, or make the prior rules stricter")
    return found / recall / every


def numbered(comparisons: list[dict]) -> list[tuple[dict, list[tuple[int, dict]]]]:
    """Each comparison with its levels and their gammas, as scoring numbers them: the missing level -1, then the first
    level highest, down to the else level's 0."""
    out = []
    for c in comparisons:
        top = sum(not lv.get("is_null_level") for lv in c["comparison_levels"])
        ladder = []
        for lv in c["comparison_levels"]:
            if lv.get("is_null_level"):
                ladder.append((-1, lv))
            else:
                top -= 1
                ladder.append((top, lv))
        out.append((c, ladder))
    return out


def columns(c: dict) -> set[str]:  # the record columns a comparison's levels read ("x" of "x_l" and "x_r")
    return {col for lv in c["comparison_levels"] for col in re.findall(r'"([^"]+)_[lr]"', lv["sql_condition"])}


def exact_column(sql: str) -> str | None:  # "x" where a level is plain equality, ("x_l" = "x_r"), as Splink tells it
    found = re.fullmatch(r'\(\s*"([^"]+)_l"\s*=\s*"\1_r"\s*\)', sql.strip())
    return found.group(1) if found else None


class Trained:
    """Each level's m as the sessions so far have left it: the median of what each learned for it, or Splink's first
    guess before any has. One per fit."""

    def __init__(self):
        self.learned: dict[Level, list[float]] = {}

    def add(self, m: dict[Level, float]) -> None:
        for key, value in m.items():
            self.learned.setdefault(key, []).append(value)

    def m(self, c: dict, gamma: int, label: str) -> float:  # the m a session starts from
        got = self.learned.get((c["output_column_name"], label))
        if got:
            return statistics.median(got)
        n = sum(not lv.get("is_null_level") for lv in c["comparison_levels"])
        return START_M if gamma == n - 1 else (1 - START_M) / (n - 1)

    def medians(self) -> dict[Level, float]:  # each level's m, where a session learned one
        return {key: statistics.median(values) for key, values in self.learned.items()}


@dataclass
class Session:
    fixed: set[str]          # the comparisons the key chose the pairs by: not learned here
    start: float             # λ among the key's pairs, where EM starts
    m: dict[Level, float]    # each learned level's m after the last round; a level no pair reached is left out
    rounds: int


def _points(m: float, u: float) -> float:  # a level's points, as Splink writes them: log2(m / u), each at least 1e-300
    return math.log2(max(m, 1e-300) / max(u, 1e-300))


def _probability(points: float) -> float:  # points → the chance of a match, written so that 2^points never overflows
    return 1.0 / (1.0 + 2.0 ** -points) if points >= 0 else 2.0 ** points / (1.0 + 2.0 ** points)


def _odds(p: float) -> float:
    return p / (1 - p) if p != 1 else math.inf


def _patterns(engine: Engine, records: str, pairs_on: str, uid: str, comparisons: list[dict]) -> list[tuple]:
    """Each pattern of gammas the pairs show (pairs_on: SQL over l and r; each pair once), with its count, in order."""
    u = q(uid)
    cols = sorted(set().union(*(columns(c) for c in comparisons)))
    sides = ", ".join(f"l.{q(x)} AS {q(x + '_l')}, r.{q(x)} AS {q(x + '_r')}" for x in cols)
    gammas = [f"CASE {' '.join(f'ELSE {g}' if lv['sql_condition'].strip().upper() == 'ELSE' else f'WHEN {lv['sql_condition']} THEN {g}' for g, lv in ladder)} END"
              for _, ladder in numbered(comparisons)]
    return engine.rows(f"""SELECT {', '.join(gammas)}, count(*) FROM (SELECT {sides} FROM {records} l JOIN {records} r
        ON ({pairs_on}) AND l.{u} < r.{u}) GROUP BY ALL ORDER BY ALL""")


def session(engine: Engine, records: str, settings: dict, pairs_on: str, keyed: set[str], uid: str,
            lam: float, trained: Trained) -> Session:
    """One EM session on the pairs that share a key (pairs_on: SQL over l and r; keyed: the record columns it names).
    settings: the model's comparisons, each level with its u. O(P·K) for the patterns of P pairs and K comparisons,
    then O(rounds · patterns · K)."""
    fixed = {c["output_column_name"] for c in settings["comparisons"] if columns(c) & keyed}
    ladders = numbered([c for c in settings["comparisons"] if c["output_column_name"] not in fixed])

    # λ among the key's pairs: λ with the evidence of the exact levels the key guarantees, each column once
    odds, left = _odds(lam), set(keyed)
    for c, ladder in numbered(settings["comparisons"]):
        for g, lv in ladder:
            col = exact_column(lv["sql_condition"])
            if col and col in left:
                left.discard(col)
                u = lv["u_probability"]
                odds = (trained.m(c, g, lv["label_for_charts"]) / u if u != 0 else math.inf) * odds
    start = odds / (1 + odds)
    if not ladders:
        return Session(fixed=fixed, start=start, m={}, rounds=0)

    patterns = _patterns(engine, records, pairs_on, uid, [c for c, _ in ladders])
    if not patterns:
        raise InputError(f"no two records share {pairs_on}, the pairs an EM session learns from", fix="map those fields to filled columns")
    names = [c["output_column_name"] for c, _ in ladders]
    label = {(c["output_column_name"], g): lv["label_for_charts"] for c, ladder in ladders for g, lv in ladder}
    u = {(c["output_column_name"], g): lv["u_probability"] for c, ladder in ladders for g, lv in ladder if g >= 0}
    m: dict[Gamma, float | None] = {key: trained.m(c, key[1], label[key]) for c, ladder in ladders for key in ((c["output_column_name"], g) for g, _ in ladder) if key[1] >= 0}
    lam_s, rounds = start, 0
    for rounds in range(1, MAX_ROUNDS + 1):
        # E-step: each pattern's chance of being a match, from λ and its levels' points, added left to right
        points_at = {key: _points(UNSEEN_M if m[key] is None else m[key], u[key]) for key in m} | {(n, -1): 0.0 for n in names}
        prior_points = math.log2(_odds(lam_s))
        expected: dict[Gamma, float] = {}  # the expected matches at each level
        matches, pairs = 0.0, 0
        for *gammas, count in patterns:
            points = prior_points
            for name, g in zip(names, gammas):
                points = points + points_at[name, g]
            p = _probability(points)
            matches += p * count
            pairs += count
            for name, g in zip(names, gammas):
                expected[name, g] = expected.get((name, g), 0.0) + p * count
        # M-step: each level's m, its share of the expected matches where the comparison is filled; λ, their share
        new: dict[Gamma, float | None] = {}
        for name in names:
            filled = 0.0
            for key in sorted(k for k in expected if k[0] == name and k[1] >= 0):
                filled += expected[key]
            for key in (k for k in m if k[0] == name):
                share = expected[key] / filled if key in expected and filled else math.nan
                new[key] = share if share >= 1e-300 else None  # no pair reached it, or its share is nothing (NaN too)
        new_lam = matches / pairs
        moved = [abs((UNSEEN_M if new[k] is None else new[k]) - (UNSEEN_M if m[k] is None else m[k])) for k in m] + [abs(new_lam - lam_s)]
        m, lam_s = new, new_lam
        if max((x for x in moved if not math.isnan(x)), default=0.0) < CONVERGED:
            break
    return Session(fixed=fixed, start=start, m={(key[0], label[key]): v for key, v in m.items() if v is not None}, rounds=rounds)


def fitted(settings: dict, lam: float, m: dict[Level, float]) -> dict:
    """The fitted model: settings (each level with its u) with λ and each level's m; a level no session learned has
    no m (er.match.train_fs fills it)."""
    out = copy.deepcopy(settings)
    out["probability_two_random_records_match"] = lam
    for c in out["comparisons"]:
        for lv in c["comparison_levels"]:
            if not lv.get("is_null_level") and (c["output_column_name"], lv["label_for_charts"]) in m:
                lv["m_probability"] = m[c["output_column_name"], lv["label_for_charts"]]
    return out

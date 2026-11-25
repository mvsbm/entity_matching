"""Stage 2, fit: learn the Fellegi–Sunter model from the counts fit.sql leaves, to the same numbers Splink 5.0 gives.

The model has three sorts of number:

    λ   how likely two random records are one entity: the pairs the near-certain rules find (the prior), divided by
        the share of all matches those rules find (prior_recall), divided by every pair of the sample.
    u   how often two different entities fall into a level by chance: counted exactly where fit.sql counts it, else
        measured on sampled pairs, else, when no sampled pair reached the level, an upper bound.
    m   how often one entity's two records fall into a level: learned by EM sessions on the sample's pairs that
        share a field, each session starting from what the sessions before it learned. A level's m is the median.

After learning, u is measured again on the file to be scored: in a bigger file, a field whose values grow with it
agrees by chance less often. An update scores with the model as the build left it, as a saved model is reused;
building again measures u on the run as it has grown.

fit() is a pure function, JSON in and JSON out, using the standard library only. fit.sql calls it as fit_model, on
BigQuery as a Python UDF (engines.functions) and on DuckDB alike. Cost:
O(iterations · patterns · K) for K comparisons.
"""
import copy
import json
import math
import statistics

START_M = 0.95  # Splink's first guess of m for a comparison's first level
UNSEEN_M = 1e-6  # the m Splink gives a level that no pair of the session reached
MAX_ITERATIONS = 25  # Splink's max_iterations
CONVERGED = 1e-4  # Splink's em_convergence: stop once no m and no λ moves by more than this
ELSE = "else"  # the label of each comparison's last level: none of the others
LAMBDA_CAP = 1 - 1e-9  # the most the rescaled λ can be, a hair under 1, so that its log-odds stay finite (score.sql's)
PRIOR_RULES = {  # fit_prior's columns, named as the report names the rules
    "cif_name": "customer_id + full_name",
    "cif_company": "customer_id + company_name",
    "name_code_phone": "full_name + address_code + phone",
}


def fit(counts: str, settings: str, given_fit: str | None = None) -> str:
    """Fit the model and return it as JSON.

    `counts` holds fit.sql's tables, each a list of rows; `settings` is config.toml's [fit]. Without `given_fit` (a
    build), the model is learned on the sample (learn) and its u measured on the file (assemble). With `given_fit`,
    what fit returned for another file (as scripts/benchmark.py fits one on a train split), that model is used and its
    u measured on this file whole.

    The result holds each level with m and u as fitted and as measured on the file (file_m, file_u, and bits: what a
    score adds), λ and its bits at the file's size (prior_bits), the sample's size, the notes the report reads, and the
    model as fitted.
    """
    tables, config = json.loads(counts), json.loads(settings)
    # by comparison, then the strongest level first
    levels = sorted(tables["levels"], key=lambda lv: (lv["position"], -lv["gamma"]))
    measures = measured(tables, config)
    model = (json.loads(given_fit)["model"] if given_fit is not None
             else learn(levels, measures["sample"], tables["prior"][0], tables["patterns"] or [], config))
    file = measures["file"]
    exact = exact_u(levels, file)
    sampled = sampled_u(levels, file, [x for x in comparisons(levels) if ELSE not in exact.get(x, {})])
    return fitted(model, assemble(model, file, sampled), file["n"])


def fitted(model: dict, scoring: dict, n: int) -> str:
    """Return what fit gives back, as JSON: the model as scored on a file of `n` records."""
    # λ is a per-pair rate, so it is rescaled to the file's size (score.sql's level_bits rescales it the same way)
    lam = min(model["probability"] * (model["fit_records"] - 1) / max(n - 1, 1), LAMBDA_CAP)
    levels = [dict(lv, file_m=f["m"], file_u=f["u"], bits=bits(f["m"], f["u"]))
              for lv, f in zip(model["levels"], scoring["levels"])]
    notes = dict(model["notes"], file_adjusted=scoring["notes"]["adjusted"])
    return json.dumps(dict(levels=levels, probability=model["probability"], fit_records=model["fit_records"], records=n,
                           prior_bits=math.log2(lam / (1 - lam)), notes=notes, model=model))


def bits(m: float, u: float) -> float:
    """Return a level's weight as Splink writes it: log2(m/u), each clamped at 1e-300."""
    return math.log2(max(m, 1e-300) / max(u, 1e-300))


# ---------- u: the counts made into shares ----------

def measured(tables: dict, config: dict) -> dict[str, dict]:
    """Return fit.sql's u counts by scope (sample, file), with each scope's max_pairs: what its sample drew from."""
    out = {}
    for scope, most in (("sample", float(config["fit_u_max_pairs"])), ("file", float(config["u_max_pairs"]))):
        def rows_of(table: str) -> list[dict]:
            return [r for r in tables.get(table) or [] if r["scope"] == scope]
        filled = next(iter(rows_of("filled")), {"records": 0})
        out[scope] = dict(n=filled["records"], max_pairs=most, filled=filled, plan=next(iter(rows_of("plan")), {}),
                          outside={r["comparison"]: r["pairs"] for r in rows_of("outside")},
                          counted={(r["comparison"], r["label"]): r["pairs"] for r in rows_of("counted")},
                          one_edit={(r["comparison"], r["label"]): r["pairs"] for r in rows_of("one_edit")},
                          sampled={(r["comparison"], r["gamma"]): r["pairs"] for r in rows_of("sampled")})
    return out


def exact_u(levels: list[dict], counts: dict) -> dict[str, dict[str, float]]:
    """Return the u of each comparison's levels that fit.sql counted exactly.

    Each u is a share of the pairs outside the comparison's missing level. When every level is counted, the else
    level's u is the rest. A comparison with no level counted is left out.
    """
    out: dict[str, dict[str, float]] = {}
    for name in comparisons(levels):
        counted_levels = [lv for lv in levels if lv["comparison"] == name and lv["agreement"] != ELSE]
        if u_of := counted_u(name, counted_levels, counts):
            out[name] = u_of
    return out


def counted_u(name: str, counted_levels: list[dict], counts: dict) -> dict[str, float]:
    """Return the u of `counted_levels`, one comparison's levels but its else level, that fit.sql counted, in order.

    A level counted with no pair has no u. When some level has a u and every one does, the else level's u is the rest.
    """
    outside = float(counts["outside"][name])
    u_of: dict[str, float] = {}
    for lv in counted_levels:
        pairs = counts["counted"].get((name, lv["label"]), counts["one_edit"].get((name, lv["label"])))
        if pairs is None:
            break  # a level not counted: neither is any after it
        u = float(pairs) / outside if outside else 0.0
        if u > 0:
            u_of[lv["label"]] = u
    if not u_of or any(lv["label"] not in u_of for lv in counted_levels):
        return u_of  # no rest unless some level has a u, and every one does: the else level is sampled
    counted = 0.0
    for u in u_of.values():  # added in turn: Python 3.12+'s sum() rounds otherwise, and BigQuery runs 3.11
        counted += u
    rest = 1 - counted
    if rest > 0:
        u_of[ELSE] = rest  # every level counted: nothing is left to sample
    return u_of


def sampled_u(levels: list[dict], counts: dict, names: list[str]) -> dict[str, dict[str, float]]:
    """Return the u of these comparisons' levels in the sampled pairs.

    A level's u is its pairs over the pairs with the comparison filled. A level no pair reached has none.
    """
    out = {}
    for name in names:
        its_levels = [lv for lv in levels if lv["comparison"] == name]
        if counts["plan"].get(name) is False:
            raise RuntimeError(f"fit.sql counted {name} to its else level and sampled none of its pairs, "
                               "where nayose.em samples it")
        sampled = counts["sampled"]
        filled = sum(sampled.get((name, lv["gamma"]), 0) for lv in its_levels)
        out[name] = {lv["label"]: sampled[name, lv["gamma"]] / filled
                     for lv in its_levels if sampled.get((name, lv["gamma"]))}
    return out


def u_bound(counts: dict, name: str) -> float:
    """Return a 95% upper bound on u for a level no sampled pair reached.

    The bound counts zero hits among the sampled pairs where the comparison is filled, of which there are at least the
    sample times its fill share squared.
    """
    n = counts["n"]
    filled_pairs = min(counts["max_pairs"], n * (n - 1) / 2) * (counts["filled"][name] / n if n else 0.0) ** 2
    return 1 - 0.05 ** (1 / max(1, int(filled_pairs)))


def comparisons(levels: list[dict]) -> list[str]:
    """Return the comparisons, in the model's order."""
    return list(dict.fromkeys(lv["comparison"] for lv in levels))


# ---------- the model learned on the sample ----------

def learn(levels: list[dict], counts: dict, prior_counts: dict, patterns: list[dict], settings: dict) -> dict:
    """Learn the model on the sample: u, then λ, then m by the EM sessions in order.

    Raises ValueError when no near-certain rule, or no session's field, finds a pair in the sample, or the rules find
    more pairs than their recall allows.
    """
    names = comparisons(levels)
    model, filled_u = sample_u(levels, counts, names)
    records, prior_pairs = prior_counts["records"], prior_counts["prior_pairs"]
    rules_found = [rule for rule in PRIOR_RULES if prior_counts[rule]]
    sessions = [s["field"] for s in settings["em_sessions"]]
    patterns_of = {s: [tuple(p[n] for n in names) + (p["pairs"],) for p in patterns if p["session"] == s]
                   for s in sessions}
    em_pairs = {s: sum(p[-1] for p in patterns_of[s]) for s in sessions if patterns_of[s]}
    lam = prior_rate(records, prior_pairs, rules_found, sessions, em_pairs, settings["prior_recall"])
    with_pairs = [s for s in settings["em_sessions"] if s["field"] in em_pairs]
    learned, filled_m = learn_m(model, with_pairs, patterns_of, names, lam)
    adjusted = sensible_m(model, {tuple(x) for x in filled_m})
    skipped = [PRIOR_RULES[r] for r in PRIOR_RULES if r not in rules_found] + [s for s in sessions if s not in em_pairs]
    by_session = {s: [[name, label, m] for (name, label), m in m_of.items()] for s, m_of in learned.items()}
    return dict(model, probability=lam, fit_records=records,
                notes=dict(fit_records=records, filled=dict(u=filled_u, m=filled_m), skipped=skipped, adjusted=adjusted,
                           em_pairs=em_pairs, em_sessions=by_session))


def sample_u(levels: list[dict], counts: dict, names: list[str]) -> tuple[dict, list[list[str]]]:
    """Return the model before EM, each level's u on the sample and its m unknown, and the levels whose u is a bound."""
    exact = exact_u(levels, counts)
    skip = {name for name, u in exact.items() if ELSE in u}
    u = {**{name: {} for name in skip}, **sampled_u(levels, counts, [x for x in names if x not in skip])}
    u = {name: {**u_of, **exact.get(name, {})} for name, u_of in u.items()}
    filled_u = [[lv["comparison"], lv["label"]] for lv in levels if lv["label"] not in u[lv["comparison"]]]
    model = dict(levels=[dict(lv, u=u[lv["comparison"]].get(lv["label"]) or u_bound(counts, lv["comparison"]), m=None)
                         for lv in levels])
    return model, filled_u


def prior_rate(records: int, prior_pairs: int, rules_found: list[str], sessions: list[str], em_pairs: dict,
               recall: float) -> float:
    """Return λ: the pairs the near-certain rules find, over their recall, over every pair of the sample.

    Raises ValueError when no near-certain rule, or no session's field, finds a pair in the sample, or the rules find
    more pairs than their recall allows.
    """
    if not rules_found:
        raise ValueError(f"no two records of the {records:,} the fit samples agree on any near-certain rule "
                         f"({'; '.join(PRIOR_RULES.values())}), so the chance that two records match can't be "
                         "estimated: map the fields those rules read")
    if not em_pairs:
        raise ValueError(f"no two records of the {records:,} the fit samples share {' or '.join(sessions)}, "
                         "the pairs it learns from: map those fields to filled columns")
    all_pairs = int(records * (records - 1) / 2)
    if prior_pairs > all_pairs * recall:
        raise ValueError(f"the near-certain rules find {prior_pairs:,} of the {all_pairs:,} pairs, more than a recall "
                         f"of {recall} allows (at least {prior_pairs / all_pairs:,.2f}): "
                         "raise [fit] prior_recall, or make the prior rules stricter")
    return prior_pairs / recall / all_pairs


def learn_m(model: dict, with_pairs: list[dict], patterns_of: dict[str, list[tuple]], names: list[str],
            lam: float) -> tuple[dict, list[list[str]]]:
    """Learn each level's m by the EM sessions `with_pairs`, in order: the median of what they learned, else its u.

    Returns what each session learned, and the levels whose m is their u.
    """
    trained: dict[tuple[str, str], list[float]] = {}  # each level's m, as each session so far learned it
    learned = {}
    for s in with_pairs:
        learned[s["field"]] = session(model, patterns_of[s["field"]], names, s, lam, trained)
        for key, value in learned[s["field"]].items():
            trained.setdefault(key, []).append(value)
    filled_m = []
    for lv in model["levels"]:
        if (lv["comparison"], lv["label"]) in trained:
            lv["m"] = statistics.median(trained[lv["comparison"], lv["label"]])
        else:
            lv["m"] = lv["u"]
            filled_m.append([lv["comparison"], lv["label"]])
    return learned, filled_m


def first_m(model: dict, name: str, gamma: int, trained: dict) -> float:
    """Return the m a session starts a level from: the median of what earlier sessions learned, else Splink's guess."""
    lv = next(x for x in model["levels"] if x["comparison"] == name and x["gamma"] == gamma)
    if earlier := trained.get((name, lv["label"])):
        return statistics.median(earlier)
    n = sum(1 for x in model["levels"] if x["comparison"] == name)
    return START_M if gamma == n - 1 else (1 - START_M) / (n - 1)


def probability(p: float) -> float:
    """Return the chance of a match for `p` points, written so that 2^p never overflows."""
    return 1.0 / (1.0 + 2.0 ** -p) if p >= 0 else 2.0 ** p / (1.0 + 2.0 ** p)


def odds(p: float) -> float:
    """Return the odds of a chance `p`."""
    return p / (1 - p) if p != 1 else math.inf


def session(model: dict, patterns: list[tuple], names: list[str], s: dict, lam: float,
            trained: dict) -> dict[tuple[str, str], float]:
    """Run one EM session on the pairs that share its field, and return each level's m after its last iteration.

    `patterns` holds each pattern of levels with its count, in order; a comparison the field fixed is None. λ among
    these pairs starts from λ with the evidence of the exact levels the field guarantees. Each iteration guesses each
    pattern's chance of a match from λ's bits and its levels' bits, added left to right (E), then counts m from those
    guesses (M). The session stops once nothing moves by CONVERGED, or after MAX_ITERATIONS. A level no pair reached is
    left out of the result.
    """
    learns = [i for i, name in enumerate(names) if all(p[i] is not None for p in patterns)]  # its field fixed the rest
    order = [names[i] for i in learns]
    start = odds(lam)
    for name, label in s["start"]:
        lv = next(x for x in model["levels"] if x["comparison"] == name and x["label"] == label)
        evidence = first_m(model, name, lv["gamma"], trained) / lv["u"] if lv["u"] != 0 else math.inf
        start = evidence * start
    lam_s = start / (1 + start)
    u = {(lv["comparison"], lv["gamma"]): lv["u"] for lv in model["levels"] if lv["comparison"] in order}
    label_of = {(lv["comparison"], lv["gamma"]): lv["label"] for lv in model["levels"]}
    m: dict[tuple[str, int], float | None] = {key: first_m(model, key[0], key[1], trained) for key in u}
    # in order, as SQL's ORDER BY ALL sorts them
    rows = [(list(x[:-1]), x[-1]) for x in sorted(tuple(p[i] for i in learns) + (p[-1],) for p in patterns)]
    for _ in range(MAX_ITERATIONS):
        bits_at_level = {key: bits(seen(m[key]), u[key]) for key in m}
        bits_at_level |= {(n, -1): 0.0 for n in order}  # a missing comparison weighs nothing
        matches, pairs, expected = expect(rows, order, bits_at_level, math.log2(odds(lam_s)))
        new, new_lam = maximise(expected, m, order), matches / pairs
        moved = [abs(seen(new[k]) - seen(m[k])) for k in m] + [abs(new_lam - lam_s)]
        m, lam_s = new, new_lam
        if max((x for x in moved if not math.isnan(x)), default=0.0) < CONVERGED:
            break
    return {(key[0], label_of[key]): v for key, v in m.items() if v is not None}


def seen(m: float | None) -> float:
    """Return a level's m, or UNSEEN_M where no pair of the session reached it (None)."""
    return UNSEEN_M if m is None else m


def expect(rows: list[tuple], order: list[str], bits_at_level: dict, prior_bits: float) -> tuple[float, int, dict]:
    """E: guess each pattern's chance of a match from its points, λ's bits and its levels' bits added left to right.

    Returns the matches expected among the pairs, the pairs, and the matches expected at each level.
    """
    expected: dict[tuple[str, int], float] = {}
    matches, pairs = 0.0, 0
    for gammas, count in rows:  # loops, not sum(): Python 3.12+'s sum() rounds otherwise, and BigQuery runs 3.11
        total = prior_bits
        for name, gamma in zip(order, gammas):
            total = total + bits_at_level[name, gamma]
        p = probability(total)
        matches += p * count
        pairs += count
        for name, gamma in zip(order, gammas):
            expected[name, gamma] = expected.get((name, gamma), 0.0) + p * count
    return matches, pairs, expected


def maximise(expected: dict, m: dict, order: list[str]) -> dict[tuple[str, int], float | None]:
    """M: count each level's m from E's guesses (share); None where no pair reached it."""
    new: dict[tuple[str, int], float | None] = {}
    for name in order:
        filled = 0.0
        for key in sorted(k for k in expected if k[0] == name and k[1] >= 0):  # a loop, not sum(), as in expect
            filled += expected[key]
        for key in (k for k in m if k[0] == name):
            new[key] = share(expected, key, filled)
    return new


def share(expected: dict, key: tuple[str, int], filled: float) -> float | None:
    """Return a level's m: its expected matches over its comparison's `filled`; None where no pair reached it."""
    m = expected[key] / filled if key in expected and filled else math.nan
    return m if m >= 1e-300 else None  # no pair reached it, or its share is nothing (NaN too)


def sensible_m(model: dict, filled: set[tuple[str, str]]) -> list[list]:
    """Hold EM's m to two limits, each where the sample gave EM nothing to go by, and return what changed.

    - A fuzzy level stands for a typo in a value that matches share. Where no match agreed exactly in training (each
      exact level's m was filled as its u), a fuzzy agreement only means neighbouring values, such as IDs handed out
      in sequence: no evidence, so m = u and the level weighs 0 bits.
    - Partial agreement is never more evidence against a match than none: a level weighs at least its else level.
    """
    out = []
    for name in comparisons(model["levels"]):
        its_levels = [lv for lv in model["levels"] if lv["comparison"] == name]
        out += fuzzy_without_exact(name, its_levels, filled)
        out += at_least_else(name, its_levels)
    return out


def fuzzy_without_exact(name: str, its_levels: list[dict], filled: set[tuple[str, str]]) -> list[list]:
    """Give a comparison's fuzzy levels m = u where each of its exact levels' m was filled as u; return what changed."""
    exact = [lv for lv in its_levels if lv["agreement"] == "exact"]
    if not exact or not all((name, lv["label"]) in filled for lv in exact):
        return []
    out = []
    for lv in its_levels:
        if lv["agreement"] == "fuzzy" and lv["m"] != lv["u"]:
            was = round(math.log2(lv["m"] / lv["u"]), 2)
            out.append([name, lv["label"], "no exact agreement among matches: 0 bits", was])
            lv["m"] = lv["u"]
    return out


def at_least_else(name: str, its_levels: list[dict]) -> list[list]:
    """Raise each level of a comparison that weighs less than its else level to that weight; return what changed."""
    other = next((lv for lv in its_levels if lv["agreement"] == ELSE), None)
    if other is None:
        return []
    out = []
    floor = other["m"] / other["u"]
    for lv in its_levels:
        if lv is not other and lv["m"] / lv["u"] < floor:
            was = round(math.log2(lv["m"] / lv["u"]), 2)
            out.append([name, lv["label"], "less than no agreement: the else level's weight", was])
            lv["m"] = lv["u"] * floor
    return out


# ---------- u on the file to be scored ----------

def assemble(model: dict, counts: dict, sampled: dict) -> dict:
    """Return the model with each level's u measured on the file.

    A level's u is counted exactly, else taken from `sampled`, else the bound on the file. A level never seen in
    training keeps m = u, 0 bits. m and λ stay as fitted, within sensible_m's limits again.
    """
    exact = exact_u(model["levels"], counts)
    filled_m = {tuple(x) for x in model["notes"]["filled"]["m"]}
    out = copy.deepcopy(model)
    for lv in out["levels"]:
        name, label = lv["comparison"], lv["label"]
        lv["u"] = exact.get(name, {}).get(label) or sampled.get(name, {}).get(label) or u_bound(counts, name)
        if (name, label) in filled_m:
            lv["m"] = lv["u"]
    out["notes"] = {**out["notes"], "adjusted": sensible_m(out, filled_m)}
    return out

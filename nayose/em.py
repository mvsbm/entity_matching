"""Stage 2, fit: the model learned from the counts fit.sql leaves, as er/fit.py and er/match.py learn it
(Fellegi–Sunter as Splink 5.0 fits it), the same numbers to the last bit.

    λ   how likely two random records are one customer: the pairs the near-certain rules find (prior), over the share
        of all matches they find (prior_recall), over every pair of the sample
    u   how often two different customers land in a level: counted exactly where fit.sql counts it, else sampled, else
        (no sampled pair reached it) a bound
    m   how often one customer's two records land in a level: EM sessions on the sample's pairs sharing a key
        (patterns), each starting from what those before it learned; a level's m is the median of the sessions'

Then u measured again on the file to be scored: in a bigger file, a field whose values grow with it agrees by chance
less often. fit() is a pure function, JSON in and JSON out, standard library only: fit.sql calls it as fit_model,
BigQuery's Python UDF (engines.functions) and DuckDB's alike. O(rounds · patterns · K).
"""
import copy
import json
import math
import statistics

START_M = 0.95           # Splink's first guess of m for a comparison's first level
UNSEEN_M = 1e-6          # the m Splink weighs a level with when no pair of the session reached it
MAX_ROUNDS = 25          # Splink's max_iterations
CONVERGED = 1e-4         # Splink's em_convergence: stop once no m and no λ moves by more
ELSE = "else"
PRIOR_RULES = {"cif_name": "customer_id + full_name", "cif_company": "customer_id + company_name",
               "name_code_phone": "full_name + address_code + phone"}  # fit_prior's columns, as the report names the rules


def fit(counts: str, settings: str) -> str:
    """The model from fit.sql's counts (counts: its tables, each a list of rows) and config.toml [fit] (settings):
    learned on the sample (learn), its u measured on the file (assemble). Returns each level with m and u as fitted
    and on the file (file_m, file_u), λ, the sample's size and the notes the report reads."""
    c, s = json.loads(counts), json.loads(settings)
    levels = sorted(c["levels"], key=lambda lv: (lv["position"], -lv["gamma"]))
    got = measured(c, s)
    model = learn(levels, got["sample"], c["prior"][0], c["patterns"] or [], s)
    scoring = assemble(model, got["file"])
    return json.dumps(dict(
        levels=[dict(lv, file_m=f["m"], file_u=f["u"]) for lv, f in zip(model["levels"], scoring["levels"])],
        probability=model["probability"], fit_rows=model["fit_rows"], notes=dict(model["notes"], file_adjusted=scoring["notes"]["adjusted"])))


# ---------- u: the counts made shares ----------

def measured(c: dict, s: dict) -> dict[str, dict]:
    """fit.sql's u counts by scope (sample, file); each scope's max_pairs, what its sample drew from."""
    out = {}
    for scope, most in (("sample", float(s["fit_u_max_pairs"])), ("file", float(s["u_max_pairs"]))):
        mine = lambda table: [r for r in c[table] or [] if r["scope"] == scope]
        filled = next(iter(mine("filled")), {"records": 0})
        out[scope] = dict(n=filled["records"], max_pairs=most, filled=filled, plan=next(iter(mine("plan")), {}),
                          outside={r["comparison"]: r["pairs"] for r in mine("outside")},
                          counted={(r["comparison"], r["label"]): r["pairs"] for r in mine("counted")},
                          near={(r["comparison"], r["label"]): r["pairs"] for r in mine("near")},
                          sampled={(r["comparison"], r["gamma"]): r["pairs"] for r in mine("sampled")})
    return out


def exact_u(levels: list[dict], got: dict) -> dict[str, dict[str, float]]:
    """u of each comparison's levels counted exactly, each among the pairs outside its missing level; with every level
    counted, the else level's the rest (er.match.exact_u)."""
    out: dict[str, dict[str, float]] = {}
    for name in comparisons(levels):
        outside = float(got["outside"][name])
        for lv in (lv for lv in levels if lv["comparison"] == name and lv["kind"] != ELSE):
            pairs = got["counted"].get((name, lv["label"]), got["near"].get((name, lv["label"])))
            if pairs is None:
                break  # a level not counted: neither is any after it
            if (u := float(pairs) / outside if outside else 0.0) > 0:
                out.setdefault(name, {})[lv["label"]] = u
        mine = out.get(name, {})
        if all(lv["label"] in mine for lv in levels if lv["comparison"] == name and lv["kind"] != ELSE) and (rest := 1 - sum(mine.values())) > 0:
            mine[ELSE] = rest  # every level counted: nothing left to sample
    return out


def sampled_u(levels: list[dict], got: dict, names: list[str]) -> dict[str, dict[str, float]]:
    """u of these comparisons' levels in the sampled pairs: a level's pairs over those with the comparison filled; a
    level no pair reached, none (er.match.sample_u)."""
    out = {}
    for name in names:
        mine = [lv for lv in levels if lv["comparison"] == name]
        if got["plan"].get(name) is False:
            raise RuntimeError(f"fit.sql counted {name} to its else level and sampled none of its pairs, where nayose.em samples it")
        filled = sum(got["sampled"].get((name, lv["gamma"]), 0) for lv in mine)
        out[name] = {lv["label"]: got["sampled"][name, lv["gamma"]] / filled for lv in mine if got["sampled"].get((name, lv["gamma"]))}
    return out


def u_bound(got: dict, name: str) -> float:
    """95% upper bound on u for a level no sampled pair reached: zero hits among the sampled pairs where the comparison
    is filled, of which there are at least (its fill share)² of the sample (er.match.u_bound)."""
    n = got["n"]
    sampled = min(got["max_pairs"], n * (n - 1) / 2)
    n_filled = max(1, int(sampled * (got["filled"][name] / n if n else 0.0) ** 2))
    return 1 - 0.05 ** (1 / n_filled)


def comparisons(levels: list[dict]) -> list[str]:  # the comparisons, in the model's order
    return list(dict.fromkeys(lv["comparison"] for lv in levels))


# ---------- the model learned on the sample ----------

def learn(levels: list[dict], got: dict, prior_counts: dict, patterns: list[dict], c: dict) -> dict:
    """The model on the sample: u, λ, then m by the EM sessions in order (er.match.train_fs). Refuses when no
    near-certain rule, or no session's key, finds a pair in the sample."""
    names = comparisons(levels)
    exact = exact_u(levels, got)
    skip = {name for name, u in exact.items() if ELSE in u}
    u = {**{name: {} for name in skip}, **sampled_u(levels, got, [x for x in names if x not in skip])}
    u = {name: {**mine, **exact.get(name, {})} for name, mine in u.items()}
    filled_u = [[lv["comparison"], lv["label"]] for lv in levels if lv["label"] not in u[lv["comparison"]]]
    model = dict(levels=[dict(lv, u=u[lv["comparison"]].get(lv["label"]) or u_bound(got, lv["comparison"]), m=None) for lv in levels])

    records, found = prior_counts["records"], prior_counts["found"]
    prior = [rule for rule in PRIOR_RULES if prior_counts[rule]]
    sessions = [s["key"] for s in c["sessions"]]
    patterns = {s: [tuple(p[n] for n in names) + (p["pairs"],) for p in patterns if p["session"] == s] for s in sessions}
    em_pairs = {s: sum(p[-1] for p in patterns[s]) for s in sessions if patterns[s]}
    if not prior:
        raise ValueError(f"no two records of the {records:,} the fit samples agree on any near-certain rule ({'; '.join(PRIOR_RULES.values())}), "
                         "so the chance that two records match can't be estimated: map the fields those rules read")
    if not em_pairs:
        raise ValueError(f"no two records of the {records:,} the fit samples share {' or '.join(sessions)}, the pairs it learns from: "
                         "map those fields to filled columns")
    every = int(records * (records - 1) / 2)
    if found > every * c["prior_recall"]:
        raise ValueError(f"the near-certain rules find {found:,} of the {every:,} pairs, more than a recall of {c['prior_recall']} allows "
                         f"(at least {found / every:,.2f}): raise [fit] prior_recall, or make the prior rules stricter")
    lam = found / c["prior_recall"] / every

    trained: dict[tuple[str, str], list[float]] = {}
    learned = {}
    for s in (x for x in c["sessions"] if x["key"] in em_pairs):
        learned[s["key"]] = session(model, patterns[s["key"]], names, s, lam, trained)
        for key, value in learned[s["key"]].items():
            trained.setdefault(key, []).append(value)
    filled_m = []
    for lv in model["levels"]:
        if (lv["comparison"], lv["label"]) in trained:
            lv["m"] = statistics.median(trained[lv["comparison"], lv["label"]])
        else:
            lv["m"] = lv["u"]
            filled_m.append([lv["comparison"], lv["label"]])
    adjusted = sensible_m(model, {tuple(x) for x in filled_m})
    skipped = [PRIOR_RULES[r] for r in PRIOR_RULES if r not in prior] + [s for s in sessions if s not in em_pairs]
    return dict(model, probability=lam, fit_rows=records,
                notes=dict(fit_rows=records, filled=dict(u=filled_u, m=filled_m), skipped=skipped, adjusted=adjusted, em_pairs=em_pairs,
                           sessions={s: [[name, label, m] for (name, label), m in got_m.items()] for s, got_m in learned.items()}))


def first_m(model: dict, name: str, gamma: int, trained: dict) -> float:
    """The m a session starts a level from: the median of what the sessions before learned, else Splink's guess."""
    lv = next(x for x in model["levels"] if x["comparison"] == name and x["gamma"] == gamma)
    if got := trained.get((name, lv["label"])):
        return statistics.median(got)
    n = sum(1 for x in model["levels"] if x["comparison"] == name)
    return START_M if gamma == n - 1 else (1 - START_M) / (n - 1)


def points(m: float, u: float) -> float:  # a level's points, as Splink writes them: log2(m / u), each at least 1e-300
    return math.log2(max(m, 1e-300) / max(u, 1e-300))


def probability(p: float) -> float:  # points → the chance of a match, written so that 2^points never overflows
    return 1.0 / (1.0 + 2.0 ** -p) if p >= 0 else 2.0 ** p / (1.0 + 2.0 ** p)


def odds(p: float) -> float:
    return p / (1 - p) if p != 1 else math.inf


def session(model: dict, patterns: list[tuple], names: list[str], s: dict, lam: float, trained: dict) -> dict[tuple[str, str], float]:
    """One EM session on the pairs sharing its key: each pattern of levels (the comparisons the key fixed, None) with
    its count, in order. λ among them starts from λ with the evidence of the exact levels the key guarantees; each
    round guesses each pattern's chance of a match from λ and its levels' points, added left to right (E), then counts
    m from those guesses (M); stops once nothing moves by CONVERGED, or after MAX_ROUNDS (er.fit.session). Returns
    each level's m after the last round; a level no pair reached is left out."""
    learns = [i for i, name in enumerate(names) if all(p[i] is not None for p in patterns)]  # the key fixed the others
    order = [names[i] for i in learns]
    start = odds(lam)
    for name, label in s["start"]:
        lv = next(x for x in model["levels"] if x["comparison"] == name and x["label"] == label)
        start = (first_m(model, name, lv["gamma"], trained) / lv["u"] if lv["u"] != 0 else math.inf) * start
    lam_s = start / (1 + start)
    u = {(lv["comparison"], lv["gamma"]): lv["u"] for lv in model["levels"] if lv["comparison"] in order}
    label = {(lv["comparison"], lv["gamma"]): lv["label"] for lv in model["levels"]}
    m: dict[tuple[str, int], float | None] = {key: first_m(model, key[0], key[1], trained) for key in u}
    rows = [(list(x[:-1]), x[-1]) for x in sorted(tuple(p[i] for i in learns) + (p[-1],) for p in patterns)]  # in order, as SQL's ORDER BY ALL
    for _ in range(MAX_ROUNDS):
        points_at = {key: points(UNSEEN_M if m[key] is None else m[key], u[key]) for key in m} | {(n, -1): 0.0 for n in order}
        prior_points = math.log2(odds(lam_s))
        expected: dict[tuple[str, int], float] = {}
        matches, pairs = 0.0, 0
        for gammas, count in rows:
            total = prior_points
            for name, g in zip(order, gammas):
                total = total + points_at[name, g]
            p = probability(total)
            matches += p * count
            pairs += count
            for name, g in zip(order, gammas):
                expected[name, g] = expected.get((name, g), 0.0) + p * count
        new: dict[tuple[str, int], float | None] = {}
        for name in order:
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
    return {(key[0], label[key]): v for key, v in m.items() if v is not None}


def sensible_m(model: dict, filled: set[tuple[str, str]]) -> list[list]:
    """Two limits on what EM's m may say, each where a sample gave it nothing to go by; returns what changed
    (er.match.sensible_m).
    - A near level stands for a typo in a value matches share: where no match agreed exactly in training (every exact
      level's m filled as u), nearness is neighbouring values (IDs handed out in sequence), no evidence: m = u, 0 bits.
    - Partial agreement is never more evidence against a match than none: a level weighs at least its else level."""
    out = []
    for name in comparisons(model["levels"]):
        mine = [lv for lv in model["levels"] if lv["comparison"] == name]
        exact = [lv for lv in mine if lv["kind"] == "exact"]
        if exact and all((name, lv["label"]) in filled for lv in exact):
            for lv in mine:
                if lv["kind"] == "near" and lv["m"] != lv["u"]:
                    out.append([name, lv["label"], "no exact agreement among matches: 0 bits", round(math.log2(lv["m"] / lv["u"]), 2)])
                    lv["m"] = lv["u"]
        other = next((lv for lv in mine if lv["kind"] == ELSE), None)
        if other:
            floor = other["m"] / other["u"]
            for lv in mine:
                if lv is not other and lv["m"] / lv["u"] < floor:
                    out.append([name, lv["label"], "less than no agreement: the else level's weight", round(math.log2(lv["m"] / lv["u"]), 2)])
                    lv["m"] = lv["u"] * floor
    return out


# ---------- u on the file to be scored ----------

def assemble(model: dict, got: dict) -> dict:
    """The model with each level's u measured on the file: counted exactly, else sampled, else the bound on the file. A
    level never seen in training keeps m = u, 0 bits; m and λ stay as fitted, within sensible_m's limits again
    (er.match.assemble_u)."""
    levels = model["levels"]
    exact = exact_u(levels, got)
    skip = {name for name, u in exact.items() if ELSE in u}
    sampled = sampled_u(levels, got, [x for x in comparisons(levels) if x not in skip])
    filled_m = {tuple(x) for x in model["notes"]["filled"]["m"]}
    out = copy.deepcopy(model)
    for lv in out["levels"]:
        name, label = lv["comparison"], lv["label"]
        lv["u"] = exact.get(name, {}).get(label) or sampled.get(name, {}).get(label) or u_bound(got, name)
        if (name, label) in filled_m:
            lv["m"] = lv["u"]
    out["notes"] = {**out["notes"], "adjusted": sensible_m(out, filled_m)}
    return out

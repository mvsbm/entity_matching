"""Stage 2, fit: the model learned from the counts fit.sql and u.sql leave, as er/fit.py and er/match.py learn it
(Fellegi–Sunter as Splink 5.0 fits it), the same numbers to the last bit.

    λ   how likely two random records are one customer: the pairs the near-certain rules find (fit_prior), over the
        share of all matches they find (prior_recall), over every pair of the sample
    u   how often two different customers land in a level: counted exactly where u.sql counts it, else sampled, else
        (no sampled pair reached it) a bound
    m   how often one customer's two records land in a level: EM sessions on the sample's pairs sharing a key
        (em_patterns), each starting from what those before it learned; a level's m is the median of the sessions'

Then u measured again on the file to be scored: in a bigger file, a field whose values grow with it agrees by chance
less often. fit(engine) writes the tables model (as fitted, the sample's u), scoring (the file's u) and fit (λ, the
sample's size, and what the report says of the fit). O(n + S·K) on the sample, O(N + S·K) on the file; EM
O(rounds · patterns · K).
"""
import copy
import json
import math
import statistics

import pandas as pd

import nayose

START_M = 0.95           # Splink's first guess of m for a comparison's first level
UNSEEN_M = 1e-6          # the m Splink weighs a level with when no pair of the session reached it
MAX_ROUNDS = 25          # Splink's max_iterations
CONVERGED = 1e-4         # Splink's em_convergence: stop once no m and no λ moves by more
ELSE = "else"
PRIOR_RULES = {"cif_name": "customer_id + full_name", "cif_company": "customer_id + company_name",
               "name_code_phone": "full_name + address_code + phone"}  # fit_prior's columns, as the report names the rules


def fit(engine) -> None:
    """Stage 2 on `engine`, after records: the sample and its counts (comparisons.sql, fit.sql, u.sql), the model
    learned (learn), u measured again on the file (u.sql on records, assemble), the tables written."""
    c = nayose.config()["fit"]
    nayose.stage(engine, "comparisons")
    levels = [dict(zip(("position", "comparison", "gamma", "label", "kind"), r))
              for r in engine.rows("SELECT position, comparison, gamma, label, kind FROM levels ORDER BY position, gamma DESC")]
    nayose.stage(engine, "fit", fit_rows=int(c["fit_rows"]))
    sample = measured(engine, float(c["fit_u_max_pairs"]), c["seed"])
    model = learn(engine, levels, sample, c)
    engine.run("CREATE OR REPLACE VIEW u_records AS SELECT * FROM records")
    scoring = assemble(model, measured(engine, float(c["u_max_pairs"]), c["seed"]))
    for name, m in (("model", model), ("scoring", scoring)):
        engine.put(name, pd.DataFrame([dict(position=lv["position"], comparison=lv["comparison"], gamma=lv["gamma"], label=lv["label"],
                                            kind=lv["kind"], m=lv["m"], u=lv["u"]) for lv in m["levels"]]))
    engine.put("fit", pd.DataFrame([dict(probability=model["probability"], fit_rows=model["fit_rows"],
                                         notes=json.dumps(model["notes"], ensure_ascii=False),
                                         scoring_adjusted=json.dumps(scoring["notes"]["adjusted"], ensure_ascii=False))]))


# ---------- u: the counts made shares ----------

def measured(engine, max_pairs: float, seed) -> dict:
    """u.sql on u_records, about max_pairs pairs sampled: its counts, as read back. O(N + max_pairs · K)."""
    n = engine.value("SELECT COUNT(*) FROM u_records")
    share = 0.5 * ((8 * max_pairs + 1) ** 0.5 + 1) / max(n, 1)
    nayose.stage(engine, "u", draw=share < 1, cut=max(1, round(share * 1_000_000_000)), seed=str(seed))
    filled = dict(zip(("records", "name", "company", "address", "phone", "cif", "birth"), engine.rows("SELECT * FROM u_filled")[0]))
    plan = dict(zip(("phone", "cif", "birth"), engine.rows("SELECT phone, cif, birth FROM u_plan")[0]))
    return dict(n=n, max_pairs=max_pairs, filled=filled, plan=plan,
                outside={c: p for c, p in engine.rows("SELECT comparison, pairs FROM u_outside")},
                counted={(c, label): p for c, label, p in engine.rows("SELECT comparison, label, pairs FROM u_counted")},
                near={(c, label): p for c, label, p in engine.rows("SELECT comparison, label, pairs FROM u_near")},
                sampled={(c, g): p for c, g, p in engine.rows("SELECT comparison, gamma, pairs FROM u_sampled")})


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
            raise RuntimeError(f"u.sql counted {name} to its else level and sampled none of its pairs, where nayose.em samples it")
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

def learn(engine, levels: list[dict], got: dict, c: dict) -> dict:
    """The model on the sample: u, λ, then m by the EM sessions in order (er.match.train_fs). Refuses when no
    near-certain rule, or no session's key, finds a pair in the sample."""
    names = comparisons(levels)
    exact = exact_u(levels, got)
    skip = {name for name, u in exact.items() if ELSE in u}
    u = {**{name: {} for name in skip}, **sampled_u(levels, got, [x for x in names if x not in skip])}
    u = {name: {**mine, **exact.get(name, {})} for name, mine in u.items()}
    filled_u = [[lv["comparison"], lv["label"]] for lv in levels if lv["label"] not in u[lv["comparison"]]]
    model = dict(levels=[dict(lv, u=u[lv["comparison"]].get(lv["label"]) or u_bound(got, lv["comparison"]), m=None) for lv in levels])

    records, found, *rules = engine.rows("SELECT records, found, cif_name, cif_company, name_code_phone FROM fit_prior")[0]
    prior = [rule for rule, pairs in zip(PRIOR_RULES, rules) if pairs]
    sessions = [s["key"] for s in c["sessions"]]
    patterns = {s: engine.rows("SELECT * EXCEPT (session) FROM em_patterns WHERE session = @s", {"s": s}) for s in sessions}
    em_pairs = {s: sum(p[-1] for p in patterns[s]) for s in sessions if patterns[s]}
    if not prior:
        raise nayose.InputError(f"no two records of the {records:,} the fit samples agree on any near-certain rule ({'; '.join(PRIOR_RULES.values())}), "
                                "so the chance that two records match can't be estimated", fix="map the fields those rules read, or give a model fitted before")
    if not em_pairs:
        raise nayose.InputError(f"no two records of the {records:,} the fit samples share {' or '.join(sessions)}, the pairs it learns from",
                                fix="map those fields to filled columns, or give a model fitted before")
    every = int(records * (records - 1) / 2)
    if found > every * c["prior_recall"]:
        raise nayose.InputError(f"the near-certain rules find {found:,} of the {every:,} pairs, more than a recall of {c['prior_recall']} allows "
                                f"(at least {found / every:,.2f})", fix="raise [fit] prior_recall, or make the prior rules stricter")
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

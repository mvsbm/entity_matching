"""Stage 2, fit: learn the Fellegi–Sunter model from the counts fit.sql leaves, to the same numbers Splink 5.0 gives.

The model has three kinds of number:

    λ   how likely two random records are one customer: the pairs the near-certain rules find (the prior), divided by
        the share of all matches those rules find (prior_recall), divided by every pair of the sample.
    u   how often two different customers fall into a level by chance: counted exactly where fit.sql counts it, else
        measured on sampled pairs, else, when no sampled pair reached the level, an upper bound.
    m   how often one customer's two records fall into a level: learned by EM sessions on the sample's pairs that
        share a key, each session starting from what the sessions before it learned. A level's m is the median.

After learning, u is measured again on the file to be scored: in a bigger file, a field whose values grow with it
agrees by chance less often. An update keeps the model and measures u again on the run's records (refresh): every
level counted exactly is counted again, and a sampled comparison is sampled again only once its drift outweighs its
sampling error.

fit() and resampled() are pure functions, JSON in and JSON out, using the standard library only. fit.sql calls them
as fit_model and resampled, on BigQuery as Python UDFs (engines.functions) and on DuckDB alike. Cost:
O(rounds · patterns · K) for K comparisons.
"""
import copy
import json
import math
import statistics

START_M = 0.95  # Splink's first guess of m for a comparison's first level
UNSEEN_M = 1e-6  # the m Splink gives a level that no pair of the session reached
MAX_ROUNDS = 25  # Splink's max_iterations
CONVERGED = 1e-4  # Splink's em_convergence: stop once no m and no λ moves by more than this
ELSE = "else"  # the label of each comparison's last level: none of the others
PRIOR_RULES = {  # fit_prior's columns, named as the report names the rules
    "cif_name": "customer_id + full_name",
    "cif_company": "customer_id + company_name",
    "name_code_phone": "full_name + address_code + phone",
}


def in_order(lv: dict) -> tuple:
    """Return a level's place in the model: by comparison, then the strongest level first."""
    return lv["position"], -lv["gamma"]


def fit(counts: str, settings: str, stored: str | None = None) -> str:
    """Fit the model and return it as JSON.

    `counts` holds fit.sql's tables, each a list of rows; `settings` is config.toml's [fit]. Without `stored` (a build),
    the model is learned on the sample (learn) and its u measured on the file (assemble). With `stored`, what fit
    returned for an earlier job, there are two cases. If it has a basis (an update), the model is kept and its u
    measured again on the run's records (refresh). If its basis is None (a model fitted on another file, as
    scripts/benchmark.py fits one on a train split), the model is kept and its u measured on this file whole.

    The result holds each level with m and u as fitted and as measured on the file (file_m, file_u, and bits: what a
    score adds), λ and its bits at the file's size (prior_bits), the sample's size, the notes the report reads, and
    what an update needs: the model as fitted and each comparison's basis (u_basis).
    """
    tables, config = json.loads(counts), json.loads(settings)
    levels = sorted(tables["levels"], key=in_order)
    measures = measured(tables, config)
    kept = json.loads(stored) if stored is not None else None
    if kept is not None and kept["basis"] is not None:
        return refresh(kept, measures["file"])
    if kept is not None:
        model = kept["model"]
    else:
        model = learn(levels, measures["sample"], tables["prior"][0], tables["patterns"] or [], config)
    file = measures["file"]
    exact = exact_u(levels, file)
    sampled = sampled_u(levels, file, [x for x in comparisons(levels) if ELSE not in exact.get(x, {})])
    basis = u_basis(file, sampled, exact, comparisons(levels))
    return fitted(model, assemble(model, file, sampled), file["n"], basis, [])


def refresh(stored: dict, counts: dict) -> str:
    """Return an update's model: the stored one, with its u measured again on the run's records.

    Every level counted exactly is counted again. A comparison is sampled again only once stale_u finds it stale; the
    others keep their sample. O(K) on the counts.
    """
    model, basis = stored["model"], stored["basis"]
    levels, n = model["levels"], counts["n"]
    exact = exact_u(levels, counts)
    again, check = stale(levels, basis, exact, n)
    basis = {**basis, **u_basis(counts, sampled_u(levels, counts, again), exact, again)}
    for name, x in check.items():
        basis[name]["last_check"] = {k: v if math.isfinite(v) else None for k, v in x.items()}
    scoring = assemble(model, counts, {name: b["sampled"] for name, b in basis.items()})
    return fitted(model, scoring, n, basis, [dict(comparison=x, **basis[x]["last_check"]) for x in again])


def stale(levels: list[dict], basis: dict, exact: dict, n: int) -> tuple[list[str], dict]:
    """Return the comparisons an update samples again, and stale_u's check of every comparison.

    A comparison is sampled again when stale_u finds it stale and its else level isn't counted exactly.
    """
    check = stale_u(levels, basis, exact, n)
    again = [x for x in comparisons(levels)
             if check[x]["drift_bits"] > check[x]["se_bits"] and ELSE not in exact.get(x, {})]
    return again, check


def resampled(counts: str, settings: str, stored: str | None = None) -> str:
    """Return the comparisons whose u an update's fit samples, comma-separated, from fit.sql's exact counts alone.

    For an update, these are the comparisons refresh will sample again (stale). For a build given a model, they are
    the comparisons not counted to their else level. An empty string means the sample would go unused, so fit.sql
    draws none. A build that fits its own model always samples, so it doesn't call this.
    """
    tables, config = json.loads(counts), json.loads(settings)
    file = measured(tables, config)["file"]
    if stored is not None and (kept := json.loads(stored))["basis"] is not None:
        levels = kept["model"]["levels"]
        return ",".join(stale(levels, kept["basis"], exact_u(levels, file), file["n"])[0])
    levels = sorted(tables["levels"], key=in_order)
    exact = exact_u(levels, file)
    return ",".join(x for x in comparisons(levels) if ELSE not in exact.get(x, {}))


def fitted(model: dict, scoring: dict, n: int, basis: dict, again: list[dict]) -> str:
    """Return what fit gives back, as JSON: the model as scored on a file of `n` records."""
    # λ is a per-pair rate, so it is rescaled to the file's size (score.sql's weights rescale it the same way)
    lam = min(model["probability"] * (model["fit_rows"] - 1) / max(n - 1, 1), 1 - 1e-9)
    levels = [dict(lv, file_m=f["m"], file_u=f["u"], bits=bits(f["m"], f["u"]))
              for lv, f in zip(model["levels"], scoring["levels"])]
    notes = dict(model["notes"], file_adjusted=scoring["notes"]["adjusted"], sampled_again=again)
    return json.dumps(dict(levels=levels, probability=model["probability"], fit_rows=model["fit_rows"], records=n,
                           prior_bits=math.log2(lam / (1 - lam)), notes=notes, model=model, basis=basis))


def u_basis(counts: dict, sampled: dict, exact: dict, names: list[str]) -> dict:
    """Return what a later update needs to tell whether these comparisons' sampled u went stale.

    That is the sampled u, the u counted exactly alongside, the record count, and how many sampled pairs had the
    comparison filled.
    """
    return {x: dict(sampled=sampled.get(x, {}), exact=exact.get(x, {}), n=counts["n"], pairs=filled_pairs(counts, x))
            for x in names}


def filled_pairs(counts: dict, name: str) -> float:
    """Return about how many sampled pairs have the comparison filled on both sides."""
    n = counts["n"]
    return min(counts["max_pairs"], n * (n - 1) / 2) * (counts["filled"][name] / n if n else 0.0) ** 2


def stale_u(levels: list[dict], basis: dict, exact_now: dict, n: int) -> dict[str, dict[str, float]]:
    """Return, for each comparison, how far its sampled u have likely drifted, and how precise its sample was.

    drift_bits is the drift of the comparison's leading exact level, counted exactly now and then; without one, it is
    log2(N now / N then), as an equality level can't fall faster than that. se_bits is the sampling error of its most
    precise sampled level, 1/(ln 2·√hits). Once drift > se, staleness outweighs the sample's own noise. A comparison
    never sampled has an infinite drift.
    """
    out = {}
    for name in comparisons(levels):
        b = basis.get(name)
        if b is None:
            out[name] = dict(drift_bits=math.inf, se_bits=0.0)
            continue
        lead = next(iter(b["exact"]), None)
        now = exact_now.get(name, {}).get(lead) if lead else None
        drift = abs(math.log2(now / b["exact"][lead])) if now else math.log2(max(n, 2) / max(b["n"], 2))
        hits = [u * b["pairs"] for label, u in b["sampled"].items() if label != ELSE and label not in b["exact"]]
        se = min((1 / (math.log(2) * math.sqrt(h)) for h in hits if h >= 1), default=math.inf)
        out[name] = dict(drift_bits=drift, se_bits=se)
    return out


def bits(m: float, u: float) -> float:
    """Return a level's weight as Splink writes it: log2(m/u), each clamped at 1e-300."""
    return math.log2(max(m, 1e-300) / max(u, 1e-300))


# ---------- u: the counts made into shares ----------

def measured(tables: dict, config: dict) -> dict[str, dict]:
    """Return fit.sql's u counts by scope (sample, file), with each scope's max_pairs: what its sample drew from."""
    out = {}
    for scope, most in (("sample", float(config["fit_u_max_pairs"])), ("file", float(config["u_max_pairs"]))):
        def rows_of(table: str) -> list[dict]:  # a missing table has no rows (resampled runs before sampling)
            return [r for r in tables.get(table) or [] if r["scope"] == scope]
        filled = next(iter(rows_of("filled")), {"records": 0})
        out[scope] = dict(n=filled["records"], max_pairs=most, filled=filled, plan=next(iter(rows_of("plan")), {}),
                          outside={r["comparison"]: r["pairs"] for r in rows_of("outside")},
                          counted={(r["comparison"], r["label"]): r["pairs"] for r in rows_of("counted")},
                          near={(r["comparison"], r["label"]): r["pairs"] for r in rows_of("near")},
                          sampled={(r["comparison"], r["gamma"]): r["pairs"] for r in rows_of("sampled")})
    return out


def exact_u(levels: list[dict], counts: dict) -> dict[str, dict[str, float]]:
    """Return the u of each comparison's levels that fit.sql counted exactly.

    Each u is a share of the pairs outside the comparison's missing level. When every level is counted, the else
    level's u is the rest.
    """
    out: dict[str, dict[str, float]] = {}
    for name in comparisons(levels):
        outside = float(counts["outside"][name])
        named = [lv for lv in levels if lv["comparison"] == name and lv["kind"] != ELSE]
        for lv in named:
            pairs = counts["counted"].get((name, lv["label"]), counts["near"].get((name, lv["label"])))
            if pairs is None:
                break  # a level not counted: neither is any after it
            if (u := float(pairs) / outside if outside else 0.0) > 0:
                out.setdefault(name, {})[lv["label"]] = u
        u_of = out.get(name, {})
        if all(lv["label"] in u_of for lv in named) and (rest := 1 - sum(u_of.values())) > 0:
            u_of[ELSE] = rest  # every level counted: nothing is left to sample
    return out


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
    return 1 - 0.05 ** (1 / max(1, int(filled_pairs(counts, name))))


def comparisons(levels: list[dict]) -> list[str]:
    """Return the comparisons, in the model's order."""
    return list(dict.fromkeys(lv["comparison"] for lv in levels))


# ---------- the model learned on the sample ----------

def learn(levels: list[dict], counts: dict, prior_counts: dict, patterns: list[dict], settings: dict) -> dict:
    """Learn the model on the sample: u, then λ, then m by the EM sessions in order.

    Raises ValueError when no near-certain rule, or no session's key, finds a pair in the sample.
    """
    names = comparisons(levels)
    exact = exact_u(levels, counts)
    skip = {name for name, u in exact.items() if ELSE in u}
    u = {**{name: {} for name in skip}, **sampled_u(levels, counts, [x for x in names if x not in skip])}
    u = {name: {**u_of, **exact.get(name, {})} for name, u_of in u.items()}
    filled_u = [[lv["comparison"], lv["label"]] for lv in levels if lv["label"] not in u[lv["comparison"]]]
    model = dict(levels=[dict(lv, u=u[lv["comparison"]].get(lv["label"]) or u_bound(counts, lv["comparison"]), m=None)
                         for lv in levels])

    records, found = prior_counts["records"], prior_counts["found"]
    prior = [rule for rule in PRIOR_RULES if prior_counts[rule]]
    sessions = [s["key"] for s in settings["sessions"]]
    patterns = {s: [tuple(p[n] for n in names) + (p["pairs"],) for p in patterns if p["session"] == s]
                for s in sessions}
    em_pairs = {s: sum(p[-1] for p in patterns[s]) for s in sessions if patterns[s]}
    if not prior:
        raise ValueError(f"no two records of the {records:,} the fit samples agree on any near-certain rule "
                         f"({'; '.join(PRIOR_RULES.values())}), so the chance that two records match can't be "
                         "estimated: map the fields those rules read")
    if not em_pairs:
        raise ValueError(f"no two records of the {records:,} the fit samples share {' or '.join(sessions)}, "
                         "the pairs it learns from: map those fields to filled columns")
    every = int(records * (records - 1) / 2)
    if found > every * settings["prior_recall"]:
        raise ValueError(f"the near-certain rules find {found:,} of the {every:,} pairs, more than a recall of "
                         f"{settings['prior_recall']} allows (at least {found / every:,.2f}): "
                         "raise [fit] prior_recall, or make the prior rules stricter")
    lam = found / settings["prior_recall"] / every

    trained: dict[tuple[str, str], list[float]] = {}  # each level's m, as each session so far learned it
    learned = {}
    for s in (x for x in settings["sessions"] if x["key"] in em_pairs):
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
    by_session = {s: [[name, label, m] for (name, label), m in m_of.items()] for s, m_of in learned.items()}
    return dict(model, probability=lam, fit_rows=records,
                notes=dict(fit_rows=records, filled=dict(u=filled_u, m=filled_m), skipped=skipped, adjusted=adjusted,
                           em_pairs=em_pairs, sessions=by_session))


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
    """Run one EM session on the pairs that share its key, and return each level's m after its last round.

    `patterns` holds each pattern of levels with its count, in order; a comparison the key fixed is None. λ among
    these pairs starts from λ with the evidence of the exact levels the key guarantees. Each round guesses each
    pattern's chance of a match from λ and its levels' points, added left to right (E), then counts m from those
    guesses (M). The session stops once nothing moves by CONVERGED, or after MAX_ROUNDS. A level no pair reached is
    left out of the result.
    """
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
    # in order, as SQL's ORDER BY ALL sorts them
    rows = [(list(x[:-1]), x[-1]) for x in sorted(tuple(p[i] for i in learns) + (p[-1],) for p in patterns)]
    for _ in range(MAX_ROUNDS):
        points_at = {key: bits(UNSEEN_M if m[key] is None else m[key], u[key]) for key in m}
        points_at |= {(n, -1): 0.0 for n in order}  # a missing comparison weighs nothing
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
        moved = [abs((UNSEEN_M if new[k] is None else new[k]) - (UNSEEN_M if m[k] is None else m[k])) for k in m]
        moved.append(abs(new_lam - lam_s))
        m, lam_s = new, new_lam
        if max((x for x in moved if not math.isnan(x)), default=0.0) < CONVERGED:
            break
    return {(key[0], label[key]): v for key, v in m.items() if v is not None}


def sensible_m(model: dict, filled: set[tuple[str, str]]) -> list[list]:
    """Hold EM's m to two limits, each where the sample gave EM nothing to go by, and return what changed.

    - A near level stands for a typo in a value that matches share. Where no match agreed exactly in training (each
      exact level's m was filled as its u), nearness only means neighbouring values, such as IDs handed out in
      sequence: no evidence, so m = u and the level weighs 0 bits.
    - Partial agreement is never more evidence against a match than none: a level weighs at least its else level.
    """
    out = []
    for name in comparisons(model["levels"]):
        its_levels = [lv for lv in model["levels"] if lv["comparison"] == name]
        exact = [lv for lv in its_levels if lv["kind"] == "exact"]
        if exact and all((name, lv["label"]) in filled for lv in exact):
            for lv in its_levels:
                if lv["kind"] == "near" and lv["m"] != lv["u"]:
                    was = round(math.log2(lv["m"] / lv["u"]), 2)
                    out.append([name, lv["label"], "no exact agreement among matches: 0 bits", was])
                    lv["m"] = lv["u"]
        other = next((lv for lv in its_levels if lv["kind"] == ELSE), None)
        if other:
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

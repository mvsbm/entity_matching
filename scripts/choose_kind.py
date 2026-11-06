"""Choose how to tell persons from companies (config/pipeline.toml [kind]): every combination of the ideas, judged across
the range of what a file can't tell about itself. Writes reports/choose_kind.md. The truth is the generator's.

    .venv/bin/python scripts/choose_kind.py          # about 8 minutes

Data. Companies: data/reference/registry.json, real corporations' readings, written the ways bank records write them
(er.generate.bank_name); training uses Miyagi's and Okayama's, the test Fukuoka's. Persons: the personas, half each.
A test population has 20,000 customers (a fifth companies) with 1 + Poisson records each, a person/company flag, birth
dates on 15% of a person's records, company records under the representative's name, and sole traders (legally persons)
named like a shop on most of their records.

The unknowns, 12 scenarios over their plausible range (a Latin hypercube): the flag wrong at random (1–10%) and on
representative-named records (20–80%), companies with such records (5–20%), sole traders (2–15%) and how often their
flag says company (10–50%), companies with a date in the birth-date column (0–60% of their records: the founding year,
or the representative's birth date, alternating).

The ideas: legal forms (the forms config/generator.toml writes, or the bank table of config/settings.toml) × the name
model's character n-grams (1–3, 1–4) × its training (public data; also the file's own records with a legal form) × the
combiner's signals (each subset of: the flag, a birth date filled, the birth year, a legal form, a name of known surname
and given name) × the combiner (gradient-boosted trees of depth 2 or 3, logistic regression), fitted on 1,000 records
labelled at random. Successive halving: every combination on 3 scenarios, the best quarter on 6, the best quarter of
those on 12; the combination of config/pipeline.toml always on 12.

Correct first: on each side, the share decided while its wrong calls stay within a budget (company calls: 0.1% wrong;
person calls: 1%), the line placed with the truth, so the ranking measures the score itself. Then, for the pipeline's
combination: how sole traders are counted, and how well people's answers place the lines (er.kind.lines).
"""
import itertools
import logging
import time
from dataclasses import replace

import numpy as np
import pandas as pd
from scipy.stats import qmc
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from er.config import load_pipeline
from er.generate import bank_name, kana_typo, load_reference, load_registry, load_spec, name_model_split
from er.io import markdown
from er.kind import NameModel, legal, lines, text
from er.settings import load_settings
from er.standardize import normalize

logging.disable(logging.WARNING)
S = load_settings()
SPEC = load_spec(S.root / "config" / "generator.toml")[0]
KIND = load_pipeline(S.root / "config" / "pipeline.toml", S.standardize, S.chains, S.columns).kind
BUDGET_C, BUDGET_P, HAND, CUSTOMERS = 0.001, 0.01, 1_000, 20_000
SIGNALS = ("flag", "birth", "birth_year", "legal", "known_name")
COMBINERS = ("gbdt2", "gbdt3", "lr")
GENERATOR_FORMS = tuple(sorted({normalize(pd.Series([f], dtype="string"), ("nfkc",), S.standardize)[0] for f, _ in SPEC.legal_forms_written if f}))
STD = {"bank table": S.standardize, "generator's forms": replace(S.standardize, legal_forms=GENERATOR_FORMS, legal_front=(), legal_end=())}
PIPELINE = dict(legal="bank table", ngram=KIND.ngram, train="public", signals=("flag", "birth_year", "legal"), combiner=f"gbdt{KIND.depth}")


def scenarios(n: int = 12) -> list[dict]:
    x = qmc.LatinHypercube(d=6, seed=0).random(n)
    lo, hi = np.array([0.01, 0.2, 0.05, 0.02, 0.1, 0.0]), np.array([0.10, 0.8, 0.20, 0.15, 0.5, 0.6])
    x = lo + x * (hi - lo)
    return [dict(flag_random=a, flag_rep=b, rep_share=c, sole_share=d, flag_sole=e, company_dates=f, company_date=("founding", "representative")[i % 2])
            for i, (a, b, c, d, e, f) in enumerate(x)]


def write_company(x, rng: np.random.Generator) -> str:
    return bank_name(x.reading, x.legal, x.abbreviation, x.front, rng, S.standardize.legal_front, S.standardize.legal_end, SPEC.kana_confusions, SPEC.branches)


def write_person(x, rng: np.random.Generator) -> str:
    s = x.surname_kana + ("　" if rng.random() < 0.3 else "") + x.given_kana
    return kana_typo(s, rng, SPEC.kana_confusions) if rng.random() < 0.08 else s


def population(companies: pd.DataFrame, persons: pd.DataFrame, shops: list[str], sc: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Customers and their records: name, flag (1 company, 0 person), birth year, the truth y (1 company) and case."""
    nc = int(CUSTOMERS * 0.2)
    firms = companies.sample(nc, random_state=int(rng.integers(1 << 31)))
    people = persons.sample(CUSTOMERS - nc, replace=True, random_state=int(rng.integers(1 << 31)))
    reps = persons.sample(nc, replace=True, random_state=int(rng.integers(1 << 31)))
    rows = []
    for e, (x, r) in enumerate(zip(firms.itertuples(), reps.itertuples())):
        rep_named = rng.random() < sc["rep_share"]
        for _ in range(1 + rng.poisson(0.8)):
            is_rep = rep_named and rng.random() < 0.5
            year = (int(rng.integers(1950, 2026)) if sc["company_date"] == "founding" else 2026 - r.age) if rng.random() < sc["company_dates"] else np.nan
            rows.append(dict(entity=f"C{e}", y=1, name=write_person(r, rng) if is_rep else write_company(x, rng),
                             case="representative" if is_rep else "company", birth_year=year, trade=False))
    for e, x in enumerate(people.itertuples()):
        sole, shop = rng.random() < sc["sole_share"], shops[int(rng.integers(len(shops)))]
        for _ in range(1 + rng.poisson(0.3)):
            trade = sole and rng.random() < 0.7
            name = shop + ("　" + write_person(x, rng) if rng.random() < 0.5 else "") if trade else write_person(x, rng)
            rows.append(dict(entity=f"P{e}", y=0, name=name, case="sole trader" if sole else "person",
                             birth_year=2026 - x.age if rng.random() < 0.15 else np.nan, trade=trade))
    d = pd.DataFrame(rows)
    wrong = rng.random(len(d)) < np.select([d.case == "representative", d.case == "sole trader"], [sc["flag_rep"], sc["flag_sole"]], sc["flag_random"])
    d["flag"] = np.where(wrong, 1 - d.y, d.y)
    d["birth"] = d.birth_year.notna().astype(float)
    return d


def coverage(score: np.ndarray, right: np.ndarray, budget: float) -> float:
    """The most records decided, best score first, with wrong calls at most `budget` of them; their share of the right ones."""
    order = np.argsort(-score, kind="stable")
    r = right[order]
    ok = np.flatnonzero(np.cumsum(~r) <= budget * np.arange(1, len(r) + 1))
    return float(np.cumsum(r)[ok[-1]] / max(right.sum(), 1)) if len(ok) else 0.0


def make(kind: str):
    return LogisticRegression(max_iter=3000) if kind == "lr" else HistGradientBoostingClassifier(max_depth=int(kind[-1]), max_iter=100, learning_rate=0.1, random_state=0)


def main() -> None:
    t0 = time.perf_counter()
    p_train, p_test, c_train, fukuoka = name_model_split(load_reference(S.paths["reference"])[0], load_registry(S.paths["reference"]))
    c_test, shops = fukuoka.iloc[: len(fukuoka) // 2], fukuoka.iloc[len(fukuoka) // 2:]["reading"].tolist()
    fold = lambda s: normalize(pd.Series(s, dtype="string"), ("nfkc", "strip_spaces", "kana_fold"), S.standardize)
    surnames, givens = set(fold(p_train.surname_kana).dropna()), set(fold(p_train.given_kana).dropna())
    rng = np.random.default_rng(1)
    pub = pd.DataFrame(dict(name=[write_company(x, rng) for x in c_train.itertuples()], y=1))
    pub = pd.concat([pub, pd.DataFrame(dict(name=[write_person(x, rng) for x in p_train.itertuples()] * 2, y=0))], ignore_index=True)
    public = {(lg, ng): NameModel.fit(text(pub.name, STD[lg]), pub.y.to_numpy(), ng) for lg in STD for ng in (3, 4)}
    print(f"ready in {time.perf_counter() - t0:.0f}s: name models on {len(pub):,} public names", flush=True)

    plan, cache = scenarios(), {}

    def scenario(i: int):
        if i not in cache:
            d = population(c_test, p_test, shops, plan[i], np.random.default_rng(100 + i))
            for lg, std in STD.items():
                d[f"legal:{lg}"] = legal(d["name"], std).astype(float)
                d[f"text:{lg}"] = text(d["name"], std)
            known = lambda s: isinstance(s, str) and any(s[:j] in surnames and s[j:] in givens for j in range(1, len(s)))
            d["known_name"] = d["text:bank table"].map(known).astype(float)
            hand = d.sample(HAND, random_state=i)
            logits = {}
            for lg in STD:
                mine = d[d[f"legal:{lg}"] == 1].drop(hand.index, errors="ignore")
                for ng in (3, 4):
                    logits[(lg, ng, "public")] = public[(lg, ng)].logit(d[f"text:{lg}"])
                    own = NameModel.fit(pd.concat([text(pub.name, STD[lg]), mine[f"text:{lg}"]]), np.r_[pub.y, np.ones(len(mine))], ng)
                    logits[(lg, ng, "public + the file's legal-form records")] = own.logit(d[f"text:{lg}"])
            cache[i] = (d, hand, d.drop(hand.index), logits)
        return cache[i]

    def features(cfg: dict, d: pd.DataFrame, logits: dict) -> np.ndarray:
        cols = [d[f"legal:{cfg['legal']}"] if s == "legal" else d[s] for s in cfg["signals"]]
        x = np.column_stack([logits[(cfg["legal"], cfg["ngram"], cfg["train"])][d.index]] + [c.to_numpy(dtype=float) for c in cols])
        return np.nan_to_num(x) if cfg["combiner"] == "lr" else x

    def evaluate(cfg: dict, i: int) -> tuple[float, float]:
        d, hand, rest, logits = scenario(i)
        logits = {k: pd.Series(v, index=d.index) for k, v in logits.items()}
        p = make(cfg["combiner"]).fit(features(cfg, hand, logits), hand.y).predict_proba(features(cfg, rest, logits))[:, 1]
        return coverage(p, rest.y.to_numpy() == 1, BUDGET_C), coverage(1 - p, rest.y.to_numpy() == 0, BUDGET_P)

    configs = [dict(legal=lg, ngram=ng, train=tr, signals=sig, combiner=c) for lg in STD for ng in (3, 4)
               for tr in ("public", "public + the file's legal-form records")
               for r in range(len(SIGNALS) + 1) for sig in itertools.combinations(SIGNALS, r) for c in COMBINERS]
    pipeline = next(k for k, c in enumerate(configs) if c == PIPELINE)
    results, alive, stages = {}, list(range(len(configs))), []
    for n in (3, 6, 12):
        t = time.perf_counter()
        for k in set(alive) | {pipeline}:
            for i in range(n):
                if (k, i) not in results:
                    results[(k, i)] = evaluate(configs[k], i)
        mean = {k: np.mean([sum(results[(k, i)]) / 2 for i in range(n)]) for k in alive}
        alive = sorted(alive, key=lambda k: -mean[k])
        stages.append(dict(scenarios=n, combinations=len(alive), seconds=round(time.perf_counter() - t)))
        print(f"{n} scenarios: {len(alive)} combinations in {stages[-1]['seconds']}s", flush=True)
        if n < 12:
            alive = alive[: max(len(alive) // 4, 24)]

    def row(k: int) -> dict:
        c, p = zip(*[results[(k, i)] for i in range(12)])
        cfg = configs[k]
        return dict(legal=cfg["legal"], ngram=f"1–{cfg['ngram']}", training=cfg["train"], combiner=cfg["combiner"],
                    signals=", ".join(cfg["signals"]) or "(the name only)", mean=np.mean([(a + b) / 2 for a, b in zip(c, p)]),
                    worst=min((a + b) / 2 for a, b in zip(c, p)), companies_mean=np.mean(c), companies_worst=min(c),
                    persons_mean=np.mean(p), persons_worst=min(p), k=k)
    final = pd.DataFrame([row(k) for k in set(alive) | {pipeline}]).sort_values("mean", ascending=False, ignore_index=True)
    pct = lambda df: df.assign(**{c: df[c].map(lambda v: f"{v:.1%}") for c in ("mean", "worst", "companies_mean", "companies_worst", "persons_mean", "persons_worst")})
    rank = int(final.index[final.k == pipeline][0]) + 1
    worth = []
    for col, vals in (("legal", list(STD)), ("ngram", ["1–3", "1–4"]), ("training", ["public", "public + the file's legal-form records"]),
                      ("combiner", list(COMBINERS))):
        worth += [dict(idea=f"{col}: {v}", best_mean=f"{final[final[col] == v]['mean'].max():.1%}" if (final[col] == v).any() else "not among the finalists") for v in vals]
    for s in SIGNALS:
        has = final.signals.str.split(", ").map(lambda x: s in x)
        worth += [dict(idea=f"signal {s}: with", best_mean=f"{final[has]['mean'].max():.1%}" if has.any() else "—"),
                  dict(idea=f"signal {s}: without", best_mean=f"{final[~has]['mean'].max():.1%}" if (~has).any() else "—")]

    per = pd.DataFrame([dict(scenario=i + 1, flag_wrong=f"{sc['flag_random']:.0%}", on_representatives=f"{sc['flag_rep']:.0%}",
                             representative_named_companies=f"{sc['rep_share']:.0%}", sole_traders=f"{sc['sole_share']:.0%}",
                             sole_flagged_company=f"{sc['flag_sole']:.0%}", company_dates=f"{sc['company_dates']:.0%} ({sc['company_date']})",
                             companies=f"{results[(pipeline, i)][0]:.1%}", persons=f"{results[(pipeline, i)][1]:.1%}") for i, sc in enumerate(plan)])

    print("sole traders and the lines, for the pipeline's combination", flush=True)
    cfg, policies, placing = configs[pipeline], [], []
    for i in range(12):
        d, hand, rest, logits = scenario(i)
        logits = {k: pd.Series(v, index=d.index) for k, v in logits.items()}
        for policy in ("individuals", "by record (a trade-name record a business)", "businesses (every record)"):
            y = d.y.copy()
            sole = d.case == "sole trader"
            y[sole] = 0 if policy == "individuals" else (d.trade[sole].astype(int) if policy.startswith("by record") else 1)
            p = make(cfg["combiner"]).fit(features(cfg, hand, logits), y[hand.index]).predict_proba(features(cfg, rest, logits))[:, 1]
            policies.append(dict(scenario=i, policy=policy, companies=coverage(p, y[rest.index].to_numpy() == 1, BUDGET_C),
                                 persons=coverage(1 - p, y[rest.index].to_numpy() == 0, BUDGET_P)))
        name_p = 1 / (1 + np.exp(-logits[(cfg["legal"], cfg["ngram"], cfg["train"])]))  # what a run without answers leans to
        for n_ans in (500, 1000, 2000):
            for how in ("random", "stratified (a third at random, a third leaning company, a third leaning person)"):
                if how == "random":
                    ans = d.sample(n_ans, random_state=i)
                else:
                    k, ans = n_ans // 3, d.iloc[:0]
                    for which, size in ((lambda x: x == x, k), (lambda x: x >= 0.9, k), (lambda x: x <= 0.1, n_ans - 2 * k)):
                        pool = d.drop(ans.index)[which(name_p.drop(ans.index))]
                        ans = pd.concat([ans, pool.sample(min(size, len(pool)), random_state=i)])
                X = features(cfg, ans, logits)
                oof = cross_val_predict(make(cfg["combiner"]), X, ans.y, cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")[:, 1]
                scored = d.drop(ans.index)
                p = make(cfg["combiner"]).fit(X, ans.y).predict_proba(features(cfg, scored, logits))[:, 1]
                y = scored.y.to_numpy()
                for margin in (1, 2):
                    lc, lp, _ = lines(oof, ans.y.to_numpy() == 1, replace(KIND, margin_steps=margin))
                    c_calls, p_calls = p >= lc, (1 - p) >= lp
                    placing.append(dict(scenario=i, answers=n_ans, drawn=how, company_rule=f"no error above, then {margin} step{'s' if margin > 1 else ''} stricter",
                                        companies=c_calls[y == 1].mean(), company_wrong=(c_calls & (y == 0)).sum() / max(c_calls.sum(), 1),
                                        persons=p_calls[y == 0].mean(), person_wrong=(p_calls & (y == 1)).sum() / max(p_calls.sum(), 1)))
    pol = pd.DataFrame(policies).groupby("policy", sort=False).agg(companies_mean=("companies", "mean"), companies_worst=("companies", "min"),
                                                                    persons_mean=("persons", "mean"), persons_worst=("persons", "min"))
    pol = pol.map(lambda v: f"{v:.1%}").reset_index()
    pl = pd.DataFrame(placing).groupby(["answers", "drawn", "company_rule"], sort=False).agg(
        companies=("companies", "mean"), company_wrong_worst=("company_wrong", "max"), company_over_budget=("company_wrong", lambda s: int((s > BUDGET_C).sum())),
        persons=("persons", "mean"), person_wrong_worst=("person_wrong", "max"), person_over_budget=("person_wrong", lambda s: int((s > BUDGET_P).sum()))).reset_index()
    for c in ("companies", "company_wrong_worst", "persons", "person_wrong_worst"):
        pl[c] = pl[c].map(lambda v: f"{v:.2%}")

    best = final.iloc[0]
    report = ["# Choosing how to tell persons from companies", "",
              "Written by `scripts/choose_kind.py`. Real company names from `data/reference/registry.json` (training: Miyagi and "
              "Okayama; test: Fukuoka), written the ways bank records write them, and the personas; the truth is the generator's. "
              f"Each scenario: {CUSTOMERS:,} customers. Judged correct first: the share of companies called company while at most "
              f"{BUDGET_C:.1%} of company calls are wrong, and of persons called person while at most {BUDGET_P:.0%} of person calls are "
              "wrong, each line placed with the truth.", "",
              "## The scenarios", "", "What a file can't tell about itself, over its plausible range (a Latin hypercube); and, for the "
              "combination of `config/pipeline.toml` [kind], the shares it decides within budget.", "", markdown(per), "",
              "## The search", "", f"{len(configs):,} combinations, successive halving:", "", markdown(pd.DataFrame(stages)), "",
              f"## The finalists on all 12 scenarios (the best 15 of {len(final)})", "",
              "mean and worst: over the scenarios, of the two sides' shares averaged.", "",
              markdown(pct(final.drop(columns="k").head(15))), "",
              "## What each idea is worth", "", "The best mean among the finalists with the idea, and without it.", "", markdown(pd.DataFrame(worth)), "",
              "## The pipeline's combination", "",
              f"`config/pipeline.toml` [kind]: the bank table, n-grams 1–{KIND.ngram}, trained once on public data, gradient-boosted trees "
              f"of depth {KIND.depth} on the flag, the birth year and the legal form. Rank {rank} of {len(final)}: mean "
              f"{final.loc[rank - 1, 'mean']:.1%} (worst {final.loc[rank - 1, 'worst']:.1%}), against {best['mean']:.1%} for the best "
              f"({best['legal']}, {best['ngram']}, {best['training']}, {best['combiner']}: {best['signals']}).", "",
              "## Counting sole traders", "", "The pipeline's combination, each way of counting them.", "", markdown(pol), "",
              "## Placing the lines from people's answers", "",
              "The pipeline's combination: answers drawn at random or stratified, the combiner fitted on them, the lines placed on "
              "their out-of-fold probabilities (`er.kind.lines`: the company rule as below; the person line where the answers' wrong "
              f"share is at most half of {BUDGET_P:.0%}), then the wrong calls on every other record: the mean share decided, the "
              "worst wrong share, and in how many of the 12 scenarios the wrong share broke its budget.", "", markdown(pl), ""]
    path = S.root / "reports" / "choose_kind.md"
    path.write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))
    print(f"wrote {path} in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()

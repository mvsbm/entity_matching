"""er.fit against Splink 5.0.0's training, as recorded in tests/fixtures/splink-5.0.0.json from the same inputs: λ, each
EM session (the comparisons it holds fixed, where it starts, how many rounds it takes, the m it learns), sessions one
after another, and m from labels. λ, the fixed comparisons, the start and the rounds are equal; m within 1e-12 of
Splink's, whose sums ran in thread order."""
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from er import fit
from er.match import train_fs

from conftest import UID, model

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = json.loads((FIXTURES / "splink-5.0.0.json").read_text(encoding="utf-8"))["fit"]


def ours(engine, case: str) -> dict:
    """er.fit on a recorded case's inputs: its records, the model's settings (u given), λ's rules and recall, and each
    EM session's rule with the columns it holds fixed, in a row."""
    x = RECORDED[case]["inputs"]
    name = f"er_t_fit_{case}"
    engine.register(name, pd.read_parquet(FIXTURES / "splink-5.0.0" / f"{case}.parquet"))
    try:
        lam, trained, sessions = fit.prior(engine, name, x["prior"], x["uid"], x["recall"]), fit.Trained(), []
        for rule in x["rules"]:
            s = fit.session(engine, name, x["settings"], rule["sql"], set(rule["keyed"]), x["uid"], lam, trained)
            trained.add(s.m)
            sessions.append(dict(fixed=s.fixed, start=s.start, rounds=s.rounds, m=s.m))
        return dict(lam=lam, sessions=sessions, model=trained.medians())
    finally:
        engine.unregister(name)


def same_m(ours: dict, recorded: list) -> bool:
    theirs = {(c, lv): v for c, lv, v in recorded}
    return ours.keys() == theirs.keys() and all(math.isclose(ours[k], theirs[k], rel_tol=1e-12, abs_tol=1e-300) for k in ours)


@pytest.mark.parametrize("name", list(RECORDED))
def test_the_fit_is_splink_s(engine, name):
    got, theirs = ours(engine, name), RECORDED[name]["splink"]
    assert got["lam"] == theirs["lam"]
    assert len(got["sessions"]) == len(theirs["sessions"])
    for a, b in zip(got["sessions"], theirs["sessions"]):
        assert (a["fixed"], a["start"], a["rounds"]) == (set(b["fixed"]), b["start"], b["rounds"])
        assert same_m(a["m"], b["m"]), (a["m"], b["m"])
    assert same_m(got["model"], theirs["model"]), (got["model"], theirs["model"])
    learned = [s["m"] for s in got["sessions"]]
    match name:  # what each case is there to show
        case "population":  # the tests' method on a generated population: both its sessions learned
            assert len(learned) == 2 and all(m and s["rounds"] > 1 for m, s in zip(learned, got["sessions"]))
        case "never_reached":  # a level after JW ≥ 0.9 at 0.95: no pair reaches it, and it is left unlearned
            assert ("name", "never") not in learned[0]


def test_a_fit_repeats_to_the_last_bit(engine, records):
    m = model()
    first, again = (train_fs(m, records, engine, UID) for _ in range(2))
    assert first == again


def test_prior_rules_that_find_more_pairs_than_their_recall_allows_stop_the_fit(engine):
    from er.config import InputError
    engine.register("er_t_same", pd.DataFrame({UID: ["a", "b", "c"], "phone": ["1", "1", "1"]}))  # every pair shares the phone
    try:
        assert fit.prior(engine, "er_t_same", ['l."phone" = r."phone"'], UID, 1.0) == 1.0
        with pytest.raises(InputError, match="more than a recall of 0.5 allows"):
            fit.prior(engine, "er_t_same", ['l."phone" = r."phone"'], UID, 0.5)
    finally:
        engine.unregister("er_t_same")

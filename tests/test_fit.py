"""er.fit against Splink 5.0's training, the fit it replaces: λ, each EM session (the comparisons it holds fixed, where
it starts, how many rounds it takes, the m it learns), sessions one after another, and m from labels. λ, the fixed
comparisons, the start and the rounds are equal; m within 1e-12 of Splink's, whose sums run in thread order."""
import logging
import math
from dataclasses import replace

import pandas as pd
import pytest
import splink.internals.expectation_maximisation as splink_em
from splink import DuckDBAPI, Linker
from splink.internals.comparison_level import M_U_CLAMP_MIN
from splink.internals.constants import LEVEL_NOT_OBSERVED_TEXT

from er import fit
from er.config import keys_sql
from er.match import keyed, model_dict, narrowed, read_by, rule_pairs, train_fs

from conftest import UID, model

SPLINK_STEP = splink_em.populate_m_u_from_lookup


def unseen_when_zero(fixed, level, name, lookup):  # the rule train_fs held Splink's EM step to: an m it can't hold, or NaN, is a level not seen
    got = lookup.get(name, {}).get(level.comparison_vector_value)
    if got and isinstance(got.get("m_probability"), float) and not got["m_probability"] >= M_U_CLAMP_MIN:
        got["m_probability"] = LEVEL_NOT_OBSERVED_TEXT
    SPLINK_STEP(fixed, level, name, lookup)


def both(con, frame: pd.DataFrame, m, uid: str = UID, labels: str | None = None) -> tuple[dict, dict]:
    """The fit of `frame` under model m by Splink 5.0 and by er.fit, from the same u (train_fs's) and the same records:
    λ, each of m's EM sessions in a row (from em_rules), and the model's m (with labels: m from them instead)."""
    u = {c["output_column_name"]: {lv["label_for_charts"]: lv["u_probability"] for lv in c["comparison_levels"] if not lv.get("is_null_level")}
         for c in train_fs(replace(m, m_method="em"), frame.drop(columns=[labels] if labels else []), con, uid)["comparisons"]}
    settings = model_dict(m, uid, u)
    prior = [keys_sql(r) for r in m.prior_rules if rule_pairs(frame, r)]
    rules = [r for r in m.em_rules if rule_pairs(frame, r)] if not labels else []
    with narrowed(frame, con, read_by(settings, *prior, *(keys_sql(r) for r in rules)) | {uid, *([labels] if labels else [])}) as records:
        linker = Linker(DuckDBAPI(connection=con).register(records), settings, log_level=logging.ERROR, validate_settings=False)
        linker.training.estimate_probability_two_random_records_match(prior, recall=m.prior_recall)
        theirs = dict(lam=linker._settings_obj._probability_two_random_records_match, sessions=[])
        for r in rules:  # the rule naming the columns it holds fixed, as train_fs told Splink
            also = "".join(f' AND l."{x}" IS NOT DISTINCT FROM l."{x}"' for x in sorted(keyed(m, r) - {k.name for k in r}))
            s = linker.training.estimate_parameters_using_expectation_maximisation(keys_sql(r) + also, estimate_without_term_frequencies=True)
            theirs["sessions"].append(dict(fixed={c.output_column_name for c in s._comparisons_that_cannot_be_estimated},
                                           start=s._core_model_settings_history[0].probability_two_random_records_match,
                                           rounds=len(s._core_model_settings_history) - 1,
                                           m={(c.output_column_name, lv.label_for_charts): lv._m_probability for c in s.core_model_settings.comparisons
                                              for lv in c.comparison_levels if not lv.is_null_level and isinstance(lv._m_probability, float)}))
        if labels:
            linker.training.estimate_m_from_label_column(labels)
        theirs["model"] = {(c["output_column_name"], lv["label_for_charts"]): lv["m_probability"] for c in linker.misc.save_model_to_json()["comparisons"]
                           for lv in c["comparison_levels"] if "m_probability" in lv}
        linker.table_management.invalidate_cache()

        lam, trained, sessions = fit.prior(con, records, prior, uid, m.prior_recall), fit.Trained(), []
        for r in rules:
            s = fit.session(con, records, settings, keys_sql(r), keyed(m, r), uid, lam, trained)
            trained.add(s.m)
            sessions.append(dict(fixed=s.fixed, start=s.start, rounds=s.rounds, m=s.m))
        if labels:
            trained.add(fit.m_from_labels(con, records, settings, labels, uid))
        ours = dict(lam=lam, sessions=sessions, model=trained.medians())
    return ours, theirs


def same_m(ours: dict, theirs: dict) -> bool:
    return ours.keys() == theirs.keys() and all(math.isclose(ours[k], theirs[k], rel_tol=1e-12, abs_tol=1e-300) for k in ours)


def assert_same_fit(ours: dict, theirs: dict) -> None:
    assert ours["lam"] == theirs["lam"]
    assert len(ours["sessions"]) == len(theirs["sessions"])
    for a, b in zip(ours["sessions"], theirs["sessions"]):
        assert (a["fixed"], a["start"], a["rounds"]) == (b["fixed"], b["start"], b["rounds"])
        assert same_m(a["m"], b["m"]), (a["m"], b["m"])
    assert same_m(ours["model"], theirs["model"]), (ours["model"], theirs["model"])


@pytest.fixture
def splink_held_to_unseen(monkeypatch):
    monkeypatch.setattr(splink_em, "populate_m_u_from_lookup", unseen_when_zero)


def test_the_method_s_fit_on_a_population_is_splink_s(tmp_path, population, splink_held_to_unseen):
    from er.match import fit_model, fit_sample_sql
    from er.run import Run
    s, p, g = population
    run = Run(p, s)
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    run.load(tmp_path / "in.parquet")
    m = fit_model(p.fs)
    sample = run.con.execute(f"{fit_sample_sql([m], run.uid, run.columns())} LIMIT {p.fit_rows}").df().astype("string")  # the fit's own sample
    ours, theirs = both(run.con, sample, m, run.uid)
    assert len(ours["sessions"]) == 2 and all(x["m"] and x["rounds"] > 1 for x in ours["sessions"])  # both sessions learned
    assert_same_fit(ours, theirs)


def test_a_level_no_pair_reaches_is_left_unlearned_as_splink_leaves_it(con, records, splink_held_to_unseen):
    from er.config import Comparator, Level
    m = model(extra_name_levels=(Level(label="never", any_of=(("name", Comparator("jaro_winkler", 0.95)),)),))  # after JW ≥ 0.9: never reached
    ours, theirs = both(con, records, m)
    assert ("name", "never") not in ours["sessions"][0]["m"]
    assert_same_fit(ours, theirs)


def test_one_record_copied_many_times_fits_as_splink_fits_it(con, records, splink_held_to_unseen):
    copies = pd.concat([records] + [records.iloc[[0]].assign(**{UID: f"copy{i}"}) for i in range(80)], ignore_index=True)
    ours, theirs = both(con, copies, model())
    assert_same_fit(ours, theirs)


def test_m_from_labels_is_splink_s(con, records, splink_held_to_unseen):
    ours, theirs = both(con, records.assign(__label__=records["entity"]), model("labels"), labels="__label__")
    assert ours["model"] and not ours["sessions"]
    assert_same_fit(ours, theirs)


def test_a_fit_repeats_to_the_last_bit(con, records):
    m = model()
    first, again = (train_fs(m, records, con, UID) for _ in range(2))
    assert first == again


def test_prior_rules_that_find_more_pairs_than_their_recall_allows_stop_the_fit(con):
    from er.config import InputError
    con.register("er_t_same", pd.DataFrame({UID: ["a", "b", "c"], "phone": ["1", "1", "1"]}))  # every pair shares the phone
    try:
        assert fit.prior(con, "er_t_same", ['l."phone" = r."phone"'], UID, 1.0) == 1.0
        with pytest.raises(InputError, match="more than a recall of 0.5 allows"):
            fit.prior(con, "er_t_same", ['l."phone" = r."phone"'], UID, 0.5)
    finally:
        con.unregister("er_t_same")

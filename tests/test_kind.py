"""Person or company: the name model, the kind problems, people's answers."""
import json
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from er.config import (InputError)
from er.config import legal_pattern, load_pipeline
from er.settings import load_settings
from er.standardize import normalize



@pytest.fixture(scope="module")
def kind_population():
    """A small population with one name column for every kind, a person/company flag that is sometimes wrong, companies
    under their representative's name and sole traders; the settings that read it; the final pipeline."""
    from er.generate import KindProblems, generate as make, kind_problems, load_reference, load_registry, load_spec
    from er.settings import shared_name
    base = load_settings()
    spec = replace(load_spec(base.root / "config" / "generator.toml")[0], entities=1_500)
    ref, std = load_reference(base.paths["reference"]), base.standardize
    g = kind_problems(make(spec, *ref), KindProblems(), load_registry(base.paths["reference"]), std.legal_front, std.legal_end,
                      spec.kana_confusions, spec.branches)
    s = shared_name(base, "NAME_KANA")
    return s, load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns), g


def kind_sheet_for(run, s, p, draw):  # the run's review sheet, as Run.report writes it, with a smaller draw
    from er.kind import kind_review_sheet
    return kind_review_sheet(run.con, "records", s.data.unique_id, replace(p.kind, labels_to_draw=draw, review_max=200), s.flag_company)


def test_the_name_model_saves_and_loads_to_the_same_scores(tmp_path):
    from er.kind import NameModel
    texts = pd.Series(["ヤマダタロウ", "スズキハナコ", "ヤマダシヨウテン", "トヨタシトウシヤ", "サトウイチロウ", "ミツヒシシヨウシ"] * 3, dtype="string")
    m = NameModel.fit(texts, np.array([0, 0, 1, 1, 0, 1] * 3), ngram=3)
    m.save(tmp_path / "m.npz", "k")
    probe = pd.Series(["ヤマダハナコ", pd.NA, "スズキシヨウテン"], dtype="string")
    back = NameModel.load(tmp_path / "m.npz", "k")
    assert np.allclose(m.logit(probe), back.logit(probe), equal_nan=True) and np.isnan(back.logit(probe)[1])
    assert NameModel.load(tmp_path / "m.npz", "another key") is None  # a model trained under other settings isn't loaded


def test_a_run_loads_the_committed_name_model_and_it_is_what_training_builds():
    """config/kind_names.npz is what scripts/train_name_model.py builds from today's reference data, generator settings
    and code; a run refuses one trained under its other settings."""
    from er.generate import train_name_model
    from er.kind import name_model
    s = load_settings()
    spec = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns).kind
    kept, fresh = name_model(s, spec), train_name_model(s, spec)
    assert kept.terms == fresh.terms and np.allclose(kept.coef, fresh.coef, rtol=0, atol=1e-3) and abs(kept.intercept - fresh.intercept) < 1e-3, \
        "the training changed: run scripts/train_name_model.py and commit config/kind_names.npz"
    other = replace(s, standardize=replace(s.standardize, legal_forms=s.standardize.legal_forms[1:]))
    with pytest.raises(InputError, match="trained under other settings") as stop:
        name_model(other, spec)
    assert "train_name_model.py" in stop.value.fix


def test_each_side_s_line_keeps_within_its_labels():
    from er.config import KindSpec
    from er.kind import lines
    p = np.r_[np.full(50, 0.999), [0.97], np.full(300, 0.01), [0.03]]  # 50 companies, a person at 0.97, 300 persons, a company at 0.03
    company = np.r_[np.ones(50, bool), [False], np.zeros(300, bool), [True]]
    line_c, line_p, error = lines(p, company, KindSpec(margin_steps=1, labels_to_draw=len(p)))
    assert line_c == 0.99   # the lowest line with no person above it is 0.98; one step stricter
    assert lines(p, company, KindSpec(margin_steps=1, labels_to_draw=len(p) + 1))[0] == 0.995  # fewer answers than the draw: one more
    assert (line_p, error) == (0.98, 0.0)  # 300 right: the rate's 95% bound is 0.99%; at 0.95, 1 wrong in 301 bounds it at 1.6%
    few = np.r_[np.full(40, 0.01), np.full(10, 0.999)]  # 40 persons, none wrong: the bound is still 7.2%
    assert lines(few, np.r_[np.zeros(40, bool), np.ones(10, bool)], KindSpec())[1] == 1.01


def test_the_kind_problems_change_names_dates_and_the_flag_only(kind_population):
    from er.generate import generate as make, load_reference, load_spec
    s, p, g = kind_population
    made = make(replace(load_spec(s.root / "config" / "generator.toml")[0], entities=1_500), *load_reference(s.paths["reference"])).df
    assert {"NAME_KANA", "PERSON_ORG_CODE"} <= set(g.df.columns) and "FULL_NAME_KANA" not in g.df.columns
    assert g.df[["CONT_ID", "CIF_ID"]].equals(made[["CONT_ID", "CIF_ID"]])  # the records start as generate() made them
    stay = g.truth["KIND"].eq("person").to_numpy()  # only a company moves: to its representative's address and phone
    assert g.df.loc[stay, ["PHONE_NUM_4", "STD_ADDRESS"]].equals(made.loc[stay, ["PHONE_NUM_4", "STD_ADDRESS"]])
    assert set(g.truth["CASE"]) == {"company", "person", "representative", "sole trader"}
    flag_company = g.df["PERSON_ORG_CODE"] == "2"
    assert 0.02 < (flag_company != g.truth["KIND"].eq("company")).mean() < 0.1  # the flag is wrong, now and then


def test_without_answers_the_engine_calls_what_it_is_sure_of_the_flag_the_rest_and_a_person_company_pair_goes_to_people(tmp_path, kind_population):
    from er.report import qa
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    home = g.df[g.df[["NAME_KANA", "PHONE_NUM_4", "SOURCE_ADDR_CD", "STD_ADDRESS"]].notna().all(axis=1) & g.truth["CASE"].eq("person").to_numpy()].iloc[0]
    firm = home.copy()
    firm[["CIF_ID", "BIRTH_DATE"]] = pd.NA
    firm[[uid, "NAME_KANA", "PERSON_ORG_CODE"]] = ["9" * len(home[uid]), "カブシキガイシャテスト", "2"]
    pd.concat([g.df, firm.to_frame().T.astype(g.df.dtypes)], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(replace(p, fs=replace(p.fs, min_match_weight=4.0)), s).full(tmp_path / "all.parquet", tmp_path / "run")
    rec = run.con.sql(f'SELECT "{uid}", person_name, company_name, kind, name_p, kind_flag, kind_flagged FROM records').df().set_index(uid)
    assert rec.loc[firm[uid], "kind"] == 2 and pd.isna(rec.loc[firm[uid], "person_name"]) and rec.loc[firm[uid], "company_name"] == "カブシキガイシャテスト"
    assert pd.notna(rec.loc[home[uid], "person_name"]) and pd.isna(rec.loc[home[uid], "company_name"])
    named = rec[rec.index.isin(g.df[uid])].join(g.df.set_index(uid)["NAME_KANA"])
    written = named["NAME_KANA"].str.normalize("NFKC").str.replace("[ 　]", "", regex=True).str.contains(legal_pattern(s.standardize))
    line = p.kind.name_line
    sure = np.where(written.fillna(False) | (named["name_p"] >= line), 2, np.where(named["name_p"] <= 1 - line, 1, 0))
    flag = np.where(named["kind_flag"].isna(), 0, np.where(named["kind_flag"].isin(s.flag_company), 2, 1))
    assert (named["kind"].to_numpy() == np.where(sure > 0, sure, flag)).all() and set(named["kind"]) == {1, 2}  # a legal form or a sure name; else the flag
    assert (named["kind_flagged"].to_numpy() == ((sure > 0) & (flag > 0) & (sure != flag))).all() and named["kind_flagged"].any()  # sure against the flag
    pair = (home[uid], firm[uid])
    assert run.con.execute(f'SELECT count(*) FROM matches WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0] == 0
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    assert sheet[(sheet[l] == pair[0]) & (sheet[r] == pair[1])]["why"].tolist() == ["decide"]


def test_the_review_sheet_says_in_words_why_each_record_is_there(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a"), s, p, 300)
    assert set(sheet["why"]) == {"decide", "measure"} and sheet[uid].is_unique and sheet["kind"].isna().all()
    decide = sheet[sheet["why"] == "decide"]
    assert len(decide) <= 200 and (decide["reason"].str.contains("the flag says")).all()
    assert decide["reason"].str.startswith("the engine is sure it is").all() and decide["reason"].str.endswith("matched as the engine says").all()
    assert set(sheet["engine_says"]) <= {"2 company", "1 person", "0 not sure"} and sheet["name_says"].str.match(r"[12] (company|person) \(").all()
    measure = sheet[sheet["why"] == "measure"]
    assert len(measure) == 300 and set(measure["drawn"]) == {"at random"} and measure[~measure["flagged"]]["reason"].str.startswith("drawn at random").all()
    assert measure[measure["flagged"]]["reason"].str.startswith("the engine is sure").all()  # a flagged record drawn: said as flagged
    flags = g.df.set_index(uid).loc[decide[uid], "PERSON_ORG_CODE"].astype(int).to_numpy()
    assert len(decide) and (decide["engine"].to_numpy() != flags).all()  # flagged: the engine's sure kind against the flag
    surest = (decide["engine_p"] - 0.5).abs().to_numpy()
    assert (surest[:-1] >= surest[1:]).all()  # surest first


def test_with_answers_the_kinds_are_the_same_every_run_people_s_stand_and_a_customer_takes_its_surest_record(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a"), s, p, 900)
    sheet["kind"] = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)  # people's answers: here, the truth
    sheet.loc[sheet.index[:3], "kind"] = 0  # can't tell: kept out
    sheet.to_parquet(tmp_path / "labels.parquet")
    a = Run(p, s, kind_labels=tmp_path / "labels.parquet").full(tmp_path / "all.parquet", tmp_path / "b")
    Run(p, s, kind_labels=tmp_path / "labels.parquet").full(tmp_path / "all.parquet", tmp_path / "c")
    ga, gb = (pd.read_parquet(tmp_path / x / "gold.parquet") for x in ("b", "c"))
    assert a.classifier.labels == len(sheet) - 3 and a.classifier.measured == (sheet["why"] == "measure").sum() - (sheet["why"][:3] == "measure").sum()
    assert ga[["kind", "kind_p", "kind_by", "customer_kind"]].equals(gb[["kind", "kind_p", "kind_by", "customer_kind"]])
    answered = ga.set_index(uid).loc[sheet[uid][3:]]
    assert (answered["kind_by"] == "people").all() and (answered["kind"].to_numpy() == sheet["kind"][3:].to_numpy()).all()  # people's answers stand
    assert len(pd.read_parquet(tmp_path / "b" / "kind_answers" / "part-00000.parquet")) == len(sheet)  # kept as given, for later runs
    inputs = json.loads((tmp_path / "b" / "steps.json").read_text(encoding="utf-8"))["runs"][0]["inputs"]
    assert {Path(i["file"]).name for i in inputs} == {"all.parquet", "kind_names.npz", "labels.parquet"}  # what went in, with its SHA-256
    by = ga.groupby("cluster_id").agg(any_company=("kind", lambda k: (k == 2).any()), leans=("kind_p", "max"),
                                      any_person=("kind", lambda k: (k == 1).any()), customer=("customer_kind", "first"))
    expect = np.where(by.any_company, 2, np.where((by.leans.fillna(0) < 0.5) & by.any_person, 1, 0))
    assert (by.customer.to_numpy() == expect).all()
    wrong = ga.set_index(uid).join(g.truth.set_index("CONT_ID")["KIND"])
    sure = (wrong["kind_by"] == "engine") & (wrong["kind_p"] >= a.classifier.fitted.line_company)
    assert not (sure & (wrong["KIND"] != "company")).any()  # no sure company that isn't one: a wrong one is the flag's


def test_answers_without_a_measuring_draw_keep_the_engine_s_own_rule(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 600)
    decide = np.arange(len(sheet)) < 60  # the first rows people chose to answer, none of them drawn to measure
    truth = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)
    sheet.assign(why="decide", kind=pd.array(np.where(decide, truth, pd.NA), dtype="Int8")).to_parquet(tmp_path / "top.parquet")
    run = Run(p, s, kind_labels=tmp_path / "top.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    assert run.classifier.labels == decide.sum() >= 50 and run.classifier.measured == 0 and run.classifier.fitted is None
    before, after = (pd.read_parquet(tmp_path / x / "gold.parquet").set_index(uid) for x in ("free", "run"))
    engine = after.index[after["kind_by"] == "engine"]
    assert (before.loc[engine, "kind"] == 2).any() and after.loc[engine, "kind"].equals(before.loc[engine, "kind"])  # a legal form still decides
    assert (after.loc[sheet[uid][decide], "kind"].to_numpy() == truth[decide]).all()  # and people's answers stand


def test_results_count_the_flagged_and_a_gold_written_before_flags_still_reads(tmp_path, kind_population):
    from er.kind import sheet_parts
    from er.results import describe_merging, describe_results
    from er.run import Run
    from er.strings import connect
    s, p, g = kind_population
    out = tmp_path / "run"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    Run(p, s).full(tmp_path / "all.parquet", out, pipeline_file=s.root / "config" / "final.toml")
    con, db = connect(s.compute)
    gold, sheet = pd.read_parquet(out / "gold.parquet"), pd.read_parquet(out / "kind_review.parquet")
    k, part = describe_results(con, db, out, s, p)["kinds"], sheet_parts(sheet)
    assert k == dict(flagged=int(gold["kind_flagged"].sum()), to_check=int((part == "decide").sum()), to_teach=int((part == "measure").sum()))
    assert k["flagged"] and int(sheet["flagged"].sum()) == k["to_check"]  # every flagged record on the sheet is to check, drawn at random or not
    gold.drop(columns="kind_flagged").to_parquet(out / "gold.parquet")  # as a run written before flags left it
    assert describe_merging(con, db, out, s, p, {"when": [{"points": 12}]})["pairs"] >= 0  # it still reads: none of its records flagged


def test_a_sheet_s_ids_must_name_records_of_the_file(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 100).assign(kind=1)
    sheet.assign(**{uid: sheet[uid].astype("int64")}).to_parquet(tmp_path / "numbers.parquet")  # as a spreadsheet gives 0000000151 back
    with pytest.raises(InputError, match="IDs that name no record of"):  # as for decisions
        Run(p, s, kind_labels=tmp_path / "numbers.parquet").full(tmp_path / "all.parquet", tmp_path / "a")
    sheet.assign(**{uid: [pd.NA, *sheet[uid][1:]]}).astype({uid: "string"}).to_parquet(tmp_path / "blank.parquet")
    with pytest.raises(InputError, match="answered rows have no"):
        Run(p, s, kind_labels=tmp_path / "blank.parquet").full(tmp_path / "all.parquet", tmp_path / "b")


def test_a_new_part_takes_the_number_after_the_highest(tmp_path):
    from er.folder import next_part
    assert next_part(tmp_path) == 0
    (tmp_path / "part-00001.parquet").touch()  # part-00000 deleted by hand: undone
    assert next_part(tmp_path) == 2


def test_the_field_check_and_the_run_read_one_legal_form_table():
    import duckdb
    s = load_settings()
    names = ["イ)ヤマダクリニック", "ヤマダショウジ(カ", "トクヒ)ミライノカイ", "カブシキガイシヤヤマダ", "カ)ヤマダ", "ヤマダ(カ)", "株式会社ヤマダ", "ヤマダ㈱", "（有）ヤマダ商店"]
    folded = normalize(pd.Series(names, dtype="string"), ("nfkc", "strip_spaces"), s.standardize)  # as the field holds them
    pattern = s.detect["company_name"].replace("'", "''")
    assert all(duckdb.sql(f"SELECT regexp_matches('{n}', '{pattern}')").fetchall()[0][0] for n in folded)  # every one looks right
    assert normalize(pd.Series(names[6:], dtype="string"), ("nfkc", "strip_legal_form"), s.standardize).tolist() == ["ヤマダ", "ヤマダ", "ヤマダ商店"]


def test_a_name_in_hiragana_reads_as_the_same_name_in_katakana():  # as the name fields read it
    from er.kind import legal, text
    std = load_settings().standardize
    hira, kata = pd.Series(["かぶしきがいしゃ やまだしょうてん", "やまだ たろう"]), pd.Series(["カブシキガイシャ ヤマダショウテン", "ヤマダ タロウ"])
    assert legal(hira, std).tolist() == legal(kata, std).tolist() == [True, False]
    assert text(hira, std).tolist() == text(kata, std).tolist()


def test_a_decision_keeps_each_record_s_kind_and_a_merged_customer_takes_its_surest(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    before = pd.read_parquet(tmp_path / "run" / "gold.parquet")
    alone = before.groupby("cluster_id").filter(lambda c: len(c) == 1)
    company, other = alone[alone["kind"] == 2].iloc[0], alone[alone["kind"] == 0].iloc[0]  # a sure company, a record not sure
    pair = sorted([company[uid], other[uid]])
    pd.DataFrame({f"{uid}_l": [pair[0]], f"{uid}_r": [pair[1]], "decision": ["match"]}).to_parquet(tmp_path / "decided.parquet")
    Run(p, s).decide(tmp_path / "decided.parquet", tmp_path / "run")
    after = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert list(after.reset_index().columns) == list(before.columns)
    assert after.loc[pair, "cluster_id"].nunique() == 1 and (after.loc[pair, "customer_kind"] == 2).all()
    assert after["kind"].equals(before.set_index(uid)["kind"].reindex(after.index))  # each record's kind stands


def test_answers_add_up_over_sheets_each_kept_as_given_and_a_blank_row_erases_nothing(tmp_path, kind_population):
    import shutil
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 600)
    truth = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)
    half = len(sheet) // 2
    first = sheet.assign(kind=pd.array([*truth[:half], *[pd.NA] * (len(sheet) - half)], dtype="Int8"))  # the second half left blank
    first.to_parquet(tmp_path / "first.parquet")
    run1 = Run(p, s, kind_labels=tmp_path / "first.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    assert set(run1.labels[uid]) == set(sheet[uid][:half])  # a blank row isn't an answer: its record comes back on the next sheet
    second = sheet.assign(kind=pd.array([pd.NA] * half + list(truth[half:]), dtype="Int8"))  # the first half blank this time
    second.to_parquet(tmp_path / "second.parquet")
    run2 = Run(p, s, kind_labels=tmp_path / "second.parquet").full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    answers = tmp_path / "run" / "kind_answers"
    parts = sorted(answers.glob("part-*.parquet"))
    assert [set(pd.read_parquet(f)[uid]) for f in parts] == [set(sheet[uid][:half]), set(sheet[uid][half:])]  # a part per sheet, its filled rows
    assert len(run2.classifier.decided) == len(sheet)  # both sheets' answers stand
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid).loc[sheet[uid]]
    assert (gold["kind_by"] == "people").all() and (gold["kind"].to_numpy() == truth).all()

    parts[1].unlink()  # a sheet answered wrong: deleting its part undoes it
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run", overwrite=True)
    assert set(pd.read_parquet(answers)[uid]) == set(sheet[uid][:half])
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert not (gold.loc[sheet[uid][half:], "kind_by"] == "people").any()

    from er import folder
    from er.cli import main
    shutil.move(parts[0], tmp_path / "run" / "state" / "kind_labels.parquet")  # answers where an earlier nayose kept them: refused, never half read
    assert main(["list", "pairs", "--workspace", str(tmp_path / "run"), "--format", "json"]) == 2
    with pytest.raises(InputError, match="an earlier nayose wrote .people's answers in state/"):
        folder.current(tmp_path / "run")
    old = tmp_path / "old"
    (old / "inputs" / "0001-theirs").mkdir(parents=True)  # a part the reader never described
    with pytest.raises(InputError, match="0001-theirs read before the reader described its files"):
        folder.current(old)
    (old / "inputs" / "0001-theirs").rmdir()
    (old / "rule_kept").mkdir()
    pd.DataFrame({f"{uid}_l": ["1"], f"{uid}_r": ["2"], "rule": ["X1"]}).to_parquet(old / "rule_kept" / "part-00000.parquet")  # rules' pairs without merged
    with pytest.raises(InputError, match="don't say whether they merged"):
        folder.current(old)
    folder.current(old, replacing=True)  # a full run --overwrite writes them anew: let through


def test_a_record_people_can_t_tell_stays_out_of_name_matching_and_off_the_next_sheet(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "all.parquet", tmp_path / "free"), s, p, 600)
    first = sheet[uid].iloc[0]
    sheet.assign(kind=pd.array([0] + [pd.NA] * (len(sheet) - 1), dtype="Int8")).to_parquet(tmp_path / "answers.parquet")
    run = Run(p, s, kind_labels=tmp_path / "answers.parquet").full(tmp_path / "all.parquet", tmp_path / "run")
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert gold.loc[first, ["kind", "kind_by"]].tolist() == [0, "people"] and gold.loc[first, "kind_held"]
    names = run.con.execute(f'SELECT person_name, company_name FROM records WHERE "{uid}" = ?', [first]).fetchall()[0]
    assert names == (None, None)  # its name goes to neither side: its pairs go to people
    assert first not in set(kind_sheet_for(run, s, p, 600)[uid])


def test_an_increment_classifies_its_batch_on_the_run_s_answers(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    batch = np.random.default_rng(0).random(len(g.df)) < 0.1
    g.df[~batch].to_parquet(tmp_path / "first.parquet", index=False)
    g.df[batch].to_parquet(tmp_path / "new.parquet", index=False)
    sheet = kind_sheet_for(Run(p, s).full(tmp_path / "first.parquet", tmp_path / "free"), s, p, 600)
    sheet["kind"] = np.where(g.truth.set_index("CONT_ID").loc[sheet[uid], "KIND"].eq("company"), 2, 1)
    sheet.to_parquet(tmp_path / "answers.parquet")
    full = Run(p, s, kind_labels=tmp_path / "answers.parquet").full(tmp_path / "first.parquet", tmp_path / "run")
    inc = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "run")
    assert inc.classifier.labels == full.classifier.labels > 0 and inc.classifier.fitted.line_company == full.classifier.fitted.line_company
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)
    assert (gold.loc[sheet[uid], "kind_by"] == "people").all()  # the stored records' answers stand
    new = gold.loc[g.df.loc[batch, uid]]
    assert new["kind"].notna().all() and set(new["kind_by"]) == {"engine", "flag"}  # the batch: the same engine's calls, the flag's where it isn't sure


def test_the_kind_problems_are_the_same_in_every_process(tmp_path):
    import subprocess
    import sys
    code = """import sys
from dataclasses import replace
from er.generate import KindProblems, generate, kind_problems, load_reference, load_registry, load_spec
from er.settings import load_settings
s = load_settings()
spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=400)
g = kind_problems(generate(spec, *load_reference(s.paths["reference"])), KindProblems(representatives=0.5), load_registry(s.paths["reference"]),
                  s.standardize.legal_front, s.standardize.legal_end, spec.kana_confusions, spec.branches)
g.df.to_parquet(sys.argv[1], index=False)"""
    for seed in ("1", "2"):  # Python hashes strings differently in every process: nothing may depend on it
        subprocess.run([sys.executable, "-c", code, str(tmp_path / f"{seed}.parquet")], check=True, env={**__import__("os").environ, "PYTHONHASHSEED": seed})
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "1.parquet"), pd.read_parquet(tmp_path / "2.parquet"))


def test_the_kind_problems_name_no_company_the_name_model_trains_on():
    from er.generate import KindProblems, generate as make, kind_problems, load_reference, load_spec, name_model_split
    s = load_settings()
    spec = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=600)
    registry = pd.DataFrame({"reading": ["ヰヱヰヱ", "アオイ"], "legal": ["カブシキガイシャ"] * 2, "abbreviation": ["カ"] * 2,
                             "front": [True] * 2, "prefecture": ["04", "40"]}).astype(object)  # a training company, a held-out one
    g = kind_problems(make(spec, *load_reference(s.paths["reference"])), KindProblems(), registry, s.standardize.legal_front,
                      s.standardize.legal_end, spec.kana_confusions, spec.branches)
    names = g.df.loc[g.truth["CASE"].eq("company").to_numpy(), "NAME_KANA"].dropna()
    assert len(names) and not names.str.contains("ヰ").any()  # only the held-out company is ever written
    _, _, train, held = name_model_split(load_reference(s.paths["reference"])[0], registry)
    assert set(train["reading"]) == {"ヰヱヰヱ"} and set(held["reading"]) == {"アオイ"}


def test_a_birth_year_reads_from_four_digits_or_two_by_this_year(monkeypatch):
    import datetime
    from er import kind
    from er.kind import birth_year
    got = birth_year(pd.Series(["1993-05-25", "19930525", "1993/05/25", "1993/5/2", "199305", "93-05-25", "930525", "25/05/1993", "05-01-02", None, "abc",
                                "H05.05.25"], dtype="string"))
    assert got[:9].tolist() == [1993] * 8 + [2005] and np.isnan(got[9:]).all()  # an era's year: none
    for year, read in ((2026, 1927), (2027, 2027)):  # 27: a year to come in 2026, this year in 2027
        monkeypatch.setattr(kind, "date", type("D", (), {"today": staticmethod(lambda y=year: datetime.date(y, 1, 1))}))
        assert birth_year(pd.Series(["27-03-15", "270315", "26-03-15"], dtype="string")).tolist() == [read, read, 2026]


def test_answers_of_ids_and_kinds_alone_stand_and_train_nothing():
    from er.kind import COMPANY, PERSON, classifier
    s = load_settings()
    labels = pd.DataFrame({s.data.unique_id: [str(i) for i in range(60)], "kind": [PERSON, COMPANY] * 30})  # as answers() takes a file: no name
    c = classifier(s, load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns).kind, labels)
    assert c.decided["0"] == PERSON and c.fitted is None  # each stands for its record; with no name, nothing to learn from

"""Person or company: the name model, the kind problems, the engine's rule."""
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


def test_a_flag_reads_its_spaces_and_width_aside():
    from types import SimpleNamespace
    from er.kind import Classifier
    flag = pd.Series(["2", "2 ", " 2", "２", "1", None, "12"], dtype="string")  # a fixed-width export pads its fields
    assert Classifier.flag_code(SimpleNamespace(flag_company=("2",)), flag, len(flag)).tolist()[:5] == [2, 2, 2, 2, 1]
    assert np.isnan(Classifier.flag_code(SimpleNamespace(flag_company=("2",)), flag, len(flag))[5])


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


def test_the_engine_calls_what_it_is_sure_of_the_flag_the_rest_and_a_person_company_pair_goes_to_people(tmp_path, kind_population):
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
    person_under_company = (sure == 1) & (flag == 2)  # a company's records under its representative's name read so
    assert person_under_company.any() and (named["kind"].to_numpy()[person_under_company] == 2).all()  # the company flag stands
    sure = np.where(person_under_company, 0, sure)
    assert (named["kind"].to_numpy() == np.where(sure > 0, sure, flag)).all() and set(named["kind"]) == {1, 2}  # a legal form or a sure name; else the flag
    assert (named["kind_flagged"].to_numpy() == ((sure > 0) & (flag > 0) & (sure != flag))).all() and named["kind_flagged"].any()  # sure against the flag
    pair = (home[uid], firm[uid])
    assert run.con.execute(f'SELECT count(*) FROM matches WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0] == 0
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    assert sheet[(sheet[l] == pair[0]) & (sheet[r] == pair[1])]["why"].tolist() == ["decide"]


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


def test_an_increment_tells_its_batch_s_kinds_as_a_full_run_does(tmp_path, kind_population):
    from er.run import Run
    s, p, g = kind_population
    uid = s.data.unique_id
    batch = np.random.default_rng(0).random(len(g.df)) < 0.1
    g.df[~batch].to_parquet(tmp_path / "first.parquet", index=False)
    g.df[batch].to_parquet(tmp_path / "new.parquet", index=False)
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    Run(p, s).full(tmp_path / "first.parquet", tmp_path / "run")
    Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "run")
    Run(p, s).full(tmp_path / "all.parquet", tmp_path / "whole")
    inc, whole = (pd.read_parquet(tmp_path / w / "gold.parquet").set_index(uid).loc[g.df.loc[batch, uid], ["kind", "kind_p", "kind_by", "kind_flagged"]]
                  for w in ("run", "whole"))
    assert inc.equals(whole) and set(inc["kind_by"]) == {"engine", "flag"}  # one rule, whichever run tells it


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


def test_a_pipeline_or_a_workspace_holding_what_no_run_reads_of_kind_is_refused(tmp_path):
    from er import folder
    from er.config import kind_spec
    with pytest.raises(InputError, match="depth, review_max set nothing") as stop:  # a combiner's and a review sheet's settings
        kind_spec({"name_field": "any_name", "depth": 2, "review_max": 1000})
    assert stop.value.fix == "delete depth, review_max from [kind]"
    (tmp_path / "kind_answers").mkdir()  # people's person/company answers: a run would leave them out
    with pytest.raises(InputError, match="person/company answers, which no run reads now"):
        folder.current(tmp_path)

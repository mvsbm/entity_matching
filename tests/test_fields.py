"""Fields: the pipeline file, mandatory and optional fields, blank values."""
from dataclasses import replace

import pandas as pd
import pytest

from er.config import (Budget, FSSpec, InputError, Key, KeyBlocker, Resolver)
from er.match import exact_u, pattern_coverage, train_fs
from er.config import dump_pipeline, fields_read, load_pipeline
from er.settings import fit_to_file, load_settings
from er.standardize import prepare

from conftest import UID, model


def pipeline_and_columns():
    s = load_settings()
    p = load_pipeline(s.root / "config" / "pipeline.toml", s.standardize, s.chains, s.columns)
    return s, p, {c for sources in s.columns.values() for alt in sources for c in alt} - {"ENTITY_ID"}  # every mapped record column


def test_the_pipeline_file_writes_and_loads_back_unchanged(tmp_path):
    s, p, _ = pipeline_and_columns()
    dump_pipeline(p, s.chains, tmp_path / "p.toml")
    assert load_pipeline(tmp_path / "p.toml", s.standardize, s.chains, s.columns) == p


def test_a_mandatory_field_or_an_empty_one_of_group_stops_the_run():
    s, p, cols = pipeline_and_columns()
    with pytest.raises(InputError, match=r"id \(expected in CONT_ID\)"):
        fit_to_file(p, s, cols - {"CONT_ID"})
    names = {"FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA", "NYS_CNV_P_NAME_KANA"}
    with pytest.raises(ValueError, match="person_name .* / company_name"):
        fit_to_file(p, s, cols - names)
    with pytest.raises(ValueError, match="entity"):
        fit_to_file(p, s, cols, labelled=True)  # a labelled run needs the truth
    with pytest.raises(InputError, match="can run: every .* reads a field this file lacks"):
        fit_to_file(p, s, {"CONT_ID", "NYS_CNV_P_NAME_KANA"})  # a mistake to fix, not a traceback
    fit_to_file(p, s, cols | {"ENTITY_ID"}, labelled=True)


def test_an_absent_optional_field_disables_exactly_what_reads_it():
    s, p, cols = pipeline_and_columns()
    q, gone = fit_to_file(p, s, cols - {"CIF_ID"})
    assert "customer_id" not in fields_read(replace(q, generators={b.name: b for b in q.fs.blockers}))
    rules = {r.name for st in q.rules.stages for r in st.rules}
    assert rules == {r.name for st in p.rules.stages for r in st.rules} - {"X1_CIF_PERSON_NAME", "X2_CIF_COMPANY_NAME", "X3_CIF_PHONE", "F3_NAME~_CIF"}
    assert [b.name for b in q.fs.blockers] == [b.name for b in p.fs.blockers if b.name != "cif"]
    assert [c.name for c in q.fs.model.comparisons] == ["name", "company", "address", "phone"]
    assert [[k.column for k in r] for r in q.fs.model.prior_rules] == [["full_name", "address_code", "phone"]]
    assert {g.split(" (")[0] for g in gone} == {"rule X1_CIF_PERSON_NAME", "rule X2_CIF_COMPANY_NAME", "rule X3_CIF_PHONE", "rule F3_NAME~_CIF",
                                                "generator cif", "level cif: exact", "comparison cif",
                                                "prior rule ['customer_id', 'full_name']", "prior rule ['customer_id', 'company_name']"}
    q, gone = fit_to_file(p, s, cols - {"FULL_NAME_KANA", "O_PERSON_NAME_KANA"})  # a field built from the sources the file has
    person = next(d for d in q.rules.standardize.derived if d.name == "person_name")
    assert person.sources == (("LAST_NAME_KANA", "GIVEN_NAME_KANA"),) and any("X1_CIF_PERSON_NAME" in g for g in gone)


def test_pattern_coverage_finds_the_patterns_no_key_guarantees(con_db, records):
    _, db = con_db
    spec = FSSpec(standardize=replace(load_settings().standardize, derived=()), previous_stage="rules", stage="fs", model=model(),
                    blockers=(KeyBlocker(name="phone", keys=(Key("phone"),)),), min_match_weight=-10.0,  # toy weights
                    resolver=Resolver(method="connected_components"),
                    budget=Budget(max_pairs_per_record=10**4, max_block_size=10**4, target_rows=10**6, benchmark_pairs=10))
    model_json = train_fs(model(), records, db, UID)
    open_ = pattern_coverage(spec, model_json, len(records))
    assert len(open_) and not (open_["phone"] == "exact").any()  # the phone key guarantees every pattern with phone exact
    named = pattern_coverage(replace(spec, blockers=spec.blockers + (KeyBlocker(name="name", keys=(Key("name"),)),)), model_json, len(records))
    assert len(named) < len(open_) and not (named["name"] == "exact").any()  # a name key adds the name-exact patterns
    assert len(pattern_coverage(spec, model_json, 10**9)) <= len(open_)  # fewer patterns reach the threshold at scale


def test_exact_u_counts_every_pair(con_db, records):
    _, db = con_db
    holes = records.assign(name=records["name"].mask(records.index % 7 == 0))  # some names missing: the null level
    u = exact_u(model(), holes, db)
    pairs = [(a, b) for i, a in enumerate(holes.itertuples()) for b in list(holes.itertuples())[i + 1:]]
    filled = [(a, b) for a, b in pairs if pd.notna(a.name) and pd.notna(b.name)]
    assert u["name"]["exact"] == pytest.approx(sum(a.name == b.name for a, b in filled) / len(filled))
    assert u["phone"]["exact"] == pytest.approx(sum(a.phone == b.phone for a, b in pairs) / len(pairs))
    assert "close" not in u["name"]  # a fuzzy level stays sampled


def test_blank_values_are_missing_and_full_width_spaces_are_stripped():
    s = load_settings()
    p = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    sources = {c for alts in s.columns.values() for alt in alts for c in alt}
    raw = pd.DataFrame({c: [pd.NA] * 3 for c in sources}, dtype="string")
    raw["CONT_ID"] = ["1", "2", "3"]
    raw["FULL_NAME_KANA"] = ["\u3000", " ", pd.NA]  # blank: the next source must win
    raw["O_PERSON_NAME_KANA"] = ["ヤマダ\u3000タロウ", pd.NA, pd.NA]
    raw["NYS_CNV_P_NAME_KANA"] = [pd.NA, "カブシキガイシャ", "\u3000"]  # a legal form alone is no company name
    df = prepare(p.fs.standardize, raw, p.fs.normalized() + p.rules.normalized())
    assert df["person_name"].tolist()[:1] == ["ヤマダタロウ"] and df["full_name"].isna().all()
    assert df["person_name"].isna().tolist()[1:] == [True, True]
    assert df["company_name__nfkc_strip_legal_form_kana_fold"].isna().all()


def test_katakana_and_strip_separators_read_one_value_written_two_ways_as_one_and_keep_others_apart():
    from er.standardize import normalize
    std = load_settings().standardize
    digits = normalize(pd.Series(["03-1234-5678", "０３（１２３４）５６７８", "〒100-0001", "100 0001", "AB-123", "XY-123", None], dtype="string"), ("nfkc", "strip_separators"), std)
    assert digits.tolist()[:6] == ["0312345678", "0312345678", "1000001", "1000001", "AB123", "XY123"] and pd.isna(digits.iloc[6])  # letters stay: two IDs stay two
    names = normalize(pd.Series(["さとう　ひろし", "サトウヒロシ", "ｻﾄｳﾋﾛｼ"], dtype="string"), ("nfkc", "katakana", "strip_spaces"), std)
    assert names.nunique() == 1
    assert "strip_separators" not in dict((d.name, d.normalize) for d in std.derived).get("birth_date", ())  # 1993-1-12 and 1993-11-2 would be one date

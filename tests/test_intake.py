"""The reader: Parquet files as they come, every column text, what loses nothing fixed and counted."""
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from er.config import InputError
from er.settings import load_settings


def test_the_generator_writes_kanji_names_without_changing_any_other_column():
    from design.generate import check, generate as make, load_reference, load_spec
    s = load_settings()
    spec, ref = replace(load_spec(s.root / "config" / "generator.toml")[0], entities=300), load_reference(s.paths["reference"])
    full = make(spec, *ref)
    check(spec, full)
    bare = make(replace(spec, columns=tuple(c for c in spec.columns if "KANJI" not in c.name)), *ref)
    assert all(full.df[c].equals(bare.df[c]) for c in bare.df.columns)  # the kanji columns' own draws: every other column as it was
    d = full.df.merge(full.truth, on="CONT_ID")
    person, company = d["KIND"].eq("person"), d["KIND"].eq("company")
    assert d.loc[company, "FULL_NAME_KANJI"].isna().all() and d.loc[person, "COMPANY_NAME_KANJI"].isna().all()
    assert 0.5 < d.loc[person, "FULL_NAME_KANJI"].notna().mean() < 0.7  # fewer systems hold kanji than kana
    canon = {b: a for a, b in spec.kanji_variants}  # 齋 → 斎: a variant is the same character, written another way
    plain = lambda v: "".join(canon.get(ch, ch) for ch in v)
    given = d[person].dropna(subset=["GIVEN_NAME_KANJI"]).groupby("ENTITY_ID")["GIVEN_NAME_KANJI"].agg(lambda x: x.map(plain).nunique())
    assert given.max() == 1  # one person, one given name in kanji, through their kana typos
    assert d["COMPANY_NAME_KANJI"].dropna().str.contains("株式会社").any()


def test_a_parquet_file_read_by_column_reads_as_value_by_value_does(tmp_path, monkeypatch):
    import pyarrow as pa
    from er import intake
    spec = intake.InputSpec()
    names = ["ヤマダタロウ", "ヤマダ　タロウ", " サトウ", "サトウ ", "　", "  ", "NULL", " NULL ", "－", "譁ｰ縺励＞", "abc\x01", "タ​ナカ", "a\tb",
             "ﾔﾏﾀﾞ", "�", "", None, "東京" * 100, "①", "😀", "Ｓｕｚｕｋｉ", "plain", " plain", "１２.０", " ", "ア　",
             '["大分県"]', '　["大分県"]　', "[1] ", "[株]", '["a", "b"]', "[]"]  # every kind of value a reading treats apart
    n = 6 * len(names)
    table = pa.table({"id": [f"R{i}" for i in range(n)], "name": [names[i % len(names)] for i in range(n)],
                      "amount": [["12345.0", "1.23457E+11", "100", "１２.０", "3.5", None][i % 6] for i in range(n)],
                      "n": pa.array([i if i % 5 else None for i in range(n)], pa.int64()), "f": pa.array([[1.5, 2.0, None][i % 3] for i in range(n)]),
                      "raw": pa.array([["ヤマダ".encode("cp932"), b"abc", None][i % 3] for i in range(n)], pa.binary()),
                      "kind": pa.array([["法人", "個人", None][i % 3] for i in range(n)]).dictionary_encode()})
    monkeypatch.setattr(intake, "CHUNK", 7)  # a first chunk to learn from, then many read by column

    def read(where: str) -> tuple:
        part = tmp_path / where
        part.mkdir()
        pq.write_table(table, part / "x.parquet")
        r = intake.take(part, {part / "x.parquet": "x.parquet"}, spec)
        return {k: v for k, v in r.items() if k != "seconds"}, pd.read_parquet(part / r["files"][0]["read"])
    quick = read("quick")
    monkeypatch.setattr(intake, "settled", lambda a, *_: np.zeros(len(a), bool))  # nothing settled in Arrow: every value read one by one
    slow = read("slow")
    assert {k: v for k, v in quick[0].items() if k != "files"} == {k: v for k, v in slow[0].items() if k != "files"}  # the same counts and fixes
    assert [{k: v for k, v in x.items() if k not in ("sha256", "versions")} for x in quick[0]["files"]] == [{k: v for k, v in x.items() if k not in ("sha256", "versions")} for x in slow[0]["files"]]
    pd.testing.assert_frame_equal(quick[1], slow[1])
    assert quick[0]["fixed"]["placeholders"] > 0 and quick[0]["fixed"]["damaged"] > 0 and quick[1]["raw"].isna().sum() > n // 3  # both paths taken; bytes that aren't UTF-8 missing


def test_text_reading_keeps_is_found_in_one_pass_as_its_definition_says():
    import random
    import pyarrow as pa
    import pyarrow.compute as pc
    from er import intake
    edges = [0x1f, 0x20, 0x7e, 0x7f, 0x85, 0xa0, 0x1fff, 0x2000, 0x200a, 0x200b, 0x200d, 0x2028, 0x202f, 0x205f, 0x2060, 0x206f, 0x2070, 0x218f, 0x2190,
             0x23ff, 0x2400, 0x2460, 0x27bf, 0x27c0, 0x2fff, 0x3000, 0x30ff, 0x3100, 0x318f, 0x3190, 0x33ff, 0x3400, 0x4dbf, 0x4dc0, 0x4e00, 0x9fff,
             0xa000, 0xf8ff, 0xf900, 0xfaff, 0xfb00, 0xfe2f, 0xfe30, 0xfe4f, 0xfe50, 0xfeff, 0xff00, 0xffef, 0xfff0, 0x1f600]
    pool = [*map(chr, edges), *"\t\n\r ア漢ｱA1縺繧"]
    rng = random.Random(0)
    values = [*pool, *("".join(rng.choice(pool) for _ in range(rng.randint(1, 5))) for _ in range(20_000))]
    bad = lambda v: intake.CONTROL.search(v) or intake.BREAKS.search(v)
    want = [bool(intake.JAPANESE.fullmatch(v)) and not bad(v) and v.strip(" \u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000") != ""
            for v in values]  # every character JAPANESE's, none to fix, one at least not a space
    assert pc.match_substring_regex(pa.array(values), intake.text_re2()).to_pylist() == want and any(want) and not all(want)


def test_plain_ascii_is_printable_ascii_with_no_space_at_either_end():
    import random
    import pyarrow as pa
    import pyarrow.compute as pc
    from er import intake
    rng, chars = random.Random(0), [chr(i) for i in range(128)] + [" "] * 20
    values = ["", " ", "a", " a", "a ", "a b", "\t", "a\tb", "\x7f", "~", None] + ["".join(rng.choices(chars, k=rng.randint(0, 5))) for _ in range(5000)]
    a = pa.array(values, pa.string())
    assert intake.plain_ascii(a).to_pylist() == pc.match_substring_regex(a, "^[!-~](?:[ -~]*[!-~])?$").to_pylist()  # the pattern it replaces


def test_a_parquet_file_reads_alike_whatever_its_row_groups_and_text_that_isn_t_utf8_is_missing_counted_as_damaged(tmp_path, monkeypatch):
    import pyarrow as pa
    from er import intake
    spec = intake.InputSpec()
    monkeypatch.setattr(intake, "CHUNK", 20)
    table = pa.table({"id": [f"R{i}" for i in range(50)], "kind": pa.array(["法人", "個人"] * 25).dictionary_encode(),  # a category: its batches end with its row groups
                      "amount": ["abc"] * 4 + ["12345.0"] * 46})  # the first chunk of 20 says: numbers, written by a spreadsheet

    def read(where: str, **write) -> tuple:
        part = tmp_path / where
        part.mkdir()
        pq.write_table(table, part / "x.parquet", **write)
        r = intake.take(part, {part / "x.parquet": "x.parquet"}, spec)
        return ({k: v for k, v in r.items() if k != "seconds"}, (part / r["files"][0]["read"]).read_bytes())
    whole, groups = read("whole"), read("groups", row_group_size=4)
    assert whole == groups and whole[0]["fixed"] == {"numbers": 46}  # the same chunks, so the same first chunk learned from: byte for byte
    cp932 = [x.encode("cp932") for x in ("ヤマダ", "東京都")] + [b"abc"]
    data = b"".join(cp932)
    offsets = pa.py_buffer(np.cumsum([0, *map(len, cp932)]).astype(np.int32).tobytes())
    stored = pa.Array.from_buffers(pa.string(), len(cp932), [None, offsets, pa.py_buffer(data)])  # bytes a writer stored as text, unchecked
    texts = {}
    for name, column in (("text", stored), ("bytes", pa.array(cp932, pa.binary()))):
        part = tmp_path / name
        part.mkdir()
        pq.write_table(pa.table({"id": ["a", "b", "c"], "name": column}), part / "y.parquet")
        r = intake.take(part, {part / "y.parquet": "y.parquet"}, spec)
        texts[name] = (r["fixed"], [x if isinstance(x, str) else None for x in pd.read_parquet(part / r["files"][0]["read"])["name"]])
    assert texts["text"] == texts["bytes"] == ({"damaged": 2}, [None, None, "abc"])  # Parquet's text is UTF-8: what isn't says nothing, and is counted


def test_a_value_written_as_a_list_reads_as_its_item_and_a_part_an_older_reader_read_is_read_again_once(tmp_path, monkeypatch):
    import pyarrow as pa
    from er import folder, intake
    spec = intake.InputSpec()
    table = pa.table({"id": ["1", "2", "3", "4", "5"],
                      "postal": pa.array([["0708612"], [], [None], ["8700848", "8700849"], None], pa.list_(pa.string())),  # a Parquet list column
                      "phone": pa.array([[1201], [3344], None, [], [7.0]], pa.list_(pa.float64())),
                      "text": ['["大分県"]', "['大分市']", "[株]", "[0708612]", ' ["x"] ']})  # lists a CSV or a text column holds
    part = tmp_path / "ws" / "inputs" / "0001-x"
    part.mkdir(parents=True)
    pq.write_table(table, part / "x.parquet")
    as_text = lambda r: [{c: x if isinstance(x, str) else None for c, x in row.items()} for row in pd.read_parquet(part / r["files"][0]["read"]).to_dict("records")]
    with monkeypatch.context() as m:  # as the reader before this one read it: lists kept as JSON
        m.setattr(intake, "READER", 1)
        m.setattr(intake, "unlisted", lambda v: None)
        old = intake.take(part, {part / "x.parquet": "x.parquet"}, spec)
    assert old["reader"] == 1 and as_text(old)[0]["postal"] == '["0708612"]'
    r = intake.report(folder.fresh(part, spec))
    got = as_text(r)
    assert [x["postal"] for x in got] == ["0708612", None, None, "8700848", None]  # the first of several; an empty list or one of nulls, missing
    assert [x["phone"] for x in got] == ["1201", "3344", None, None, "7"] and [x["text"] for x in got] == ["大分県", "大分市", "[株]", "0708612", "x"]
    assert r["reader"] == intake.READER and r["fixed"] == {"lists": 11, "first of several": 1}  # counted: one loses nothing, the other the rest
    assert r["files"][0]["versions"][0] == old["files"][0]["sha256"] and r["older_reader"] == [old["files"][0]["sha256"]]  # a run that read the old one still finds its file, and is known to have
    seconds = (part / intake.REPORT).stat().st_mtime_ns
    folder.fresh(part, spec)
    assert (part / intake.REPORT).stat().st_mtime_ns == seconds  # read again once: then as it is


def test_the_reader_reads_its_edge_cases_alike_and_a_part_reads_again_under_new_settings_or_after_a_cut(tmp_path, monkeypatch):
    import os
    import pyarrow as pa
    from er import folder, intake
    from er.source import find
    spec = intake.InputSpec()

    def read(name: str, write) -> tuple[dict, pd.DataFrame]:
        part = tmp_path / name.replace(".", "_")
        part.mkdir()
        write(part / name)
        r = intake.take(part, {part / name: name}, spec)
        return r, pd.read_parquet(part / r["files"][0]["read"])
    _, got = read("case.parquet", lambda f: pq.write_table(pa.table({"id": ["1"], "TEL": ["0311112222"], "tel": ["09033334444"], "name": ["[{[]}]"]}), f))
    assert list(got.columns) == ["id", "TEL", "tel_2", "name"] and got["tel_2"][0] == "09033334444"  # DuckDB reads names case aside: tel apart from TEL
    assert got["name"][0] == "[{[]}]"  # brackets that hold no plain list: as written, no crash
    table = pa.table({"id": ["1", "2", "3", "4", "5"], "code": [9e10, 1.23e11, 1e16, 0.5, 12345.0], "half": pa.array([1, 2.5, None, 4, 5], pa.float16()),
                      "old": pa.array(["ヤマダ".encode("cp932")] * 5, pa.binary()), "name": ["𠮷野家", "山田花子", None, "𠮷田", "東京"]})
    r, got = read("float.parquet", lambda f: pq.write_table(table, f))
    assert got["code"].tolist() == ["90000000000", "123000000000", "10000000000000000", "0.5", "12345"] and "numbers" not in r["fixed"]
    assert got["half"].tolist()[:2] == ["1", "2.5"]  # a half float too  # never 9e+10, read as cut short
    assert got["name"].tolist()[:2] == ["𠮷野家", "山田花子"] and got["old"].isna().all() and r["fixed"]["damaged"] == 5  # Parquet text is UTF-8: other bytes say nothing
    one = lambda f, i: pd.DataFrame({"id": [i]}).to_parquet(f)
    one(tmp_path / "customers[2024].parquet", "1")
    one(tmp_path / "customers2.parquet", "2")
    assert find(tmp_path / "customers[2024].parquet") == [tmp_path / "customers[2024].parquet"]  # a file that exists is itself, [ in its name or not
    exports = tmp_path / "exports"
    (exports / "archive").mkdir(parents=True)
    (exports / ".DS_Store").write_bytes(b"\0")
    one(exports / "a.parquet", "1")
    (exports / "notes.csv").write_text("id\n2\n", encoding="utf-8")
    assert find(exports / "*") == [exports / "a.parquet"] and find(exports) == [exports / "a.parquet"]  # a pattern's files, as a folder's: no folder, no hidden file, Parquet only

    ws = tmp_path / "ws"
    pd.DataFrame({"id": ["1", "2", "3"], "code": ["-", "N/A", "A1"]}).to_parquet(tmp_path / "f.parquet")
    part, _ = folder.take_in(ws, tmp_path / "f.parquet", spec)
    codes = lambda: [x if isinstance(x, str) else None for x in pd.read_parquet(part / intake.report(part)["files"][0]["read"])["code"]]
    assert codes() == [None, None, "A1"]
    folder.fresh(part, replace(spec, nulls=("NULL",)))
    assert codes() == ["-", "N/A", "A1"]  # [input] changed: read again under it
    replace_ = os.replace
    def cut(a, b):  # the process stops as a reading again is about to move its report into place
        if Path(b).name == intake.REPORT:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(intake.os, "replace", cut)
    with pytest.raises(KeyboardInterrupt):
        intake.take(part, {part / "f.parquet": "f.parquet"}, spec)
    monkeypatch.undo()
    assert intake.report(part)["input"] == intake.read_as(replace(spec, nulls=("NULL",)))  # read/ new, the report old
    folder.fresh(part, spec)  # the next to open it finishes the moves: the reading was complete
    assert codes() == [None, None, "A1"] and intake.report(part)["input"] == intake.read_as(spec) and not (part / ".read.tmp").exists()


def test_two_files_whose_names_differ_only_by_case_are_refused_not_read_into_one(tmp_path):
    from er import intake
    pd.DataFrame({"id": ["1"], "name": ["ヤマダ"]}).to_parquet(tmp_path / "one.parquet")
    pd.DataFrame({"id": ["2"], "name": ["サトウ"]}).to_parquet(tmp_path / "two.parquet")
    with pytest.raises(InputError, match="would be read into one file"):  # a.parquet and A.parquet from a disk that tells case apart, on one that doesn't
        intake.take(tmp_path, {tmp_path / "one.parquet": "a.parquet", tmp_path / "two.parquet": "A.parquet"}, intake.InputSpec())


def test_a_file_that_isn_t_parquet_is_refused_saying_how_to_write_it_and_parquet_without_its_ending_is_read(tmp_path):
    from er import folder, intake
    from er.settings import load_settings as settings
    (tmp_path / "x.csv").write_text("id,name\n1,ヤマダ\n", encoding="utf-8")
    (tmp_path / "x.xlsx").write_bytes(b"PK\x03\x04" + b"\0" * 20)
    for f, looks in (("x.csv", "text, perhaps a CSV"), ("x.xlsx", "a ZIP or Excel file")):
        with pytest.raises(InputError, match=f"not a Parquet file; it looks like {looks}") as e:
            folder.take_in(tmp_path / "ws", tmp_path / f, intake.InputSpec())
        assert "to_parquet" in e.value.fix and "read_csv(path, all_varchar = true)" in e.value.fix
    pd.DataFrame({"id": ["1"]}).to_parquet(tmp_path / "export.dat")
    part, new = folder.take_in(tmp_path / "ws", tmp_path / "export.dat", intake.InputSpec())
    assert new and intake.report(part)["rows"] == 1  # Parquet saved without its ending: read as it is
    with pytest.raises(InputError, match=r"\[input\] encodings, margin_text: set nothing") as e:
        settings_file = tmp_path / "settings.toml"
        root = settings().root
        settings_file.write_text((root / "config" / "settings.toml").read_text(encoding="utf-8").replace(
            "[input]\n", '[input]\nencodings = ["utf-8"]\nmargin_text = 0.75\n'), encoding="utf-8")
        settings(settings_file)
    assert e.value.fix == "delete encodings, margin_text from [input]"

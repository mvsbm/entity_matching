"""The reader and describe records: files as they come, repairs proposed and accepted."""
import io
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from er.config import (InputError)
from er.settings import load_settings



def test_the_generator_writes_kanji_names_without_changing_any_other_column():
    from er.generate import check, generate as make, load_reference, load_spec
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


def test_the_reader_reads_each_value_as_it_comes_and_proposes_only_what_it_would_guess(tmp_path, monkeypatch):
    import gzip
    import zipfile
    import pyarrow as pa
    from er import intake
    ref, spec = load_settings().paths["reference"], intake.InputSpec()

    def read(name: str, data: bytes, accepted: tuple[str, ...] = ()) -> tuple[dict, pd.DataFrame, list[dict], list[dict]]:
        part = tmp_path / name.replace(".", "_")
        part.mkdir(exist_ok=True)
        (part / name).write_bytes(data)
        r = intake.take(part, {part / name: name}, spec, ref, frozenset(accepted))
        return (r, pd.read_parquet(part / r["files"][0]["read"]).set_index("id"), pd.read_parquet(part / intake.PROPOSALS).to_dict("records"),
                pd.read_parquet(part / intake.UNREAD).to_dict("records"))
    u = lambda t: t.encode("utf-8")
    good = [u(f"{i},ヤマモト　タロウ,東京都港区芝公園{i}-2,{1000 + i}") for i in range(60)]
    dirty = b"\n".join([b"id,name,address,phone", *good,
        b"900," + "サトウ　ジロウ".encode("cp932") + b"," + "大阪府北区".encode("cp932") + b",1234",  # another system's CP932
        b"901," + "キムラ".encode("euc-jp") + b"," + "東京都".encode("euc-jp") + b",12.0",            # and EUC-JP; a number a spreadsheet wrote
        b"902," + u("​タナカ") + b"\x00," + u("東京都") + b",NULL",                            # a zero-width character, a NUL, a placeholder
        b"903," + u("譁ｰ縺励＞") + b"," + u("京都府") + b",1.23457E+11",                             # garbled upstream; a number cut short
        b"904," + u("ナカムラ") + b"," + u("大阪府北区3,4番") + b",5678",                           # a comma inside a value
        b"905," + u("イトウ") + b"," + u("東京都港"),                                             # a line break inside a value ...
        u("区1") + b",5555",                                                                       # ... the rest of the row
        b"906,a,b,c,d,e,f,g,h",                                                                    # too many fields to re-split
        b"907," + u("\u3000 ") + b"," + u("京都府") + b",4321"]) + b"\n"                            # a name of spaces alone: missing
    r, rows, proposed, unread = read("dirty.csv", dirty)
    assert rows.loc["900", "name"] == "サトウ　ジロウ" and rows.loc["901", "name"] == "キムラ" and r["decoded"]["cp932"] == 2 and r["decoded"]["euc-jp"] == 2
    assert rows.loc["902", "name"] == "タナカ" and pd.isna(rows.loc["902", "phone"]) and rows.loc["901", "phone"] == "12" and pd.isna(rows.loc["903", "phone"])
    assert r["fixed"] == {"controls": 1, "placeholders": 2, "numbers": 2} and pd.isna(rows.loc["907", "name"]) and rows.loc["907", "phone"] == "4321"
    assert rows.loc["903", "name"] == "譁ｰ縺励＞" and {"904", "905", "906"}.isdisjoint(rows.index)  # nothing guessed is applied before people accept it
    assert {(x["kind"], x["after"]) for x in proposed} == {("garbled", "新しい"), ("realign", "東京都港 区1"), ("realign", "大阪府北区3,4番")}
    assert [(x["line"], "waits" in x["reason"]) for x in unread] == [(66, True), (67, True), (68, True), (69, False)] and r["unread"] == 4  # a split row's two lines wait together
    r2, rows, proposed, unread = read("dirty.csv", dirty, ("realign", "garbled"))
    assert rows.loc["903", "name"] == "新しい" and rows.loc["904", "address"] == "大阪府北区3,4番" and rows.loc["905", "phone"] == "5555"
    assert [x["line"] for x in unread] == [69] and r2["files"][0]["versions"][0] == r["files"][0]["sha256"]  # what it replaced, kept by its hash
    monkeypatch.setattr(intake, "KEEP", 1)  # past KEEP of a kind, proposals are counted, not kept; accepting still repairs them all
    r3, rows, proposed, _ = read("dirty.csv", dirty)
    assert r3["proposed"]["realign"] == 2 and [x["kind"] for x in proposed].count("realign") == 1
    r3, rows, *_ = read("dirty.csv", dirty, ("realign",))
    assert rows.loc["904", "address"] == "大阪府北区3,4番" and rows.loc["905", "phone"] == "5555"

    short = b"\n".join([b"id,name,address,phone", *good, b"100," + u("ヤマダタロウ"), b"101," + u("スズキハナコ,大阪府")]) + b"\n"  # a writer that leaves off empty fields
    r4, rows, proposed, unread = read("short.csv", short, ("realign",))
    assert not [x for x in proposed if x["kind"] == "realign"] and [x["line"] for x in unread] == [62, 63]  # two records, never glued into one
    kana = "\n".join(["id,name_kana,phone", *(f"{i},{'ﾔﾏﾓﾄ ﾀﾛｳ' if i % 8 == 0 else 'ヤマモト　タロウ'},{1000 + i}" for i in range(200)), "900,ﾄｮﾀﾞﾐｴｺﾞ,1234"]) + "\n"
    part = tmp_path / "halfwidth"
    part.mkdir()
    (part / "halfwidth.csv").write_bytes(kana.encode("cp932"))  # half-width kana in a kana column: its bytes read as kanji in EUC-JP too
    r = intake.take(part, {part / "halfwidth.csv": "halfwidth.csv"}, replace(spec, margin_text=0.3), ref)  # a margin low enough that text alone would tip it
    assert not r["proposed"]  # a column that holds no kanji is offered none

    table = pa.table({"id": ["1", "2", "3"], "name": ["ヤマモト", None, ""], "n": pa.array([1, 2, None], pa.int64()), "x": [1.5, 2.0, None],
                      "day": pa.array([None, 0, 1], pa.date32()), "b": pa.array([u("東京"), "大阪".encode("cp932"), None], pa.binary())})
    clean = io.BytesIO()
    pq.write_table(table, clean)
    r, rows, proposed, unread = read("typed.parquet", clean.getvalue())
    assert rows.astype(object).where(rows.notna(), None).to_dict("index") == {"1": {"name": "ヤマモト", "n": "1", "x": "1.5", "day": None, "b": "東京"}, "2": {"name": None, "n": "2", "x": "2", "day": "1970-01-01", "b": "大阪"},
                                     "3": {"name": None, "n": None, "x": None, "day": "1970-01-02", "b": None}}  # text, as the door reads it; blank is missing
    assert not proposed and not unread and r["fixed"] == {} and any("leading zeros" in n for n in r["notes"])
    r, rows, *_ = read("quoted.csv", u('id,name\n1,"ヤマダ, タロウ"\n2,"""別府"\n'))  # a file that quotes: a comma and a quote inside values
    assert rows.loc["1", "name"] == "ヤマダ, タロウ" and rows.loc["2", "name"] == '"別府' and r["files"][0]["quotes"]
    r, rows, *_ = read("stray.csv", u('id,name,phone\n1,"別府,1234\n2,ヤマダ,5678\n'))  # one that never does: a stray quote is text
    assert rows.loc["1", "name"] == '"別府' and rows.loc["2", "phone"] == "5678" and not r["files"][0]["quotes"]
    base = "id,name,address\n1,ヤマダ　タロウ,東京都港区1-2\n2,サトウ,大阪府北区3\n"
    for name, data in (("euc.csv", base.encode("euc-jp")), ("le.csv", base.encode("utf-16-le")), ("jis.csv", base.encode("iso2022_jp")),
                       ("titled.csv", u("顧客一覧 2026-11\n" + base)), ("trailing.csv", u("id,name,address\n1,ヤマダ　タロウ,東京都港区1-2,\n2,サトウ,大阪府北区3,\n"))):
        r, rows, proposed, unread = read(name, data)  # one encoding for the whole file, UTF-16 without its BOM, JIS; a title above the header; a delimiter at a record's end
        assert (rows.loc["1", "name"], rows.loc["2", "address"]) == ("ヤマダ　タロウ", "大阪府北区3") and not proposed and not unread, name
    assert any("above the header" in n for n in read("titled.csv", u("顧客一覧 2026-11\n" + base))[0]["notes"])
    (tmp_path / "headless.csv").write_bytes(u(base.split("\n", 1)[1]))
    assert any("header may be missing" in n for n in intake.take(tmp_path, {tmp_path / "headless.csv": "headless.csv"}, spec, ref)["notes"])
    with pytest.raises(InputError, match="gzip"):
        read("in.csv.gz", gzip.compress(u(base)))
    r, rows, *_ = read("utf16.tsv", "id\tname\n1\tヤマモト\n".encode("utf-16"))
    assert rows.loc["1", "name"] == "ヤマモト" and r["files"][0]["delimiter"] == "\t"
    book = io.BytesIO()
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("xl/workbook.xml", "")
    with pytest.raises(InputError, match="Excel"):
        read("book.xlsx", book.getvalue())
    with pytest.raises(InputError, match="cut short"):
        read("cut.parquet", clean.getvalue()[:-10])


def test_the_reader_takes_the_files_real_systems_write_and_refuses_one_it_cannot_line_up(tmp_path, monkeypatch):
    from er import intake
    ref, spec = load_settings().paths["reference"], intake.InputSpec()

    def read(name: str, data: bytes) -> tuple[dict, pd.DataFrame]:
        part = tmp_path / name.replace(".", "_")
        part.mkdir()
        (part / name).write_bytes(data)
        r = intake.take(part, {part / name: name}, spec, ref)
        return r, pd.read_parquet(part / r["files"][0]["read"])
    rows = ["id|name|phone", *(f"{i}|ニッポン　ショウジ{i}|{1000 + i}" for i in range(30))]
    r, got = read("pipe.txt", "\n".join(rows).encode("cp932"))  # | is the second byte of ポ in CP932: decoded whole first
    assert len(got) == 30 and not r["unread"] and got["name"][0] == "ニッポン　ショウジ0" and r["files"][0]["format"] == "cp932"
    r, got = read("flag.txt", "".join(f"{x}\n" for x in ["id|name|kind", *(f"{i}|ヤマダ|{i % 2}" for i in range(30))]).encode("cp932"))  # ダ just before the last field
    assert r["files"][0]["format"] == "cp932" and list(got["name"].unique()) == ["ヤマダ"]
    rows = ["id|name|kind", *(f"{i}|ヤマダ　タロウ|{i % 2}" for i in range(50))]  # mostly UTF-8, one CP932 row: read by value, never decoded whole as CP932
    r, got = read("mixed.txt", "".join(f"{x}\n" for x in rows).encode("utf-8") + "51|ポーラ|1\n".encode("cp932"))
    assert r["files"][0]["format"] == "csv" and set(got["name"]) == {"ヤマダ　タロウ"} and r["proposed"] == {"realign": 1}  # ポ's | split it: proposed
    r, got = read("stray.txt", "".join(f"{x}\n" for x in rows[:-1]).replace("ヤマダ", "ニッポン").encode("cp932") + b"49|\x81 x|1\n")
    assert r["files"][0]["format"] == "cp932" and got["name"].iloc[0] == "ニッポン　タロウ"  # one line CP932 can't read: still CP932
    assert r["fixed"].get("damaged") == 1  # that line's value, bytes CP932 can't read: made missing, counted
    names = ["サトウ　ハナコ", "ワタナベ　タロウ"]  # EUC-JP reads as CP932 too, but is no CP932 file: read by value, right
    r, got = read("euc.txt", "".join(f"{x}\n" for x in ["id|name|kind", *(f"{i}|{names[i % 10 == 0]}|{i % 2}" for i in range(30))]).encode("euc-jp"))
    assert r["files"][0]["format"] == "csv" and set(got["name"]) == set(names)
    r, got = read("cr.txt", "id|name|kind\r1|ニッポン|1\r2|ポーラ|0".encode("cp932"))  # CR line ends, no final line end
    assert r["files"][0]["format"] == "cp932" and list(got["name"]) == ["ニッポン", "ポーラ"]
    r, got = read("memo.txt", 'id\tmemo\r\n1\t"1行目\n2行目"\r\n2\tなし\r\n'.encode("utf-16"))  # Excel's Unicode text: a quoted cell with a line break
    assert list(got["memo"]) == ["1行目 2行目", "なし"] and not r["unread"]  # read whole; its line break a space, as in any value
    r, got = read("cr.csv", "id,name\r1,ヤマダ\r2,サトウ\r".encode("utf-16"))  # UTF-16, lines ended by CR alone
    assert list(got["name"]) == ["ヤマダ", "サトウ"]
    r, got = read("dup.csv", b"A,A,A_2\n1,2,3\n")  # a repeated header: every column kept, each its own name
    assert list(got.columns) == ["A", "A_3", "A_2"] and list(got.iloc[0]) == ["1", "2", "3"]  # A_2 stays the header's own
    r, got = read("ids.csv", b"id,code\n1,1E0001\n2,1.23457E+11\n3,7\n4,1E+11\n")  # only a spreadsheet's E notation is a number cut short
    assert list(got["code"].fillna("·")) == ["1E0001", "·", "7", "·"]
    monkeypatch.setattr(intake, "CHUNK", 20_000)  # a few bad rows at the top of a long file: set aside, not refused
    r, got = read("top.csv", "\n".join(["id,name,city", *(f"{i},Ito, Inc.,Oita" for i in range(1100)), *(f"{i},Ito,Oita" for i in range(1100, 22_000))]).encode())
    assert len(got) == 20_900 and r["unread"] == 1100
    with pytest.raises(InputError, match="don't line up"):  # a wrong delimiter: refused, not 99% unread
        read("bad.csv", "\n".join(["a,b,c", *(f"{i},x,y,z" if i % 3 == 0 else f"{i},x,y" for i in range(6000))]).encode())


def test_a_parquet_file_read_by_column_reads_as_value_by_value_does(tmp_path, monkeypatch):
    import pyarrow as pa
    from er import intake
    ref, spec = load_settings().paths["reference"], intake.InputSpec()
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
        r = intake.take(part, {part / "x.parquet": "x.parquet"}, spec, ref)
        return ({k: v for k, v in r.items() if k != "seconds"}, pd.read_parquet(part / r["files"][0]["read"]),
                pd.read_parquet(part / intake.PROPOSALS), pd.read_parquet(part / intake.UNREAD))
    quick = read("quick")
    monkeypatch.setattr(intake, "settled", lambda a, *_: (np.zeros(len(a), bool),) * 2)  # nothing settled in Arrow: every value read one by one
    slow = read("slow")
    assert {k: v for k, v in quick[0].items() if k != "files"} == {k: v for k, v in slow[0].items() if k != "files"}  # the same counts, fixes and proposals
    assert [{k: v for k, v in x.items() if k not in ("sha256", "versions")} for x in quick[0]["files"]] == [{k: v for k, v in x.items() if k not in ("sha256", "versions")} for x in slow[0]["files"]]
    for a, b in zip(quick[1:], slow[1:]):
        pd.testing.assert_frame_equal(a, b)
    assert quick[0]["decoded"]["utf-8"] > 0 and quick[0]["fixed"]["placeholders"] > 0  # both paths were taken


def test_text_reading_keeps_is_found_in_one_pass_as_its_definition_says():
    import random
    import pyarrow as pa
    import pyarrow.compute as pc
    from er import intake
    m = intake.model(load_settings().paths["reference"])
    edges = [0x1f, 0x20, 0x7e, 0x7f, 0x85, 0xa0, 0x1fff, 0x2000, 0x200a, 0x200b, 0x200d, 0x2028, 0x202f, 0x205f, 0x2060, 0x206f, 0x2070, 0x218f, 0x2190,
             0x23ff, 0x2400, 0x2460, 0x27bf, 0x27c0, 0x2fff, 0x3000, 0x30ff, 0x3100, 0x318f, 0x3190, 0x33ff, 0x3400, 0x4dbf, 0x4dc0, 0x4e00, 0x9fff,
             0xa000, 0xf8ff, 0xf900, 0xfaff, 0xfb00, 0xfe2f, 0xfe30, 0xfe4f, 0xfe50, 0xfeff, 0xff00, 0xffef, 0xfff0, 0x1f600]
    pool = [*map(chr, edges), *"\t\n\r ア漢ｱA1", *sorted(m.garbled)[:50]]
    rng = random.Random(0)
    values = [*pool, *("".join(rng.choice(pool) for _ in range(rng.randint(1, 5))) for _ in range(20_000))]
    bad = lambda v: intake.CONTROL.search(v) or intake.BREAKS.search(v) or not m.garbled.isdisjoint(v)
    want = [bool(intake.JAPANESE.fullmatch(v)) and not bad(v) and v.strip(" \u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000") != ""
            for v in values]  # every character JAPANESE's, none to fix, one at least not a space
    assert pc.match_substring_regex(pa.array(values), intake.text_re2(m.garbled)).to_pylist() == want and any(want) and not all(want)


def test_plain_ascii_is_printable_ascii_with_no_space_at_either_end():
    import random
    import pyarrow as pa
    import pyarrow.compute as pc
    from er import intake
    rng, chars = random.Random(0), [chr(i) for i in range(128)] + [" "] * 20
    values = ["", " ", "a", " a", "a ", "a b", "\t", "a\tb", "\x7f", "~", None] + ["".join(rng.choices(chars, k=rng.randint(0, 5))) for _ in range(5000)]
    a = pa.array(values, pa.string())
    assert intake.plain_ascii(a).to_pylist() == pc.match_substring_regex(a, "^[!-~](?:[ -~]*[!-~])?$").to_pylist()  # the pattern it replaces


def test_a_parquet_file_reads_alike_whatever_its_row_groups_and_text_that_isn_t_utf8_reads_as_bytes(tmp_path, monkeypatch):
    import pyarrow as pa
    from er import intake
    ref, spec = load_settings().paths["reference"], intake.InputSpec()
    monkeypatch.setattr(intake, "CHUNK", 20)
    table = pa.table({"id": [f"R{i}" for i in range(50)], "kind": pa.array(["法人", "個人"] * 25).dictionary_encode(),  # a category: its batches end with its row groups
                      "amount": ["abc"] * 4 + ["12345.0"] * 46})  # the first chunk of 20 says: numbers, written by a spreadsheet

    def read(where: str, **write) -> tuple:
        part = tmp_path / where
        part.mkdir()
        pq.write_table(table, part / "x.parquet", **write)
        r = intake.take(part, {part / "x.parquet": "x.parquet"}, spec, ref)
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
        r = intake.take(part, {part / "y.parquet": "y.parquet"}, spec, ref)
        texts[name] = (r["decoded"], pd.read_parquet(part / r["files"][0]["read"])["name"].tolist())
    assert texts["text"] == texts["bytes"] and texts["text"][1][:2] == ["ヤマダ", "東京都"]  # read one by one, in its own encoding


def test_a_value_written_as_a_list_reads_as_its_item_and_a_part_an_older_reader_read_is_read_again_once(tmp_path, monkeypatch):
    import pyarrow as pa
    from er import folder, intake
    ref, spec = load_settings().paths["reference"], intake.InputSpec()
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
        old = intake.take(part, {part / "x.parquet": "x.parquet"}, spec, ref)
    assert old["reader"] == 1 and as_text(old)[0]["postal"] == '["0708612"]'
    r = intake.report(folder.fresh(part, spec, ref))
    got = as_text(r)
    assert [x["postal"] for x in got] == ["0708612", None, None, "8700848", None]  # the first of several; an empty list or one of nulls, missing
    assert [x["phone"] for x in got] == ["1201", "3344", None, None, "7"] and [x["text"] for x in got] == ["大分県", "大分市", "[株]", "0708612", "x"]
    assert r["reader"] == intake.READER and r["fixed"] == {"lists": 11, "first of several": 1}  # counted: one loses nothing, the other the rest
    assert r["files"][0]["versions"][0] == old["files"][0]["sha256"] and r["older_reader"] == [old["files"][0]["sha256"]]  # a run that read the old one still finds its file, and is known to have
    seconds = (part / intake.REPORT).stat().st_mtime_ns
    folder.fresh(part, spec, ref)
    assert (part / intake.REPORT).stat().st_mtime_ns == seconds  # read again once: then as it is


def test_the_reader_reads_its_edge_cases_alike_and_a_part_reads_again_under_new_settings_or_after_a_cut(tmp_path, monkeypatch):
    import os
    import pyarrow as pa
    from er import folder, intake
    from er.source import find
    ref, spec = load_settings().paths["reference"], intake.InputSpec()

    def read(name: str, write) -> tuple[dict, pd.DataFrame]:
        part = tmp_path / name.replace(".", "_")
        part.mkdir()
        write(part / name)
        r = intake.take(part, {part / name: name}, spec, ref)
        return r, pd.read_parquet(part / r["files"][0]["read"])
    _, got = read("case.csv", lambda f: f.write_text("id,TEL,tel,name\n1,0311112222,09033334444,[{[]}]\n", encoding="utf-8"))
    assert list(got.columns) == ["id", "TEL", "tel_2", "name"] and got["tel_2"][0] == "09033334444"  # DuckDB reads names case aside: tel apart from TEL
    assert got["name"][0] == "[{[]}]"  # brackets that hold no plain list: as written, no crash
    table = pa.table({"id": ["1", "2", "3", "4", "5"], "code": [9e10, 1.23e11, 1e16, 0.5, 12345.0], "half": pa.array([1, 2.5, None, 4, 5], pa.float16()),
                      "old": pa.array(["ヤマダ".encode("cp932")] * 5, pa.binary()), "name": ["𠮷野家", "山田花子", None, "𠮷田", "東京"]})
    r, got = read("float.parquet", lambda f: pq.write_table(table, f))
    assert got["code"].tolist() == ["90000000000", "123000000000", "10000000000000000", "0.5", "12345"] and "numbers" not in r["fixed"]
    assert got["half"].tolist()[:2] == ["1", "2.5"]  # a half float too  # never 9e+10, read as cut short
    assert got["name"].tolist()[:2] == ["𠮷野家", "山田花子"] and got["old"][0] == "ヤマダ"  # Parquet text is UTF-8, whatever its other columns' encoding
    both = tmp_path / "both"
    both.mkdir()
    pd.DataFrame({"id": ["1"]}).to_csv(both / "x.csv", index=False)
    pd.DataFrame({"id": ["2"]}).to_parquet(both / "x.csv.parquet")
    with pytest.raises(InputError, match="read into one file"):  # one would overwrite the other
        folder.take_in(tmp_path / "ws_both", both, spec, ref)

    (tmp_path / "customers[2024].csv").write_text("id\n1\n", encoding="utf-8")
    (tmp_path / "customers2.csv").write_text("id\n2\n", encoding="utf-8")
    assert find(tmp_path / "customers[2024].csv") == [tmp_path / "customers[2024].csv"]  # a file that exists is itself, [ in its name or not
    exports = tmp_path / "exports"
    (exports / "archive").mkdir(parents=True)
    (exports / ".DS_Store").write_bytes(b"\0")
    (exports / "a.csv").write_text("id\n1\n", encoding="utf-8")
    assert find(exports / "*") == [exports / "a.csv"]  # a pattern's files, as a folder's: no folder, no hidden file

    ws = tmp_path / "ws"
    (tmp_path / "f.csv").write_text("id,code\n1,-\n2,N/A\n3,A1\n", encoding="utf-8")
    part, _ = folder.take_in(ws, tmp_path / "f.csv", spec, ref)
    codes = lambda: [x if isinstance(x, str) else None for x in pd.read_parquet(part / intake.report(part)["files"][0]["read"])["code"]]
    assert codes() == [None, None, "A1"]
    folder.fresh(part, replace(spec, nulls=("NULL",)), ref)
    assert codes() == ["-", "N/A", "A1"]  # [input] changed: read again under it
    replace_ = os.replace
    def cut(a, b):  # the process stops as a reading again is about to move its report into place
        if Path(b).name == intake.REPORT:
            raise KeyboardInterrupt
        replace_(a, b)
    monkeypatch.setattr(intake.os, "replace", cut)
    with pytest.raises(KeyboardInterrupt):
        intake.take(part, {part / "f.csv": "f.csv"}, spec, ref)
    monkeypatch.undo()
    assert intake.report(part)["input"] == intake.read_as(replace(spec, nulls=("NULL",)))  # read/ new, the report old
    folder.fresh(part, spec, ref)  # the next to open it finishes the moves: the reading was complete
    assert codes() == [None, None, "A1"] and intake.report(part)["input"] == intake.read_as(spec) and not (part / ".read.tmp").exists()


@pytest.mark.parametrize("ends", ["lf", "crlf"])
def test_a_csv_read_by_column_reads_as_value_by_value_does_its_odd_fields_and_encodings_too(tmp_path, monkeypatch, ends):
    from er import intake
    ref, spec = load_settings().paths["reference"], intake.InputSpec()
    names = ["ヤマダタロウ", "ヤマダ　タロウ", " サトウ", "サトウ ", "　", "  ", "NULL", " NULL ", "－", "譁ｰ縺励＞", "abc\x01", "タ​ナカ", "a\tb",
             "ﾔﾏﾀﾞ", "�", "", "東京" * 100, "①", "😀", "Ｓｕｚｕｋｉ", "plain", " plain", "１２.０", " ", "ア　", "a,b", 'say "hi"', "two\nlines",
             '["大分県"]', '　["大分県"]　', "[1] ", "[株]", '["a", "b"]', "[]"]  # every kind of value a reading treats apart
    field = lambda v, enc="utf-8": ('"' + v.replace('"', '""') + '"' if any(c in v for c in ',"\n') else v).encode(enc)  # quoted as a CSV writer quotes
    rows = [b"id,name,amount,kana"]
    for i in range(6 * len(names)):
        kana = field("ヤマダ", "cp932") if i == 40 else field(names[(i * 7) % len(names)])  # one CP932 field: that chunk of that column read one by one
        rows.append(b",".join([field(f"R{i}"), field(names[i % len(names)]), field(["12345.0", "1.23457E+11", "100", "１２.０", "3.5", ""][i % 6]), kana]))
    rows.append(b"R-odd,only two")  # a row that doesn't line up
    (tmp_path / "x.csv").write_bytes(b"\n".join(rows) + b"\n" if ends == "lf" else "\ufeff".encode() + b"\r\n".join(rows) + b"\r\n")  # as Unix writes it; as Windows does, with a BOM
    monkeypatch.setattr(intake, "CHUNK", 7)  # a first chunk to learn from, then many

    def read(where: str) -> tuple:
        part = tmp_path / where
        part.mkdir()
        r = intake.take(part, {tmp_path / "x.csv": "x.csv"}, spec, ref)
        return ({k: v for k, v in r.items() if k != "seconds"}, (part / r["files"][0]["read"]).read_bytes(),
                (part / intake.PROPOSALS).read_bytes(), (part / intake.UNREAD).read_bytes())
    spied = {}
    for name in ("plain_csv", "arrow_split", "as_text"):  # what each reading went through
        monkeypatch.setattr(intake, name, (lambda real, name: lambda *a: spied.setdefault(name, []).append(x := real(*a)) or x)(getattr(intake, name), name))
    by_arrow = read("by_arrow")
    assert spied["plain_csv"][0] and any(x is not None for x in spied["arrow_split"]) and any(x is None for x in spied["arrow_split"])  # lines Python's csv read, Arrow's, and some that didn't line up
    monkeypatch.setattr(intake, "plain_csv", lambda *a: None)  # Python's csv alone
    by_column = read("by_column")
    assert any(a is not None for a in spied["as_text"]) and any(a is None for a in spied["as_text"])  # columns decoded at once, the chunk with CP932 field by field
    monkeypatch.setattr(intake, "as_text", lambda fields: None)  # no column decoded at once: each field decoded as it comes
    monkeypatch.setattr(intake, "settled", lambda a, *_: (np.zeros(len(a), bool),) * 2)  # nothing settled in Arrow: every value read one by one
    one_by_one = read("one_by_one")
    assert by_arrow == by_column == one_by_one  # byte for byte: the read file, its counts, fixes and proposals, the rows unread
    assert by_column[0]["decoded"]["utf-8"] > 0 and by_column[0]["fixed"]["placeholders"] > 0 and by_column[0]["unread"] == 1


def test_what_is_built_from_the_reference_files_is_kept_on_disk_until_they_or_its_code_change(tmp_path, monkeypatch):
    from er import intake
    monkeypatch.setattr(intake, "CACHE", tmp_path / "cache")
    built = []
    build = lambda x: lambda: built.append(x) or {"built": x}
    assert intake.kept("lists", ("files", 1), build(1)) == {"built": 1} and intake.kept("lists", ("files", 1), build(2)) == {"built": 1}  # built once, then read
    assert intake.kept("lists", ("files", 2), build(3)) == {"built": 3} and built == [1, 3]  # a file changed: built again
    assert len(list((tmp_path / "cache").glob("lists-*.pickle"))) == 1  # the newest alone: nothing grows
    next((tmp_path / "cache").glob("lists-*.pickle")).write_bytes(b"cut short")
    assert intake.kept("lists", ("files", 2), build(4)) == {"built": 4}  # unreadable: built again, never a failure
    (tmp_path / "cache").chmod(0o500)
    try:
        assert intake.kept("other", ("files", 1), build(5)) == {"built": 5}  # a folder it can't write: built, not kept
    finally:
        (tmp_path / "cache").chmod(0o700)


def test_utf16_without_its_bom_reads_whole_though_full_width_spaces_put_nuls_on_the_other_side(tmp_path):
    from er import intake
    rows = "id,name,address\n" + "".join(f"{i},ヤマダ　タロウ,東京都港区{i}\n" for i in range(40))  # U+3000 is 00 30 in UTF-16-LE
    for enc in ("utf-16-le", "utf-16-be"):
        part = tmp_path / enc
        part.mkdir()
        (part / "r.csv").write_bytes(rows.encode(enc))
        r = intake.take(part, {part / "r.csv": "r.csv"}, intake.InputSpec(), load_settings().paths["reference"])
        got = pd.read_parquet(part / r["files"][0]["read"])
        assert r["files"][0]["format"] == enc and got["name"].iloc[0] == "ヤマダ　タロウ" and got["address"].iloc[3] == "東京都港区3", enc


def test_two_files_whose_names_differ_only_by_case_are_refused_not_read_into_one(tmp_path):
    from er import intake
    (tmp_path / "one.csv").write_text("id,name\n1,ヤマダ\n", encoding="utf-8")
    (tmp_path / "two.csv").write_text("id,name\n2,サトウ\n", encoding="utf-8")
    with pytest.raises(InputError, match="would be read into one file"):  # a.csv and A.csv from a disk that tells case apart, on one that doesn't
        intake.take(tmp_path, {tmp_path / "one.csv": "a.csv", tmp_path / "two.csv": "A.csv"}, intake.InputSpec(), load_settings().paths["reference"])

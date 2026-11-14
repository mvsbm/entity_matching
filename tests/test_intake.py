"""The reader and describe records: files as they come, repairs proposed and accepted."""
import io
import json
import math
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from er.config import (InputError)
from er.settings import load_settings

from conftest import dirty_csv


def test_describe_records_says_what_a_file_holds_without_preparing_it(tmp_path, population):
    import duckdb
    from er.source import describe
    s, p, g = population
    uid, phone = s.data.unique_id, s.columns["phone"][0][0]
    df = g.df.rename(columns={uid: "customer_no", phone: "TEL"}).astype({"TEL": "string"})
    df.loc[df.index[:5], "TEL"] = ["", " ", "\u3000", None, "12"]  # blank is missing, as a run reads it
    df["Postal Code"] = df.pop(s.columns["postal_code"][0][0])  # the field's own name, not the column the mapping names
    df = df.drop(columns=[c for alt in s.columns["postal_code"][1:] for c in alt if c in df])
    df["n"] = range(len(df))  # a number column: read as text
    df.to_parquet(tmp_path / "theirs.parquet", index=False)
    d = describe(tmp_path / "theirs.parquet", duckdb.connect(), s.columns, s.detect)
    blank = lambda x: x.isna() | x.astype("string").str.fullmatch("[ \t\n\r\u3000]*").fillna(True)
    assert d["records"] == len(df) and {c["column"]: round(c["filled"], 9) for c in d["columns"]} == {c: round(1 - blank(df[c]).mean(), 9) for c in df}
    person = next(f for f in d["fields"] if f["field"] == "person_name")
    alts = [df[a[0]].mask(blank(df[a[0]])) if len(a) == 1 else (df[a[0]].mask(blank(df[a[0]])) + df[a[1]].mask(blank(df[a[1]]))) for a in person["sources"]]
    whole = alts[0]
    for x in alts[1:]:
        whole = whole.fillna(x)
    assert math.isclose(person["filled"], whole.notna().mean()) and [x["found"] for x in person["alternatives"]] == [True] * len(alts)
    assert {x["field"]: x["column"] for x in d["suggested"]} == {"id": "customer_no", "phone": "TEL", "postal_code": "Postal Code"}  # values, values, name
    assert d["fit"]["phone"]["TEL"] > 0.9 and not next(f for f in d["fields"] if f["field"] == "phone")["sources"][0] == ["TEL"]  # suggested, not applied


def test_a_joined_alternative_whose_parts_never_fill_together_is_filled_nowhere(tmp_path):
    import duckdb
    from er.source import describe
    pd.DataFrame({"a": ["x", None, "z"], "b": [None, "y", ""]}).to_parquet(tmp_path / "f.parquet", index=False)
    d = describe(tmp_path / "f.parquet", duckdb.connect(), {"both": (("a", "b"),), "either": (("a", "b"), ("a",), ("b",))}, {})
    shares = {f["field"]: f["filled"] for f in d["fields"]}
    assert shares["both"] == 0 and shares["either"] == 1  # each row holds one of them


def test_the_file_s_contents_say_which_feature_each_column_fills(say, tmp_path, capsys, monkeypatch):
    import random
    from er.settings import compiled, features_from, load_settings
    s = load_settings()
    assert compiled(features_from(s.columns)) == {k: v for k, v in s.columns.items() if k != "entity"}  # the structure is the mapping, read back
    people = json.loads((s.paths["reference"] / "individual.json").read_text(encoding="utf-8"))
    places = json.loads((s.paths["reference"] / "addresses.json").read_text(encoding="utf-8"))
    rnd, n = random.Random(0), 400
    who, where = rnd.sample(people, n), rnd.sample(places, n)
    pd.DataFrame({  # columns named nothing a mapping knows: only their contents say what they hold
        "c1": [f"R{i:06d}" for i in range(n)], "c2": [p["surname_kana"] for p in who], "c3": [p["given_kana"] for p in who],
        "c4": [p["surname_kana"] + " " + p["given_kana"] for p in who], "c5": [p["surname"] + p["given"] for p in who],
        "c6": [f"株式会社{p['surname']}商事" for p in who], "c7": [f"{a['pref']}{a['city']}{a['town']}{rnd.randint(1, 9)}-{rnd.randint(1, 30)}" for a in where],
        "c8": ["".join(rnd.choice("abcdefgh") for _ in range(6)) for _ in range(n)],
        "c9": [a["postal"] for a in where], "c10": [a["postal"] for a in where],  # a postal code, and a copy of it
        "c11": [f"{rnd.randint(0, n // 2):010d}" for _ in range(n)],  # an address code: ten digits, shared
        "c12": [f"{rnd.randrange(10 ** 12, 10 ** 13)}" for _ in range(n)],  # a customer number
        "c13": [f"{rnd.randint(1000, 9999)}" for _ in range(n)],  # four digits, named nothing: a branch code as much as a phone
        "携帯電話": [f"090-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}" for _ in range(n)],  # named a phone, written as one
        "fax_tel": [f"03{rnd.randint(10 ** 7, 10 ** 8 - 1)}" for _ in range(n)]}).to_parquet(tmp_path / "theirs.parquet", index=False)  # a fax: no calls
    monkeypatch.chdir(tmp_path)

    say("create", "workspace", "w")
    code, d = say("load", "records", "theirs.parquet", "--workspace", "workspaces/w")
    assert code == 0 and {c: x["script"] for c, x in d["profile"].items()} == {"c1": "romaji", "c2": "kana", "c3": "kana", "c4": "kana", "c5": "kanji",
                                                                               "c6": "kanji", "c7": "kanji", "c8": "romaji", "c9": None, "c10": None,
                                                                               "c11": None, "c12": None, "c13": None, "携帯電話": None,
                                                                               "fax_tel": None}  # digits: no script
    assert {x["feature"]: x["column"] for x in d["placements"]} == {
        "ID/Record ID": "c1", "Name/Full name": "c4", "Name/Full name/Family name": "c2", "Name/Full name/Given name": "c3",
        "Name/Company name": "c6", "Address/Address": "c7", "Address/Postal code": "c9", "Address/Address code": "c11", "ID/Customer number": "c12",
        "Phone/Phone": "携帯電話"}  # named a phone, and numbers: before four digits named nothing, and never the fax
    assert next(x for x in d["placements"] if x["feature"] == "Phone/Phone")["why"].startswith("its name says phone; 100%")
    # the narrow pattern (a postal code) placed before the broad one (five digits or more), and its copy (c10) nowhere; an ID
    # mostly unique; the kanji full name (c5) waits for a kanji feature; the random text, nowhere
    assert [(x["feature"], x["script"], x["column"]) for x in d["offers"]] == [("Name/Kanji name", "kanji", "c5")]  # offered as a new feature
    code, _ = say("set", "feature", *(f"{x['feature']}={x['column']}" for x in d["placements"]), "--workspace", "workspaces/w")
    m = load_settings(columns=tmp_path / "workspaces" / "w" / "columns.toml").columns
    assert code == 0 and m["id"] == (("c1",),) and m["person_name"] == (("c4",), ("c2", "c3")) and m["given_name"] == (("c3",),)
    assert m["full_name"] == (("c4",),) and m["any_name"] == (("c4",), ("c2", "c3"), ("c6",)) and m["company_name"] == (("c6",),)
    code, e = say("set", "feature", "Name/Nickname=c8", "--workspace", "workspaces/w")
    assert code == 2 and "Name/Full name/Family name" in e["fix"]  # no such feature: the ones there are
    say("set", "feature", "Address/Address=", "--workspace", "workspaces/w")
    assert load_settings(columns=tmp_path / "workspaces" / "w" / "columns.toml").columns["address"] == ()  # no column, still declared
    assert say("describe", "records", "theirs.parquet", "--workspace", "workspaces/w")[1]["placements"][0]["feature"] == "Address/Address"  # offered again


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


def test_a_name_added_in_another_script_is_compared_beside_the_kana_one(say, tmp_path, population, capsys, monkeypatch):
    import random
    from er.config import widen
    from er.settings import added_of, beside, features_of
    from er.standardize import normalize
    s, p, g = population
    assert widen(p, []) is p  # nothing added: the same pipeline, so the same config hash
    assert normalize(pd.Series(["Tanaka Taro", "ＴＡＮＡＫＡ　ＴＡＲＯ"], dtype="string"), ("nfkc", "strip_spaces", "casefold"), s.standardize).nunique() == 1
    uid, ent, kana = s.data.unique_id, s.data.entity_id, [c for alt in s.columns["person_name"] for c in alt]
    phone, code, cif = s.columns["phone"][0][0], s.columns["address_code"][0][0], s.columns["customer_id"][0][0]
    people = json.loads((s.paths["reference"] / "individual.json").read_text(encoding="utf-8"))
    rnd = random.Random(1)
    df = g.df.merge(g.truth[[uid, ent]], on=uid)
    df["SHIMEI"] = df[ent].map({e: (lambda r: r["surname"] + r["given"])(rnd.choice(people)) for e in df[ent].unique()})  # one kanji name a person
    same = df[df[kana[0]].notna() & df[phone].notna() & df[code].notna()].groupby([ent, phone, code])[uid].apply(list)
    a, b = next(ids for ids in same if len(ids) >= 2)[:2]  # one person's two records, the same address and phone
    other = df[df[ent] != df.loc[df[uid] == a, ent].iloc[0]].iloc[0]
    df.loc[df[uid] == a, kana] = other[kana].to_numpy()  # renamed in kana (a new surname, a reading misheard); its customer number gone
    df.loc[df[uid] == a, cif] = None
    df.drop(columns=[ent]).to_parquet(tmp_path / "theirs.parquet", index=False)
    monkeypatch.chdir(tmp_path)

    joined = lambda w: (lambda gold: gold.loc[a, "cluster_id"] == gold.loc[b, "cluster_id"])(pd.read_parquet(tmp_path / "workspaces" / w / "gold.parquet").set_index(uid))
    for w in ("kana", "kanji"):
        say("create", "workspace", w)
        (tmp_path / "workspaces" / w / "method.toml").unlink()  # the method as tuned: this is about matching, not the trust line
        say("load", "records", "theirs.parquet", "--workspace", f"workspaces/{w}")
    code_, e = say("add", "feature", "Name/Kanji name", "--type", "person name", "--script", "kanji", "--column", "SHIMEI", "--workspace", "workspaces/kanji")
    assert code_ == 0 and "Name/Kanji name" in [x["feature"] for x in e["slots"]]
    assert beside(added_of("workspaces/kanji")) == [("person_name_2", "person_name"), ("given_name_2", "given_name")]
    assert any(f.get("added") for f in features_of("workspaces/kanji")[1]["features"]) and not added_of("workspaces/kana")
    assert say("resolve", "records", "--workspace", "workspaces/kana")[0] == 0 and not joined("kana")  # kana alone: the names disagree
    assert say("resolve", "records", "--workspace", "workspaces/kanji")[0] == 0 and joined("kanji")  # the kanji name agrees: one person
    run = json.loads((tmp_path / "workspaces" / "kanji" / "steps.json").read_text(encoding="utf-8"))["runs"][0]
    found = {x["name"]: x["pairs"] for x in next(x for x in run["steps"] if x["step"] == "candidates")["generators"]}
    assert any(n.endswith("@person_name_2") and v for n, v in found.items())  # pairs are found on the kanji name too
    gold = pd.read_parquet(tmp_path / "workspaces" / "kanji" / "gold.parquet")
    assert gold["kind"].equals(pd.read_parquet(tmp_path / "workspaces" / "kana" / "gold.parquet")["kind"])  # any_name stays kana: kinds unchanged
    code_, e = say("add", "feature", "Address/Old address", "--type", "person name", "--workspace", "workspaces/kanji")
    assert code_ == 2  # only Name takes a feature here
    say("remove", "feature", "Name/Kanji name", "--workspace", "workspaces/kanji")
    assert not added_of("workspaces/kanji") and "person_name_2" not in (tmp_path / "workspaces" / "kanji" / "columns.toml").read_text(encoding="utf-8")


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


def test_a_file_loads_as_it_comes_and_a_run_reads_the_repairs_people_accept(say, tmp_path, population, capsys, monkeypatch):
    from er import intake
    s, p, g = population
    uid, name, address = s.data.unique_id, "FULL_NAME_KANA", "ORIGINAL_ADDRESS"
    monkeypatch.chdir(tmp_path)

    df = g.df.astype("string")
    cp932, spilled, garbled = dirty_csv(df, name, address, tmp_path / "dirty.csv")
    assert say("create", "workspace", "w")[0] == 0
    w = Path("workspaces/w")
    code, e = say("load", "records", tmp_path / "dirty.csv", "--workspace", w)
    assert code == 0 and e["read"]["waiting"] == {"realign": 1, "garbled": 1} and e["read"]["decoded"]["cp932"] == cp932 and e["read"]["rows"] == len(df) - 1
    assert {x["after"] for x in e["read"]["examples"]["realign"]} == {spilled[1]} and e["read"]["examples"]["garbled"][0]["after"] == garbled[1]
    assert e["next"][0]["command"].startswith("nayose accept repairs") and say("describe", "workspace", w)[1]["inputs"][0]["waiting"] == 2
    assert say("resolve", "records", "--workspace", w)[0] == 0 and len(pd.read_parquet(w / "gold.parquet")) == len(df) - 1  # the row that waits is unread

    code, e = say("accept", "repairs", "realign", "--workspace", w)
    assert code == 0 and e["added"] == 1 and e["read"]["waiting"] == {"garbled": 1} and "rerun records" in e["next"][0]["command"]
    assert say("accept", "repairs", "realign", "--workspace", w)[0] == 2  # nothing of that kind waits now
    assert say("rerun", "records", "--workspace", w)[0] == 0  # it finds the file it read before, now repaired
    gold = pd.read_parquet(w / "gold.parquet")
    assert len(gold) == len(df) and spilled[0] in set(gold[uid])
    assert say("accept", "repairs", "garbled", "--part", "0001", "--workspace", w)[0] == 0
    read = pd.read_parquet(w / "inputs" / "0001-dirty" / intake.READ / "dirty.csv.parquet").set_index(uid)
    assert read.loc[garbled[0], name] == garbled[1] and read.loc[spilled[0], address] == spilled[1]
    code, e = say("add", "records", w / "inputs" / "0001-dirty", "--workspace", w)  # its records, repaired since the run: added as a batch
    assert code == 0 and e["summary"][0][0] == "nothing new" and (w / "inputs" / "0001-dirty").is_dir()  # a file loaded before is never removed
    assert say("rerun", "records", "--workspace", w)[0] == 0

    (tmp_path / "decisions.csv").write_text(f"{uid}_l,{uid}_r,decision\n{df[uid][0]},{df[uid][1]},match,extra\n", encoding="utf-8")  # people's file, a field too many
    code, e = say("apply", "decisions", "--file", tmp_path / "decisions.csv", "--workspace", w)
    assert code == 2 and "decisions.csv" in e["error"] and "nayose-" not in e["error"]  # refused, said of their file


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


def test_a_load_says_how_far_it_has_read_and_the_workspace_keeps_how_long_it_took(tmp_path, monkeypatch, capsys):
    from er import cli, intake
    monkeypatch.setattr(intake, "CHUNK", 2)  # a progress each two rows
    pd.DataFrame({"ID": [f"R{i}" for i in range(5)], "NAME": ["ヤマダタロウ"] * 5}).to_parquet(tmp_path / "a.parquet", index=False)
    (tmp_path / "b.csv").write_text("ID,NAME\n" + "".join(f"S{i},スズキ\n" for i in range(5)), encoding="utf-8")
    assert cli.main(["create", "workspace", "w", "--home", str(tmp_path), "--format", "json"]) == 0
    for f in ("a.parquet", "b.csv"):  # Parquet counts its rows; text, its lines
        capsys.readouterr()
        assert cli.main(["load", "records", str(tmp_path / f), "--workspace", str(tmp_path / "w"), "--format", "json"]) == 0
        events = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
        assert [(e["done"], e["total"]) for e in events if e["event"] == "progress"] == [(2, 5), (4, 5), (5, 5)], f
    (tmp_path / "c.csv").write_bytes(b"ID,NOTE\n" + b"".join(b'T%d,"two\nlines"\n' % i for i in range(3)))  # a newline inside a value: more lines than rows
    capsys.readouterr()
    assert cli.main(["load", "records", str(tmp_path / "c.csv"), "--workspace", str(tmp_path / "w"), "--format", "json"]) == 0
    progress = [(e["done"], e["total"]) for e in map(json.loads, capsys.readouterr().out.splitlines()) if e["event"] == "progress"]
    assert progress[-1] == (3, 3) and all(t > 0 for _, t in progress)  # counted on, then done at the rows it holds, whatever the estimate said
    capsys.readouterr()
    assert cli.main(["describe", "workspace", str(tmp_path / "w"), "--format", "json"]) == 0
    inputs = json.loads(capsys.readouterr().out.splitlines()[-1])["inputs"]
    assert [x["columns"] for x in inputs] == [2, 2, 2] and all(x["seconds"] >= 0 for x in inputs)  # this machine's pace, for the page's estimate of a run


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


def test_a_part_s_description_is_kept_and_made_again_only_when_what_it_rests_on_changes(tmp_path, monkeypatch, capsys):
    from er import cli, folder, hints
    pd.DataFrame({"CONT_ID": [f"R{i}" for i in range(6)], "TEL": ["0312345678"] * 6, "NAME": ["ヤマダタロウ", "サトウハナコ"] * 3}).to_parquet(tmp_path / "a.parquet", index=False)
    ws = tmp_path / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(tmp_path), "--format", "json"]) == 0
    assert cli.main(["load", "records", str(tmp_path / "a.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    part = str(folder.parts(ws)[0])
    made, real = [], cli.described
    monkeypatch.setattr(cli, "described", lambda a: made.append(1) or real(a))

    def describe() -> dict:
        capsys.readouterr()
        assert cli.main(["describe", "records", part, "--workspace", str(ws), "--format", "json"]) == 0
        return json.loads(capsys.readouterr().out.splitlines()[-1])
    kept = describe()
    assert not made and kept["records"] == 6  # as the load left it: no record read
    assert cli.main(["set", "feature", "Phone/Phone=TEL", "--workspace", str(ws), "--format", "json"]) == 0
    fresh = describe()
    assert made == [1] and fresh["slots"] != kept["slots"]  # the mapping changed: described again
    assert describe() == fresh and made == [1]  # and kept again
    (Path(part) / hints.KEPT).write_text(json.dumps({"key": "other", "described": {}}), encoding="utf-8")
    assert describe() == fresh and made == [1, 1]  # a description kept for something else is never given
    (ws / "method.toml").write_text('drop_rules = ["X1_CIF_PERSON_NAME"]\n', encoding="utf-8")  # a method adopted: what a run would turn off may change
    describe()
    assert made == [1, 1, 1]
    (Path(part) / hints.KEPT).write_text("{not json", encoding="utf-8")  # a kept copy cut short: made again, never a failure
    describe()
    assert made == [1, 1, 1, 1] and json.loads((Path(part) / hints.KEPT).read_text(encoding="utf-8"))["key"]


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


def test_a_part_s_columns_are_described_once_and_a_mapping_reads_only_what_it_changes_the_same_numbers_out(tmp_path, monkeypatch, capsys, population):
    from er import cli, folder, hints, source
    s, p, g = population
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    ws = tmp_path / "w"
    assert cli.main(["create", "workspace", "w", "--home", str(tmp_path), "--format", "json"]) == 0
    assert cli.main(["load", "records", str(tmp_path / "all.parquet"), "--workspace", str(ws), "--format", "json"]) == 0
    part = folder.parts(ws)[0]
    sampled = []
    real = source.profiled
    monkeypatch.setattr(source, "profiled", lambda *a: sampled.append(1) or real(*a))  # the columns profiled: their sample read

    def describe(fresh: bool = False) -> dict:  # fresh: nothing kept, every number made again
        (part / hints.KEPT).unlink(missing_ok=True)
        if fresh:
            (part / source.COLUMNS_KEPT).unlink(missing_ok=True)
        capsys.readouterr()
        assert cli.main(["describe", "records", "--workspace", str(ws), "--format", "json"]) == 0
        return json.loads(capsys.readouterr().out.splitlines()[-1])
    phone = s.columns["phone"][0][0]
    first = describe()
    assert (part / source.COLUMNS_KEPT).is_file() and (part / source.SAMPLE_KEPT).is_file() and not sampled  # kept with the part since it loaded
    for mapping in (f"Phone/Phone={phone},{s.columns['customer_id'][0][0]}", "Phone/Phone=", f"Phone/Phone={phone}"):
        assert cli.main(["set", "feature", mapping, "--workspace", str(ws), "--format", "json"]) == 0
        sampled.clear()
        kept = describe()
        assert not sampled and kept == describe(fresh=True) and sampled == [1]  # its sample never read again, and the same numbers as made from nothing
    monkeypatch.setattr(source, "CODE", "another")  # what describes the columns changed: described again, never read back
    sampled.clear()
    assert describe() == describe(fresh=True) and sampled == [1, 1]
    (part / source.COLUMNS_KEPT).write_text("{cut short", encoding="utf-8")  # a kept copy unreadable: made again, never a failure
    assert describe()["records"] == first["records"]


def test_a_load_says_its_columns_then_its_first_rows_counted_before_its_result(tmp_path, capsys):
    from er import cli
    uid = load_settings().data.unique_id
    rows = [f"{uid},FULL_NAME_KANA,TEL"] + [f"{i:04d},{'ヤマダタロウ' if i % 3 else ''},{'NULL' if i % 4 == 0 else 1000 + i}" for i in range(40)]
    (tmp_path / "r.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert cli.main(["create", "workspace", "w", "--home", str(tmp_path), "--format", "json"]) == 0
    capsys.readouterr()
    assert cli.main(["load", "records", str(tmp_path / "r.csv"), "--workspace", str(tmp_path / "w"), "--format", "json"]) == 0
    events = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    early = [e["early"] for e in events if e["event"] == "line" and "early" in e]
    result = events[-1]
    assert result["event"] == "result" and [d["records"] for d in early] == [None, 40]  # the names at once, then the first chunk counted, then the result
    assert [c["column"] for c in early[0]["columns"]] == [c["column"] for c in result["columns"]] and all(c["filled"] is None for c in early[0]["columns"])
    assert [(c["column"], c["filled"]) for c in early[1]["columns"]] == [(c["column"], c["filled"]) for c in result["columns"]]  # one chunk: its counts are the file's
    assert {s["feature"]: s["filled"] for s in early[1]["slots"] if s["filled"] is not None} == {s["feature"]: s["filled"] for s in result["slots"] if s["filled"] is not None}


def test_only_a_records_file_is_read_whole_and_as_it_was_written(say, tmp_path):
    from er import folder, intake
    from er.details import _forms
    from er.settings import load_settings, set_features
    from er.source import answers
    from er.strings import connect
    uid = load_settings().data.unique_id
    home, ws = tmp_path / "home", tmp_path / "home" / "w"
    assert say("create", "workspace", "w", "--home", home)[0] == 0
    (tmp_path / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (tmp_path / "walk.py").write_text("import json, os\nprint(1)\n", encoding="utf-8")
    (tmp_path / "shot.csv").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)  # a picture named as a CSV
    for f in ("shot.png", "walk.py", "shot.csv"):
        code, e = say("load", "records", tmp_path / f, "--workspace", ws)
        assert code == 2 and ("not a records file" in e["error"] or "a PNG image" in e["error"]), f
    with pytest.raises(InputError, match="not a records file"):
        folder.receive(ws, "walk.py", 10, lambda n: b"x" * n)
    assert not (ws / folder.UPLOADS).exists() or not list((ws / folder.UPLOADS).iterdir())  # refused before a byte is written
    code, e = say("load", "records", home, "--workspace", ws)  # a folder that holds the workspace itself
    assert code == 2 and "holds this workspace" in e["error"] and not folder.parts(ws)
    (tmp_path / "given" / "read").mkdir(parents=True)
    (tmp_path / "given" / "a.csv").write_text(f"{uid},FULL_NAME_KANA\n0001,ヤマダタロウ\n", encoding="utf-8")
    (tmp_path / "given" / "read" / "b.csv").write_text(f"{uid},FULL_NAME_KANA\n0002,スズキハナコ\n", encoding="utf-8")
    code, e = say("load", "records", tmp_path / "given", "--workspace", ws)
    assert code == 2 and "named as the workspace's own reading" in e["error"]

    (tmp_path / "r.csv").write_text(f"{uid},FULL_NAME_KANA,KANJI_NAME,TEL\n0001,ヤマダタロウ,山田太郎,1234\n", encoding="utf-8")
    assert say("load", "records", tmp_path / "r.csv", "--workspace", ws)[0] == 0
    assert say("set", "columns", "full_name=KANJI_NAME", "--workspace", ws)[0] == 0
    set_features(ws, {"Phone/Phone": (("TEL",),)})  # another feature changed: the full name set by hand stays
    assert load_settings(columns=ws / "columns.toml").columns["full_name"] == (("KANJI_NAME",),)

    forms = _forms(["0151", "151"], {"number": False, "pad": 4})
    assert forms["'151'"] == "151" and forms["'0151'"] == "0151"  # each ID's rows its own

    rows = "\r\n".join(["id,name,address", *(f"{i},タナカタロウ,東京都千代田区丸の内{i}丁目" for i in range(50))]) + "\r\n"
    (tmp_path / "wide.csv").write_bytes(rows.encode("utf-16-le"))  # UTF-16 without a BOM, mostly Japanese: few NULs
    part = tmp_path / "wide_part"
    part.mkdir()
    (part / "wide.csv").write_bytes(rows.encode("utf-16-le"))
    r = intake.take(part, {part / "wide.csv": "wide.csv"}, intake.InputSpec(), load_settings().paths["reference"], frozenset())
    got = pd.read_parquet(part / r["files"][0]["read"])
    assert got["name"].iloc[0] == "タナカタロウ" and got["address"].iloc[3] == "東京都千代田区丸の内3丁目"

    pd.DataFrame({uid: ["0001", "0002"], "kind": [" 1", "２\u3000"]}).to_parquet(tmp_path / "kinds.parquet", index=False)
    assert len(answers(tmp_path / "kinds.parquet", connect()[0], uid)) == 2  # both taken: a space or a full-width digit is no other kind

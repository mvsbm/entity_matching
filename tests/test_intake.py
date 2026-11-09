"""The reader and describe records: files as they come, repairs proposed and accepted."""
import io
import json
import math
from pathlib import Path
from dataclasses import replace

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
    assert [(x["line"], "waits" in x["reason"]) for x in unread] == [(66, True), (67, True), (69, False)] and r["unread"] == 3
    r2, rows, proposed, unread = read("dirty.csv", dirty, ("realign", "garbled"))
    assert rows.loc["903", "name"] == "新しい" and rows.loc["904", "address"] == "大阪府北区3,4番" and rows.loc["905", "phone"] == "5555"
    assert [x["line"] for x in unread] == [69] and r2["files"][0]["versions"][0] == r["files"][0]["sha256"]  # what it replaced, kept by its hash
    monkeypatch.setattr(intake, "KEEP", 1)  # past KEEP of a kind, proposals are counted, not kept; accepting still repairs them all
    r3, rows, proposed, _ = read("dirty.csv", dirty)
    assert r3["proposed"]["realign"] == 2 and [x["kind"] for x in proposed].count("realign") == 1
    r3, rows, *_ = read("dirty.csv", dirty, ("realign",))
    assert rows.loc["904", "address"] == "大阪府北区3,4番" and rows.loc["905", "phone"] == "5555"

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

"""A details file: rows about the records that people see above each one as they review, and that matching never reads."""
import subprocess
import sys
import time

import pandas as pd

from er.settings import load_settings

UID = load_settings().data.unique_id


def test_details_are_each_record_s_rows_in_the_file_s_order_found_by_its_id_whatever_its_type(say, tmp_path):
    from er import folder
    ids = [f"{i:010d}" for i in range(1, 41)]  # text, zero-padded, as a records file gives them
    pd.DataFrame({UID: ids, "FULL_NAME_KANA": ["ヤマダタロウ"] * len(ids)}).to_parquet(tmp_path / "records.parquet", index=False)
    rows = [dict(NO=int(i), PLAN=f"plan {i}-{k}", START=pd.Timestamp("2020-01-01") + pd.Timedelta(days=k)) for n, i in enumerate(ids) for k in range(n % 4)]
    given = pd.DataFrame(rows).sample(frac=1, random_state=0).reset_index(drop=True)  # the file's order is not the ID's
    given.to_parquet(tmp_path / "their_key.parquet", index=False)
    given.rename(columns={"NO": UID}).to_parquet(tmp_path / "details.parquet", index=False)  # a number where the records hold text
    assert say("create", "workspace", "w", "--home", tmp_path)[0] == 0
    ws = tmp_path / "w"
    assert say("load", "records", tmp_path / "records.parquet", "--workspace", ws)[0] == 0
    mapping, last = (ws / "columns.toml").read_bytes(), folder.last(ws)
    assert say("show", "details", ids[0], "--workspace", ws)[1]["file"] is None  # none loaded: none, at once

    code, e = say("load", "details", tmp_path / "their_key.parquet", "--workspace", ws)
    assert code == 2 and f"has no column {UID}" in e["error"] and "--key COLUMN (one of NO, PLAN, START)" in e["fix"]
    (tmp_path / "details.csv").write_text(f"{UID},PLAN\n1,a\n", encoding="utf-8")
    code, e = say("load", "details", tmp_path / "details.csv", "--workspace", ws)
    assert code == 2 and "not a Parquet file" in e["error"]

    code, e = say("load", "details", tmp_path / "details.parquet", "--workspace", ws)
    with_rows = {i for n, i in enumerate(ids) if n % 4}
    assert code == 0 and (e["rows"], e["ids"], e["key"], e["shown"]) == (len(given), len(with_rows), UID, ["PLAN", "START"])
    assert (e["linked"], e["records"]) == (len(with_rows), len(ids))
    code, e = say("load", "details", tmp_path / "their_key.parquet", "--key", "NO", "--columns", "PLAN", "--workspace", ws)  # its own name for the ID
    assert code == 0 and (e["key"], e["shown"], e["linked"]) == ("NO", ["PLAN"], len(with_rows))
    assert [f.name for f in (ws / "details").glob("rows-*.parquet")] == ["rows-2.parquet"]  # the earlier load's copy gone
    assert (ws / "columns.toml").read_bytes() == mapping and folder.last(ws) == last  # matching reads none of it: no run asked for

    asked = [ids[3], ids[0], ids[7], " " + ids[5]]  # 3 rows, none, 3, 1; given with a space
    code, e = say("show", "details", *asked, "--workspace", ws)
    assert code == 0 and e["columns"] == ["PLAN"] and [r["id"] for r in e["records"]] == [*asked[:3], asked[3]]
    for r in e["records"]:
        theirs = given[given["NO"] == int(r["id"])]
        assert r["rows"] == [[x] for x in theirs["PLAN"]] and r["total"] == len(theirs)  # every row, in the file's order

    code, e = say("set", "details", "--columns", "START", "PLAN", "--workspace", ws)
    assert code == 0 and e["shown"] == ["PLAN", "START"]  # in the file's order
    assert {r[1][:10] for r in say("show", "details", ids[3], "--workspace", ws)[1]["records"][0]["rows"]} == {"2020-01-01", "2020-01-02", "2020-01-03"}  # dates as text
    code, e = say("set", "details", "--columns", "NOPE", "--workspace", ws)
    assert code == 2 and "has no column NOPE" in e["error"]
    assert say("set", "details", "--workspace", ws)[1]["shown"] == []  # none given: none shown

    for held, refused in ((ws / ".lock", False), (ws / "details" / ".rows.lock", True)):  # a run's lock: a load goes on; another load's: refused
        holder = subprocess.Popen([sys.executable, "-c", "import sys, time\nfrom er.io import lock\nf = open(sys.argv[1], 'w')\nassert lock(f)\nprint('held', flush=True)\ntime.sleep(60)",
                                   str(held)], stdout=subprocess.PIPE, text=True)
        try:
            assert holder.stdout.readline().strip() == "held"
            t = time.time()
            code, e = say("load", "details", tmp_path / "details.parquet", "--workspace", ws)
            assert (code, "another details file" in e.get("error", "")) == ((75, True) if refused else (0, False)) and time.time() - t < 10
            assert say("set", "details", "--columns", "PLAN", "--workspace", ws)[0] == 0  # the columns shown change while either runs
        finally:
            holder.kill()
            holder.wait()


def test_details_of_several_files_keep_each_file_s_order_and_a_key_read_as_a_decimal_still_finds_its_records(say, tmp_path):
    ids = [f"{i:06d}" for i in range(1, 7)]
    pd.DataFrame({UID: ids, "FULL_NAME_KANA": ["ヤマダタロウ"] * 6}).to_parquet(tmp_path / "records.parquet", index=False)
    assert say("create", "workspace", "w", "--home", tmp_path)[0] == 0
    ws = tmp_path / "w"
    (parts := tmp_path / "contracts").mkdir()
    pd.DataFrame({UID: [2.0, 1.0, None, 2.0], "PLAN": ["b1", "a1", "lost", "b2"]}).to_parquet(parts / "1.parquet", index=False)  # a number key with a missing value: a decimal
    pd.DataFrame({UID: [1.0, 2.0], "PLAN": ["a2", "b3"]}).to_parquet(parts / "2.parquet", index=False)
    code, e = say("load", "details", parts / "*.parquet", "--workspace", ws)  # before the records: none counted yet
    assert code == 0 and (e["file"], e["rows"], e["unkeyed"], e["linked"]) == ("contracts", 5, 1, None)
    code, e = say("show", "details", ids[1], ids[0], "--workspace", ws)
    assert [r["rows"] for r in e["records"]] == [[["b1"], ["b2"], ["b3"]], [["a1"], ["a2"]]]  # each file's rows in its order, then the next file's
    assert say("load", "records", tmp_path / "records.parquet", "--workspace", ws)[0] == 0
    d = say("describe", "workspace", ws)[1]["details"]
    assert (d["linked"], d["records"]) == (2, 6)  # counted once the records came
    pd.DataFrame({UID: ids[:2], "FULL_NAME_KANA": ["ヤマダタロウ"] * 2}).to_parquet(tmp_path / "fewer.parquet", index=False)
    assert say("load", "records", tmp_path / "fewer.parquet", "--workspace", ws)[0] == 0
    assert say("describe", "workspace", ws)[1]["details"]["records"] == 2  # counted again in the file given last

    for own in ("__key", "file_row_number"):
        pd.DataFrame({UID: [1], own: ["x"]}).to_parquet(tmp_path / "own.parquet", index=False)
        code, e = say("load", "details", tmp_path / "own.parquet", "--workspace", ws)
        assert code == 2 and f"has a column named {own}" in e["error"]

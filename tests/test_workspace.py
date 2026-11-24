"""Runs' folders: their files, the match tables and people's decisions."""
from pathlib import Path
import math
import os
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from er.config import (InputError)
from er.match import exact_u, stale_u
from er.settings import load_settings


@pytest.fixture(scope="module")
def wide_band(population):
    """The final pipeline with a wide safety margin (four grid steps) and its threshold three steps up, so the margin holds
    pairs to decide on a small population."""
    s, p, g = population
    return s, replace(p, threshold=replace(p.threshold, margin_steps=4), fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 6)), g


def test_a_pair_with_no_name_compared_is_offered_saying_so(tmp_path, population):
    """A company at a person's address with the person's phone: each record lacks the other's name field, so no name
    is compared, and address and phone alone reach the threshold. The match table offers it, named false: people see
    that no name was compared."""
    from er.jobs.build import build
    from er.jobs.match import match
    s, p, g = population
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    home = g.df[g.df[["FULL_NAME_KANA", "PHONE_NUM_4", "SOURCE_ADDR_CD", "STD_ADDRESS"]].notna().all(axis=1)].iloc[0]
    firm = home.copy()
    firm[["FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA", "CIF_ID", "BIRTH_DATE"]] = pd.NA
    firm[[uid, "NYS_CNV_P_NAME_KANA"]] = ["9" * len(home[uid]), "カブシキガイシャテスト"]
    pd.concat([g.df, firm.to_frame().T.astype(g.df.dtypes)], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    pair = (home[uid], firm[uid])
    run = build(tmp_path / "all.parquet", tmp_path / "a", s, replace(p, fs=replace(p.fs, needs=("name", "company"))))
    assert run.engine.value(f'SELECT match_weight FROM scores WHERE "{l}" = ? AND "{r}" = ?', list(pair)) >= 4.0
    table = pd.read_parquet(match(tmp_path / "a", s, p, 4.0)["into"])
    row = table[(table[l] == pair[0]) & (table[r] == pair[1])]
    assert len(row) == 1 and not row["named"].any()


def test_decisions_on_a_match_table_join_records_and_a_full_run_applies_them_again(tmp_path, wide_band):
    from er.jobs.build import build
    from er.jobs.decide import decide
    from er.jobs.match import match
    s, p, g = wide_band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = build(tmp_path / "all.parquet", tmp_path / "a", s, p)
    table = pd.read_parquet(match(tmp_path / "a", s, p, p.fs.min_match_weight)["into"])
    yes, no = table.index[0], table.index[1]
    table.loc[yes, "decision"], table.loc[no, "decision"] = "match", " No_Match "  # as people return it; undecided rows are skipped
    table.to_parquet(tmp_path / "reviewed.parquet")
    decide(tmp_path / "reviewed.parquet", tmp_path / "a", s, p)
    after = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    pair, rejected = table.loc[yes, [l, r]].tolist(), table.loc[no, [l, r]].tolist()
    assert after.loc[pair[0], "cluster_id"] == after.loc[pair[1], "cluster_id"] and after.loc[pair[0], "resolved_by"] == "review"
    assert after["cluster_id"].nunique() == len(after) - 1 and len(pd.read_parquet(tmp_path / "a" / "decisions")) == 2

    build(tmp_path / "all.parquet", tmp_path / "a", s, p, model=run.model, overwrite=True)  # people's work survives
    again = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    assert again.loc[pair[0], "cluster_id"] == again.loc[pair[1], "cluster_id"]
    offered = pd.read_parquet(match(tmp_path / "a", s, p, p.fs.min_match_weight)["into"])
    assert not ((offered[l] == rejected[0]) & (offered[r] == rejected[1])).any() and len(offered) == len(table) - 1  # a pair people rejected: offered no more

    table.loc[yes, "decision"] = "maybe"
    table.to_parquet(tmp_path / "bad.parquet")
    with pytest.raises(ValueError, match="match or no_match"):
        decide(tmp_path / "bad.parquet", tmp_path / "a", s, p)
    pd.DataFrame({l: ["nobody"], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "unknown.parquet")
    with pytest.raises(ValueError, match="IDs that name no record of the run"):
        decide(tmp_path / "unknown.parquet", tmp_path / "a", s, p)
    pd.DataFrame({l: [None], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "blank.parquet")
    with pytest.raises(ValueError, match="decided rows lack an ID"):  # it would decide a pair of one record with itself
        decide(tmp_path / "blank.parquet", tmp_path / "a", s, p)


def test_a_pipeline_with_a_trust_line_is_refused():
    from er.config import pipeline_from, toml_of
    s = load_settings()
    with pytest.raises(InputError, match=r"\[trust\] sets nothing"):
        pipeline_from(toml_of(s.root / "config" / "pipeline.toml") | {"trust": {"steps": [12.0]}}, s.standardize, s.chains)


def test_an_increment_counts_exact_u_again_and_samples_only_a_drifted_comparison(tmp_path, population, monkeypatch):
    import json
    import er.match as M
    from er.jobs.build import build
    from er.jobs.update import update
    s, p, g = population
    new = np.random.default_rng(1).random(len(g.df)) < 0.1
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    full = build(tmp_path / "old.parquet", tmp_path / "c", s, p)
    basis = json.loads((tmp_path / "c" / "state" / "scoring.json").read_text(encoding="utf-8"))["basis"]
    model = p.fs.model
    same = stale_u(model, basis, {name: b["exact"] for name, b in basis.items()}, full.n)
    assert all(x["drift_bits"] == 0 for x in same.values())  # nothing moved: nothing is stale
    halved = {name: {k: v / (2 if name == "name" else 1) for k, v in b["exact"].items()} for name, b in basis.items()}
    moved = stale_u(model, basis, halved, full.n)
    assert moved["name"]["drift_bits"] == pytest.approx(1) and all(x["drift_bits"] == 0 for k, x in moved.items() if k != "name")
    assert stale_u(model, {}, {}, full.n)["name"]["drift_bits"] == math.inf  # never sampled: sample it

    sampled, real = [], M.sample_u
    monkeypatch.setattr(M, "sample_u", lambda m, comps, *a: sampled.extend(c.name for c in comps) or real(m, comps, *a))
    inc = update(tmp_path / "new.parquet", tmp_path / "c", s, p)
    after = json.loads((tmp_path / "c" / "state" / "scoring.json").read_text(encoding="utf-8"))["basis"]
    stale = [k for k, b in after.items() if b["last_check"]["drift_bits"] > (b["last_check"]["se_bits"] or math.inf)]
    assert sampled == stale  # sampled again exactly where drift outgrew the sampling error
    exact = exact_u(model, "records", inc.engine)  # the exact levels are always counted on every record
    for c in inc.scoring["comparisons"]:
        for lv in c["comparison_levels"]:
            if lv.get("label_for_charts") in exact.get(c["output_column_name"], {}):
                assert lv["u_probability"] == pytest.approx(exact[c["output_column_name"]][lv["label_for_charts"]])


def test_the_loader_reads_parquet_by_column_name_and_says_what_is_wrong(tmp_path, engine, monkeypatch):
    from er.source import open_source
    pd.DataFrame({"cont_id": ["1", "2"], "Phone-Num 4": [599, 1234], "x": ["a", "b"]}).to_parquet(tmp_path / "a.parquet", index=False)
    pd.DataFrame({"CONT_ID": ["3"], "y": ["c"]}).to_parquet(tmp_path / "b.parquet", index=False)
    src = open_source(tmp_path / "a.parquet", engine, ["CONT_ID", "PHONE_NUM_4"])  # case, width and separators aside
    assert src.columns == ["CONT_ID", "PHONE_NUM_4", "x"]
    assert engine.rows(f"SELECT PHONE_NUM_4 FROM {src.sql}") == [("599",), ("1234",)]  # text, zeros lost upstream
    assert any("read as CONT_ID" in x for x in src.notes) and any("stored as a number" in x for x in src.notes)
    both = open_source(tmp_path / "*.parquet", engine, ["CONT_ID"])  # a glob: read together by column name
    assert engine.value(f"SELECT count(*) FROM {both.sql}") == 3 and any("lacks" in x for x in both.notes)

    with pytest.raises(InputError, match="no file matches") as e:
        open_source(tmp_path / "aa.parquet", engine, [])
    assert "a.parquet" in e.value.fix  # did you mean
    pd.DataFrame({"CONT_ID": ["1"], "KIND": ["Person"], "Phone": ["x"], "phone__x": ["y"], "kind_2": ["z"]}).to_parquet(tmp_path / "k.parquet")
    named = open_source(tmp_path / "k.parquet", engine, ["CONT_ID"], reserved=["kind", "phone"])  # names the run writes itself, in another case
    assert named.columns == ["CONT_ID", "KIND_3", "Phone_2", "phone__x_2", "kind_2"] and any("column KIND read as KIND_3" in n for n in named.notes)
    for d in ("a", "b"):  # a folder named from the home folder: every file in it, kept apart
        (tmp_path / "home" / "exports" / d).mkdir(parents=True)
        pd.DataFrame({"CONT_ID": [f"{d}{i}" for i in range(3)]}).to_parquet(tmp_path / "home" / "exports" / d / "part.parquet")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Windows' home folder
    from er import intake
    from er.source import readable
    with readable("~/exports", intake.InputSpec()) as part:
        assert intake.report(Path(part))["rows"] == 6
    (tmp_path / "empty").mkdir()
    with pytest.raises(InputError, match="holds no Parquet file"):  # a folder with no records file: said so, not "did you mean" itself
        open_source(tmp_path / "empty", engine, [])
    (tmp_path / "c.parquet").write_text("CONT_ID,name\n1,x\n", encoding="utf-8")
    with pytest.raises(InputError, match="looks like text"):
        open_source(tmp_path / "c.parquet", engine, [])
    (tmp_path / "d.parquet").write_bytes((tmp_path / "a.parquet").read_bytes()[:-10])
    with pytest.raises(InputError, match="cut short"):
        open_source(tmp_path / "d.parquet", engine, [])
    pd.DataFrame({"cont_id": ["1"], "CONT-ID": ["2"]}).to_parquet(tmp_path / "e.parquet", index=False)
    with pytest.raises(InputError, match="could each be CONT_ID"):
        open_source(tmp_path / "e.parquet", engine, ["CONT_ID"])
    pd.DataFrame({"cont_id": ["1"], "CONT_ID_2": ["2"]}).to_parquet(tmp_path / "f.parquet", index=False)  # as intake reads cont_id,CONT_ID: the second renamed
    with pytest.raises(InputError, match="could each be CONT_ID"):  # never the lowercase one read as CONT_ID
        open_source(tmp_path / "f.parquet", engine, ["CONT_ID"])


def test_a_run_sets_aside_what_it_cannot_resolve_and_suggests_a_mapping(tmp_path, population):
    from er.steps.job import start
    from er.steps.load import load
    from er.jobs.build import build
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    df = pd.concat([df, df.iloc[[0]], df.iloc[[1]].assign(PHONE_NUM_4="9999")], ignore_index=True)  # an exact copy; a clash
    df.loc[2, uid], df.loc[3, uid], df.loc[4, uid], df.loc[5, uid] = " ", "\t", "\xa0", "\u3000"  # no ID: blank in any of its forms
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = build(tmp_path / "in.parquet", tmp_path / "run", s, p)
    aside = pd.read_parquet(tmp_path / "run" / "set_aside")
    assert sorted(aside["reason"]) == ["no ID"] * 4 + ["the same ID with different content"] * 2
    assert run.n == len(g.df) - 5 and any("kept once" in x for x in run.notes)

    g.df.rename(columns={uid: "customer_no"}).to_parquet(tmp_path / "renamed.parquet", index=False)
    with pytest.raises(InputError, match="lacks a field every run needs") as e:
        load(start(s, p), tmp_path / "renamed.parquet")
    assert 'id = "customer_no"' in e.value.fix  # suggested from its values: filled and unique


@pytest.mark.skipif(os.name == "nt", reason="Linux's mount table and its paths: on Windows every folder is a disk (io.object_store)")
def test_a_workspace_on_object_storage_is_refused_and_one_on_a_disk_is_not(tmp_path, monkeypatch):
    from er import folder, io
    root = tmp_path.resolve()
    mounts = tmp_path / "mountinfo"
    mounts.write_text("\n".join(["22 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw",
                                  f"40 22 0:50 / {root}/bucket rw,nosuid - fuse.gcsfuse my-bucket rw",
                                  f"41 22 0:51 / {root}/my\\040share rw - nfs4 server:/export rw",  # a space, as mountinfo writes it
                                  f"42 40 0:52 / {root}/bucket/disk rw - ext4 /dev/sdb1 rw",
                                  f"43 22 0:53 / {root}/over rw - tmpfs tmpfs rw",
                                  f"44 43 0:54 / {root}/over rw - fuse.s3fs s3fs rw"]) + "\n", encoding="utf-8")  # a bucket mounted over a disk: the bucket
    monkeypatch.setattr(io, "MOUNTS", mounts)
    with pytest.raises(InputError, match=r"object storage \(gcsfuse\)"):
        with folder.run_lock(root / "bucket" / "w"):
            pass
    assert not (root / "bucket" / "w").exists()  # refused before anything is written
    assert io.object_store(root / "over" / "w") == "s3fs"
    for disk in (root / "my share" / "w", root / "local" / "w", root / "bucket" / "disk" / "w"):  # NFS, a local disk, a disk mounted inside the bucket
        with folder.run_lock(disk, make=True):
            pass
    monkeypatch.setattr(io, "MOUNTS", tmp_path / "none")  # no mountinfo (macOS, Windows): every folder a disk
    assert io.object_store(root / "bucket") is None


def test_people_s_latest_decision_stands_a_file_given_twice_changes_nothing_and_a_full_run_reads_them_back(say, tmp_path, population, monkeypatch):
    from er.engine.duckdb import connect
    from er.folder import latest_decisions
    s, p, g = population
    uid, ent = s.data.unique_id, s.data.entity_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "theirs.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    ws, at = tmp_path / "workspaces" / "w", ("--out", "workspaces/w")
    truth = g.truth.set_index(uid)[ent]
    latest = lambda a, b: dict(((x, y), d) for x, y, d in connect().rows(f"SELECT * FROM {latest_decisions(connect(), ws, uid)}")).get((a, b))
    assert say("build", "theirs.parquet", *at)[0] == 0
    made = say("match", *at, "--threshold", "6")[1]
    table = pd.read_parquet(made["into"])
    same = table[table[l].map(truth) == table[r].map(truth)].iloc[0]
    pd.DataFrame({l: [same[l]], r: [same[r]], "decision": ["match"]}).to_parquet(tmp_path / "same.parquet")
    pd.DataFrame({l: [same[l]], r: [same[r]], "decision": ["no_match"]}).to_parquet(tmp_path / "other.parquet")  # another person: different
    assert say("decide", "same.parquet", *at)[1]["matches"] == 1 and latest(same[l], same[r]) == "match"
    assert say("decide", "same.parquet", *at)[1]["decisions"] == 0  # given twice: nothing new
    assert say("decide", "other.parquet", *at)[0] == 0 and latest(same[l], same[r]) == "no_match"  # the latest stands
    assert say("build", "theirs.parquet", *at, "--overwrite")[0] == 0  # a full run reads people's decisions back
    again = pd.read_parquet(say("match", *at, "--threshold", "6")[1]["into"])
    assert not ((again[l] == same[l]) & (again[r] == same[r])).any() and len(again) == made["pairs"] - 1  # said different: offered no more
    gold = pd.read_parquet(ws / "gold.parquet").set_index(uid)["cluster_id"]
    assert gold[same[l]] != gold[same[r]] and latest(same[l], same[r]) == "no_match"

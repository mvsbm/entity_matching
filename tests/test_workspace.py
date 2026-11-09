"""Workspaces: their own mapping and files, the review sheet, decisions, the method and the trust line."""
import json
import math
from pathlib import Path
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from er.candidates import Records, estimate_touching, generate
from er.config import (DeletionKeys, InputError, Key, KeyBlocker, Rule)
from er.match import exact_u, stale_u
from er.config import load_pipeline
from er.settings import load_settings



@pytest.fixture(scope="module")
def wide_band(population):
    """The final pipeline with a wide safety margin (four grid steps) and its threshold three steps up, so the margin holds
    pairs to decide on a small population."""
    s, p, g = population
    return s, replace(p, threshold=replace(p.threshold, margin_steps=4), fs=replace(p.fs, min_match_weight=p.fs.min_match_weight + 6)), g


def test_a_workspace_keeps_its_own_mapping_and_a_copy_of_its_files(say, tmp_path, population, capsys, monkeypatch):
    import threading
    from er import folder
    from er.settings import settings_path
    from er.intake import sha256
    s, p, g = population
    g.df.rename(columns={s.data.unique_id: "customer_no"}).to_parquet(tmp_path / "theirs.parquet", index=False)  # their own ID column
    monkeypatch.chdir(tmp_path)  # workspaces/, in the folder nayose starts from
    project = settings_path().read_text(encoding="utf-8")

    assert say("create", "workspace", "a")[0] == 0 and say("create", "workspace", "b")[0] == 0
    assert say("create", "workspace", "a")[0] == 2 and say("create", "workspace", "../x")[0] == 2  # taken; not a name
    (tmp_path / "workspaces" / "notes").mkdir()  # a folder that is no workspace
    assert {w["name"] for w in say("list", "workspaces")[1]["workspaces"]} == {"a", "b"}
    a, b = Path("workspaces/a"), Path("workspaces/b")

    code, e = say("load", "records", "theirs.parquet", "--workspace", a)  # copied, then described: the ID is not where the mapping looks
    assert code == 0 and [(x["field"], x["column"]) for x in e["suggested"]] == [("id", "customer_no")]
    code, e = say("check", "records", a / "inputs" / "0001-theirs", "--workspace", a)  # the full check stops, and says the line to run
    assert code == 2 and e["hints"] == {"id": "customer_no"} and "set columns id=customer_no --workspace" in e["fix"]
    assert folder.sums(a / "inputs" / "0001-theirs") == {"theirs.parquet": sha256(tmp_path / "theirs.parquet")}
    say("load", "records", "theirs.parquet", "--workspace", a)
    assert [x.name for x in folder.parts(a)] == ["0001-theirs"]  # the same content again: not copied again
    assert say("set", "columns", "id=customer_no", "--workspace", a)[0] == 0
    assert settings_path().read_text(encoding="utf-8") == project and 'id = "CONT_ID"' in (b / "columns.toml").read_text(encoding="utf-8")  # a's alone
    code, e = say("resolve", "records", "--workspace", b)
    assert code == 2 and e["error"].startswith("no records file")
    assert say("resolve", "records", "--workspace", a)[1]["summary"][0][1].startswith(f"{len(g.df):,}")  # the file loaded last
    (tmp_path / "theirs.parquet").unlink()
    assert say("rerun", "records", "--workspace", a)[0] == 0  # its own copy: the original may go
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")  # another folder: the paths steps.json holds lead nowhere, its inputs/ still holds them
    assert say("rerun", "records", "--workspace", tmp_path / a)[0] == 0
    monkeypatch.chdir(tmp_path)
    d = say("describe", "workspace", a)[1]
    assert d["columns"] == "own" and [(x["name"], x["read"]) for x in d["inputs"]] == [("0001-theirs", True)]
    assert say("describe", "workspace", b)[1]["records"] == 0  # nothing run yet: no error
    assert say("describe", "workspace", "workspaces/none")[0] == 2

    for n, rows in (("one", g.df.iloc[:10]), ("two", g.df.iloc[10:20])):
        rows.to_parquet(tmp_path / f"{n}.parquet", index=False)
    said = []

    def take(n: str) -> None:
        try:
            said.append(folder.take_in(b, tmp_path / f"{n}.parquet", s.input, s.paths["reference"])[0].name)
        except folder.Busy:  # one writer at a time: the others are told to try again
            said.append("busy")
    given = [threading.Thread(target=take, args=(n,)) for n in ("one", "two", "one")]  # at once
    [t.start() for t in given]
    [t.join(60) for t in given]
    assert not any(t.is_alive() for t in given)
    for n in ("one", "two"):  # tried again, one at a time
        take(n)
    names = [x.name for x in folder.parts(b)]
    assert "busy" in said or len(set(said)) < 3  # they met
    assert sorted(x.split("-", 1)[1] for x in names) == ["one", "two"] and len({x[:4] for x in names}) == 2  # each once, numbered apart
    assert not list((b / "inputs").glob(".*"))  # no copy left half done


def test_design_time_measures_the_run_s_own_gold_pairs_and_rule_clusters(tmp_path, population):
    """scripts/choose.py measures through er.pipeline, which reads the tables of an er.run.Run: it must report the gold,
    the accepted pairs and their weights, and the rules' clusters that the run writes."""
    from er.pipeline import automatic, run_fs, run_rules
    from er.run import Run
    s, p, g = population
    p = replace(p, fs=replace(p.fs, needs=("name", "company")))  # a pair with no name compared is held back
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "run")
    res = run_fs(p, s, tmp_path / "all.parquet", g.truth, run.model)
    labelled = (res.records.set_index(uid)[["CLUSTER_ID", "MATCH_STAGE", "MATCH_RULE"]]
                .set_axis(["cluster_id", "resolved_stage", "resolved_by"], axis=1).astype("string"))
    gold = pd.read_parquet(tmp_path / "run" / "gold.parquet").set_index(uid)[list(labelled.columns)].astype("string")
    pd.testing.assert_frame_equal(gold, labelled.loc[gold.index], check_index_type=False)
    key = lambda d: d[[l, r, "match_weight"]].astype({l: "string", r: "string"}).sort_values([l, r], ignore_index=True)
    design, ran = key(res.scored[automatic(res.scored, p.fs.min_match_weight) & res.scored["keep"]]), key(pd.read_parquet(tmp_path / "run" / "matches"))
    assert len(design) > 0
    pd.testing.assert_frame_equal(design, ran, check_exact=False, atol=1e-9)
    rules = run_rules(p, s, tmp_path / "all.parquet", g.truth).records.set_index(uid)["CLUSTER_ID"]
    stored = pd.read_parquet(tmp_path / "run" / "state" / "rule_clusters.parquet").set_index(uid)["cluster_id"].astype("string")
    assert rules.loc[stored.index].tolist() == stored.tolist()


def test_a_pair_with_no_name_compared_is_left_to_people(tmp_path, population):
    """A company at a person's address with the person's phone: each record lacks the other's name field, so no name
    is compared, and address and phone alone reach the threshold. With needs, people decide it instead."""
    from er.report import qa
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    home = g.df[g.df[["FULL_NAME_KANA", "PHONE_NUM_4", "SOURCE_ADDR_CD", "STD_ADDRESS"]].notna().all(axis=1)].iloc[0]
    firm = home.copy()
    firm[["FULL_NAME_KANA", "O_PERSON_NAME_KANA", "LAST_NAME_KANA", "GIVEN_NAME_KANA", "CIF_ID", "BIRTH_DATE"]] = pd.NA
    firm[[uid, "NYS_CNV_P_NAME_KANA"]] = ["9" * len(home[uid]), "カブシキガイシャテスト"]
    pd.concat([g.df, firm.to_frame().T.astype(g.df.dtypes)], ignore_index=True).to_parquet(tmp_path / "all.parquet", index=False)
    pair = (home[uid], firm[uid])
    p = replace(p, fs=replace(p.fs, min_match_weight=4.0))
    for needs, out in (((), "a"), (("name", "company"), "b")):
        run = Run(replace(p, fs=replace(p.fs, needs=needs)), s).full(tmp_path / "all.parquet", tmp_path / out)
        weight = run.con.execute(f'SELECT match_weight FROM scores WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0]
        merged = run.con.execute(f'SELECT count(*) FROM matches WHERE "{l}" = ? AND "{r}" = ?', list(pair)).fetchall()[0][0]
        assert weight >= 4.0 and merged == (not needs)
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    row = sheet[(sheet[l] == pair[0]) & (sheet[r] == pair[1])]
    assert row["why"].tolist() == ["decide"] and not row["accepted"].any()


def test_the_batch_budget_counts_the_pairs_touching_the_batch():
    df = pd.DataFrame({"id": [f"{i:02d}" for i in range(9)], "k": list("aaabbbccc"), "n": ["サトウ", "サト", "サウ", "スズキ", "スズ", "ヤマダ",
                                                                                         "ヤマダ", "ヤマ", "タナカ"]})
    batch = ["00", "03", "04"]
    for b in (KeyBlocker(name="k", keys=(Key("k"),)), DeletionKeys(name="d", key=Key("n"))):
        r = Records(df, "id", query=batch)
        est, pairs = estimate_touching(b, r), generate(b, df, "id", batch)
        r.close()
        assert est["est_pairs"] >= len(pairs) > 0  # an upper bound, exact for equal keys
        assert est["est_pairs"] == len(pairs) or isinstance(b, DeletionKeys)


def test_the_review_sheet_asks_about_each_cluster_pair_in_the_safety_margin_once(tmp_path, wide_band):
    from er.match import review_floor
    from er.report import qa
    from er.run import Run
    s, p, g = wide_band
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    t, lo = p.fs.min_match_weight, review_floor(p)
    assert lo == t - 8  # margin_steps (4) grid steps of 2 bits below the threshold
    decide, audit = sheet[sheet["why"] == "decide"], sheet[sheet["why"] == "audit"]
    assert len(decide) and sheet["decision"].isna().all()
    assert decide["match_weight"].between(lo, t, inclusive="left").all() and audit["accepted"].all()
    gold = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)["cluster_id"]
    a, b = decide[f"{uid}_l"].map(gold).to_numpy(), decide[f"{uid}_r"].map(gold).to_numpy()
    assert (a != b).all() and not pd.DataFrame({"x": np.minimum(a, b), "y": np.maximum(a, b)}).duplicated().any()


def test_decisions_join_clusters_without_scoring_and_a_full_run_applies_them_again(tmp_path, wide_band):
    from er.report import qa
    from er.run import Run
    s, p, g = wide_band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    run = Run(p, s).full(tmp_path / "all.parquet", tmp_path / "a")
    sheet = qa(run, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]
    yes = sheet[sheet["why"] == "decide"].index[0]
    sheet.loc[yes, "decision"] = "match"
    sheet.to_parquet(tmp_path / "reviewed.parquet")  # the sheet as people return it; undecided rows are skipped
    rejected = run.con.execute(f'SELECT "{l}", "{r}" FROM matches ORDER BY match_weight DESC LIMIT 1').fetchall()[0]
    pd.DataFrame({l: [rejected[0]], r: [rejected[1]], "decision": [" No_Match "]}).to_parquet(tmp_path / "rejected.parquet")
    before = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    Run(p, s).decide(tmp_path / "reviewed.parquet", tmp_path / "a")
    Run(p, s).decide(tmp_path / "rejected.parquet", tmp_path / "a")  # an accepted pair people reject: it splits nothing now
    after = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    pair = sheet.loc[yes, [l, r]].tolist()
    assert after.loc[pair[0], "cluster_id"] == after.loc[pair[1], "cluster_id"] != before.loc[pair[1], "cluster_id"] or \
        before.loc[pair[0], "cluster_id"] != before.loc[pair[1], "cluster_id"]
    joined = before["resolved_stage"].isna() & after["resolved_stage"].notna()
    assert joined.any() and after.loc[joined, "resolved_by"].eq("review").all()
    assert len(pd.read_parquet(tmp_path / "a" / "decisions")) == 2

    rerun = Run(p, s, model=run.model).full(tmp_path / "all.parquet", tmp_path / "a", overwrite=True)  # people's work survives
    again = pd.read_parquet(tmp_path / "a" / "gold.parquet").set_index(uid)
    assert again.loc[pair[0], "cluster_id"] == again.loc[pair[1], "cluster_id"]
    matches = pd.read_parquet(tmp_path / "a" / "matches")
    assert not ((matches[l] == rejected[0]) & (matches[r] == rejected[1])).any()
    sheet = qa(rerun, [f for f in s.columns if f not in ("id", "entity")])["review_sheet"]  # what people see: what the run did
    accepted = sheet.set_index([l, r]).index.isin(matches.set_index([l, r]).index)
    assert (sheet["accepted"] == accepted).all() and sheet.loc[sheet["why"] == "audit", "accepted"].all()
    assert not ((sheet[l] == rejected[0]) & (sheet[r] == rejected[1])).any()  # a pair people rejected is no audit row

    sheet.loc[yes, "decision"] = "maybe"
    sheet.to_parquet(tmp_path / "bad.parquet")
    with pytest.raises(ValueError, match="match or no_match"):
        Run(p, s).decide(tmp_path / "bad.parquet", tmp_path / "a")
    pd.DataFrame({l: ["nobody"], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "unknown.parquet")
    with pytest.raises(ValueError, match="IDs that name no record of the run"):
        Run(p, s).decide(tmp_path / "unknown.parquet", tmp_path / "a")
    pd.DataFrame({l: [None], r: [pair[0]], "decision": ["match"]}).to_parquet(tmp_path / "blank.parquet")
    with pytest.raises(ValueError, match="decided rows lack an ID"):  # it would decide a pair of one record with itself
        Run(p, s).decide(tmp_path / "blank.parquet", tmp_path / "a")


def test_a_workspace_s_method_changes_the_tuned_one_only_where_it_says(tmp_path):
    from er.cli import setup
    from er.config import adjust
    from er.io import config_hash
    s = load_settings()
    p = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    assert adjust(p, {}) is p and setup(dict(workspace=str(tmp_path)))[1] == p  # no method.toml: the tuned method, the same hash
    rule = p.rules.stages[-1].rules[0].name
    (tmp_path / "method.toml").write_text(f'line = 9.5\ndrop_rules = ["{rule}"]\ndrop_keys = ["cif"]\n', encoding="utf-8")
    q = setup(dict(workspace=str(tmp_path)))[1]  # every command on the workspace: increments compare this hash
    assert q.fs.min_match_weight == 9.5 and rule not in {r.name for _, _, r in q.rules.each()}
    assert [b.name for b in q.fs.blockers] == [b.name for b in p.fs.blockers if b.name != "cif"]
    assert config_hash(q) != config_hash(p) and q.rules.stages[0] == p.rules.stages[0] and q.fs.model == p.fs.model
    assert adjust(p, {"trust": "none"}).trust.line == math.inf and adjust(p, {"trust": 12}).trust.below() == (8.0, 12.0)
    for bad, says in (({"drop_keys": ["nope"]}, "no rule or pair key named"), ({"lines": 9}, "unknown keys"), ({"line": "9"}, "a weight in bits"),
                      ({"drop_keys": "cif"}, "lists of names"), ({"trust": 7}, "one of the steps"), ({"trust": "all"}, "one of the steps"),
                      ({"drop_keys": [b.name for b in p.fs.blockers]}, "leaves no pair key")):
        with pytest.raises(InputError, match=says):
            adjust(p, bad)


def test_a_line_change_sets_right_what_people_decided_and_never_sets_wrong_what_was_right():
    from er.report import line_change
    d = lambda rows: pd.DataFrame(rows, columns=["weight", "named", "same"])
    keep = d([(9.0, True, False), (8.5, True, True), (12.0, True, True)])  # raising past the different pair loses the same one
    assert line_change(keep, 8.0) is None
    both = d([(9.0, True, False), (8.5, True, False), (12.0, True, True), (7.0, True, True), (13.0, False, True)])
    assert line_change(both, 8.0) == (9.5, 2)  # up sets right two, down (7) one; the unnamed pair no line accepts
    assert line_change(d([]), 8.0) is None
    assert line_change(both, 8.0, 6.0, 9.0) == (7.0, 1)  # in the band people review only: past it, pairs nobody looked at


def test_describe_method_scores_people_s_pairs_again_and_an_audit_stays_one_across_rounds(tmp_path, wide_band):
    from er.config import adjust
    from er.io import config_hash
    from er.report import describe_method
    from er.run import Run
    s, p, g = wide_band
    uid = s.data.unique_id
    l, r = f"{uid}_l", f"{uid}_r"
    ws = tmp_path / "ws"
    g.df.to_parquet(tmp_path / "all.parquet", index=False)
    final = s.root / "config" / "final.toml"  # named in the reports, which a run then writes
    run = Run(p, s).full(tmp_path / "all.parquet", ws, pipeline_file=final)
    sheet = pd.read_parquet(ws / "review.parquet")
    yes, no = sheet[sheet["why"] == "decide"].index[0], sheet[sheet["why"] == "audit"].index[0]
    sheet.loc[yes, "decision"], sheet.loc[no, "decision"] = "match", "no_match"
    sheet.to_parquet(tmp_path / "reviewed.parquet")
    kept = pd.read_parquet(ws / "rule_kept").sort_values("match_weight")
    rule_pair = kept.iloc[0]  # one the model scores lowest: only its rule joins it
    sure = kept[(kept["rule"] != rule_pair["rule"]) & (kept["match_weight"] >= p.fs.min_match_weight + 4)].iloc[-1]  # one the model links anyway
    assert rule_pair["match_weight"] < p.fs.min_match_weight
    pd.DataFrame({l: [rule_pair[l], sure[l]], r: [rule_pair[r], sure[r]], "decision": ["no_match"] * 2}).to_parquet(tmp_path / "rule.parquet")  # no why: a file of one's own
    Run(p, s).decide(tmp_path / "reviewed.parquet", ws)
    Run(p, s).decide(tmp_path / "rule.parquet", ws)

    d = describe_method(ws, p, s)
    assert d["round"] == 1 and d["method"] == {} and d["rounds"][0]["matched"] == next(x for x in run.steps if x["step"] == "cluster")["accepted"]
    assert d["audits"]["checked"] == d["audits"]["false"] == d["rounds"][0]["false_found"] == 1 and d["rounds"][0]["decided"] == 4
    weights = {(x["id_l"], x["id_r"]): x["weight"] for x in d["decided"]}
    for i in (yes, no):  # scored again: as the run scored them
        assert weights[tuple(sheet.loc[i, [l, r]])] == pytest.approx(sheet.loc[i, "match_weight"], abs=0.01)
    flagged = next(x for x in d["rules"] if x["name"] == rule_pair["rule"])
    assert flagged["different"] == 1 and {"drop_rules": [rule_pair["rule"]]} in [x["change"] for x in d["proposals"]]
    assert {"drop_rules": [sure["rule"]]} not in [x["change"] for x in d["proposals"]]  # leaving out its rule would join that pair all the same
    keys = {x["name"]: x for x in d["keys"]}
    assert all(keys[c["drop_keys"][0]]["only"] == 0 < keys[c["drop_keys"][0]]["pairs"] for x in d["proposals"] if "drop_keys" in (c := x["change"]))
    scored = run.con.execute("SELECT count(*) FROM scores").fetchall()[0][0]
    for c in p.fs.model.comparisons:  # every scored pair reaches one step of each comparison
        assert sum(x["reached"] for x in d["steps"] if x["comparison"] == c.name) == scored

    again = Run(p, s, model=run.model).rerun(ws, pipeline_file=final)  # the same method: the same round, and the audit is still one
    assert describe_method(ws, p, s)["rounds"][0]["false_found"] == 1 and len(json.loads((ws / "rounds.json").read_text(encoding="utf-8"))) == 1
    assert not pd.read_parquet(ws / "review.parquet").set_index([l, r]).index.isin(list(weights)).any()  # decided pairs: never asked again
    (ws / "method.toml").write_text(f"line = {p.fs.min_match_weight + 1}\n", encoding="utf-8")
    q = adjust(p, {"line": p.fs.min_match_weight + 1})
    Run(q, s, model=again.model).rerun(ws, pipeline_file=final)
    d = describe_method(ws, q, s)
    assert d["round"] == 2 and [x["method"] for x in d["rounds"]] == [{}, {"line": p.fs.min_match_weight + 1}]
    assert d["audits"]["checked"] == 0 and d["rounds"][0]["false_found"] == 1 and config_hash(q) != config_hash(p)


def test_a_bad_rule_is_found_tried_and_left_out_and_audits_reach_every_kind_of_link(say, tmp_path, population, capsys, monkeypatch):
    import threading
    import er.cli as cli
    from er import folder
    from er.config import dump_pipeline
    s, p, g = population
    uid, ent = s.data.unique_id, s.data.entity_id
    l, r = f"{uid}_l", f"{uid}_r"
    bad = Rule(name="BAD_POSTAL_CODE", exact=("postal_code",))  # one postal code: many people
    last = p.rules.stages[-1]
    dump_pipeline(replace(p, rules=replace(p.rules, stages=(*p.rules.stages[:-1], replace(last, rules=(*last.rules, bad))))), s.chains, tmp_path / "planted.toml")
    g.df.to_parquet(tmp_path / "theirs.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    ws, pipe = tmp_path / "workspaces" / "w", ("--workspace", "workspaces/w", "--pipeline", "planted.toml")

    say("create", "workspace", "w")
    (ws / "method.toml").unlink()  # the method as tuned: this is about improving it, not the trust line
    say("load", "records", "theirs.parquet", "--workspace", "workspaces/w")
    assert say("resolve", "records", *pipe)[0] == 0
    tuned = (ws / "state" / "config.txt").read_text(encoding="utf-8")
    entity = g.truth.set_index(uid)[ent]
    kept = pd.read_parquet(ws / "rule_kept")
    wrong = kept[(kept["rule"] == bad.name) & (kept[l].map(entity) != kept[r].map(entity))].head(3)
    assert len(wrong) == 3
    sheet = pd.read_parquet(ws / "review.parquet")
    joins = sheet[sheet["why"] == "decide"].head(1)  # a pair people join: a trial must not see it joined
    pd.concat([wrong[[l, r]].assign(decision="no_match"), joins[[l, r]].assign(decision="match")]).to_parquet(tmp_path / "decided.parquet")
    assert say("apply", "decisions", "--file", "decided.parquet", *pipe)[0] == 0

    code_, d = say("describe", "method", *pipe)
    assert code_ == 0 and next(x for x in d["rules"] if x["name"] == bad.name)["different"] == 3
    assert {"drop_rules": [bad.name]} in [x["change"] for x in d["proposals"]]
    code_, tried = say("try", "method", "--drop", bad.name, *pipe)
    assert code_ == 0 and tried["different_joined"] == {"base": 3, "variant": 0} and tried["same_apart"]["variant"] <= 1  # false merges gone
    assert len(tried["fixed"]) >= 3 and tried["apart"] >= 3
    entities = pd.read_parquet(ws / "gold.parquet")["cluster_id"].nunique()
    assert tried["base"]["entities"] == entities + 1  # the trial ran without people's decisions: the pair they joined is apart
    assert say("try", "method", "--drop", "nope", *pipe)[0] == 2 and say("try", "method", *pipe)[0] == 2

    monkeypatch.setattr(cli, "rerun_records", lambda a, emit: (_ for _ in ()).throw(InputError("the disk is full")))
    assert say("adopt", "method", "--trial", tried["trial"], *pipe)[0] == 2 and not (ws / "method.toml").exists()  # as it was
    monkeypatch.undo()
    monkeypatch.chdir(tmp_path)
    assert say("adopt", "method", "--trial", tried["trial"], *pipe)[0] == 0
    assert folder.method(ws) == {"drop_rules": [bad.name]} and (ws / "state" / "config.txt").read_text(encoding="utf-8") != tuned
    code_, d = say("describe", "method", *pipe)
    assert d["round"] == 2 and bad.name not in [x["name"] for x in d["rules"]] and d["rounds"][0]["decided"] == 4

    asked = lambda: pd.read_parquet(ws / "review.parquet")
    before = asked()
    assert say("draw", "pairs", "--count", 5, *pipe)[1]["drawn"] == 5
    assert say("draw", "pairs", "--count", 50, *pipe)[1]["drawn"] > 0  # the rest
    assert say("draw", "pairs", "--count", 50, *pipe)[1]["drawn"] == 0  # every link is asked about once
    after = asked()
    drawn = after.iloc[len(before):]
    assert (drawn["why"] == "audit").all() and drawn["accepted"].all() and not after.duplicated([l, r]).any()
    decided = pd.read_parquet(ws / "decisions")[[l, r]]
    assert not drawn.set_index([l, r]).index.isin(decided.set_index([l, r]).index).any()  # never a pair people decided
    assert drawn["match_weight"].floordiv(1).nunique() > 1 and drawn["sources"].str.match(r"^[A-Z]").any()  # bands, and the rules' links too

    held, go = threading.Event(), threading.Event()
    def other_trial():  # another trial of the workspace, in a thread of its own
        with folder.run_lock(ws / "trials"):
            held.set()
            go.wait(60)
    other = threading.Thread(target=other_trial)
    other.start()
    held.wait(60)
    assert say("try", "method", "--line", 9, *pipe)[0] == 75  # the trials take turns
    go.set()
    other.join(30)
    for line in (9, 10, 11, 12, 13, 14):
        assert say("try", "method", "--line", line, *pipe)[0] == 0
    assert sorted(int(f.stem) for f in (ws / "trials").glob("*.json") if f.stem.isdigit()) == list(range(3, 8))  # bounded: the last 5

    assert say("reset", "method", *pipe)[0] == 0
    assert not (ws / "method.toml").exists() and (ws / "state" / "config.txt").read_text(encoding="utf-8") == tuned
    assert len(folder.rounds(ws)) == 3


def test_the_trust_line_merges_only_ranges_people_proved_and_steps_down_one_at_a_time(say, tmp_path, population, capsys, monkeypatch):
    from er import folder
    from er.config import dump_pipeline
    s, p, g = population
    uid, ent = s.data.unique_id, s.data.entity_id
    l, r = f"{uid}_l", f"{uid}_r"
    dump_pipeline(replace(p, trust=replace(p.trust, checks=8, watch=3)), s.chains, tmp_path / "small.toml")  # a sample of 8, to test on 492 records
    g.df.iloc[:400].to_parquet(tmp_path / "theirs.parquet", index=False)
    g.df.iloc[400:446].to_parquet(tmp_path / "early.parquet", index=False)
    g.df.iloc[446:].to_parquet(tmp_path / "batch.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    ws, pipe = tmp_path / "workspaces" / "w", ("--workspace", "workspaces/w", "--pipeline", "small.toml")
    truth = g.truth.set_index(uid)[ent]

    def decide_by_truth() -> None:  # people answer every open row of the sheet, rightly
        sheet = pd.read_parquet(ws / "review.parquet")
        sheet = sheet[sheet["decision"].isna()].assign(decision=lambda x: np.where(x[l].map(truth) == x[r].map(truth), "match", "no_match"))
        sheet.to_parquet(tmp_path / "decided.parquet")
        assert say("apply", "decisions", "--file", "decided.parquet", *pipe)[0] == 0

    say("create", "workspace", "w")
    assert folder.method(ws) == {"trust": "none"}  # a new workspace starts strict
    say("load", "records", "theirs.parquet", "--workspace", "workspaces/w")
    assert say("resolve", "records", *pipe)[0] == 0
    gold = pd.read_parquet(ws / "gold.parquet")
    assert gold["cluster_id"].nunique() == len(gold) and not pd.read_parquet(ws / "rule_kept")["merged"].any()  # nothing merged
    keys = say("describe", "method", *pipe)[1]["keys"]
    assert any(k["matched"] for k in keys)  # the keys' likely links count, though none merged: no key looks idle
    busy = max(keys, key=lambda k: k["matched"])
    assert say("describe", "key", busy["name"], *pipe)[1]["matched"] == busy["matched"]  # its drawer counts what its row counts
    kept = (ws / "method.toml").read_text(encoding="utf-8")
    (ws / "method.toml").write_text(kept + f'drop_keys = ["{busy["name"]}"]\n', encoding="utf-8")
    left = say("describe", "method", *pipe)[1]["dropped"]["keys"]  # what the method leaves out, still in words for the page
    assert [x["name"] for x in left] == [busy["name"]] and left[0]["method"] and left[0]["keys"]
    (ws / "method.toml").write_text(kept, encoding="utf-8")
    trust = say("describe", "workspace", "workspaces/w", "--pipeline", "small.toml")[1]["trust"]  # nothing scores 20 on 492 records: that range is passed
    assert trust["line"] == "none" and trust["next"] == {"down_to": 12.0, "up_to": None} and trust["checked"] == 0 < trust["needed"] <= 8
    tuned = (ws / "state" / "config.txt").read_text(encoding="utf-8")
    rules, sheet = [r.name for _, _, r in p.rules.each()], pd.read_parquet(ws / "review.parquet")  # the rules' pairs wait on the sheet too, with the model's levels
    model = sheet[(sheet["why"] == "decide") & ~sheet["sources"].isin(rules)]
    pd.concat([sheet, *[model.head(1).assign(sources=rules[0])] * 50]).to_parquet(ws / "review.parquet")
    assert len(model) and all(min(x["wait"], x["held"], x["apart"]) >= 0 for x in say("list", "patterns", *pipe)[1]["patterns"])  # no pattern's count below 0
    sheet.to_parquet(ws / "review.parquet")
    assert say("lower", "trust", *pipe)[0] == 2  # not proven yet
    full = pd.read_parquet(ws / "review.parquet")
    full[full["why"] != "decide"].to_parquet(ws / "review.parquet")  # a sheet with none of the range's pairs (written before empty ranges were passed)
    drew = say("draw", "pairs", "--count", "0", *pipe)[1]
    assert drew["decide"] == trust["needed"] and drew["drawn"] == 0  # filled from the pairs the run kept for people: no run
    sheet = pd.read_parquet(ws / "review.parquet")
    sample = sheet[sheet["why"] == "decide"]
    assert len(sample) == trust["needed"] and sample["match_weight"].between(12, 20, inclusive="left").all() and not sample.duplicated([l, r]).any()
    decide_by_truth()
    trust = say("describe", "workspace", "workspaces/w", "--pipeline", "small.toml")[1]["trust"]
    assert trust["checked"] == trust["needed"] and trust["may_lower"] == (trust["false"] == 0)
    assert trust["false"] == 0  # 12 bits and more: right on this population

    assert say("lower", "trust", *pipe)[0] == 0 and folder.method(ws) == {"trust": 12.0}
    kept = pd.read_parquet(ws / "rule_kept")
    assert kept["merged"].any() and (kept.loc[kept["merged"], "match_weight"] >= 12).all() and (kept.loc[~kept["merged"], "match_weight"] < 12).all()
    assert (pd.read_parquet(ws / "matches")["match_weight"] >= 12).all() and (pd.read_parquet(ws / "proposed")["match_weight"] < 12).all()
    assert (ws / "state" / "config.txt").read_text(encoding="utf-8") != tuned and len(folder.rounds(ws)) == 2
    trust = say("describe", "workspace", "workspaces/w", "--pipeline", "small.toml")[1]["trust"]
    assert trust["line"] == 12.0 and trust["next"] == {"down_to": 8.0, "up_to": 12.0} and trust["above"]["pairs"] > 0
    audits = pd.read_parquet(ws / "review.parquet").query("why == 'audit'")["match_weight"]
    assert len(audits) and (audits >= 12).all()  # spot-checks above the line
    sheet = pd.read_parquet(ws / "review.parquet")
    one = sheet[(sheet["why"] == "decide") & sheet["match_weight"].between(8, 12, inclusive="left")].head(1)
    one.assign(decision="no_match")[[l, r, "decision"]].to_parquet(tmp_path / "false.parquet")  # people find a false pair in the range below the line
    assert len(one) and say("apply", "decisions", "--file", "false.parquet", *pipe)[0] == 0 and say("rerun", "records", *pipe)[0] == 0
    left = pd.read_parquet(ws / "review.parquet").query("why == 'decide'")
    assert (left["match_weight"] < 8).any()  # the line can't pass it: it, and every range below, to people one by one
    stuck = say("describe", "workspace", "workspaces/w", "--pipeline", "small.toml")[1]["trust"]
    assert stuck["false"] == 1 and stuck["needed"] == stuck["pairs"]  # every pair of it goes to people: "N of all" checked
    assert say("add", "records", "early.parquet", *pipe)[0] == 0  # a batch then: its pairs below go to people one by one too
    early, sheet = set(g.df.iloc[400:446][uid].astype(str)), pd.read_parquet(ws / "review.parquet")
    assert (sheet[(sheet["why"] == "decide") & (sheet[l].isin(early) | sheet[r].isin(early))]["match_weight"] < 8).any()

    pair = kept[kept["merged"]].iloc[0]  # people say a merged rule pair is no match: it stays apart from then on
    pd.DataFrame({l: [pair[l]], r: [pair[r]], "decision": ["no_match"]}).to_parquet(tmp_path / "no.parquet")
    assert say("apply", "decisions", "--file", "no.parquet", *pipe)[0] == 0 and say("rerun", "records", *pipe)[0] == 0
    again = pd.read_parquet(ws / "rule_kept").set_index([l, r])
    assert not again.loc[(pair[l], pair[r]), "merged"]

    status = {x["id"]: x["status"] for x in say("match", "records", "batch.parquet", *pipe)[1]["records"]}
    assert say("add", "records", "batch.parquet", *pipe)[0] == 0  # a batch: above the line merges, below waits
    sheet, new = pd.read_parquet(ws / "review.parquet"), set(g.df.iloc[446:][uid].astype(str))
    asked = {x for x in pd.concat([sheet[l], sheet[r]]) if x in new}
    assert asked and {status[x] for x in asked} <= {"joins an entity", "waits for people"}  # as the preview said: none of them a new entity
    assert "waits for people" in status.values()
    part = sorted((ws / "rule_kept").glob("part-*.parquet"))[-1]
    batch = pd.read_parquet(part)
    assert (batch["merged"] == (batch["match_weight"] >= 12)).all()

    assert say("raise", "trust", *pipe)[0] == 0 and folder.method(ws) == {"trust": 20.0}  # a step up
    assert say("raise", "trust", *pipe)[0] == 0 and folder.method(ws) == {"trust": "none"}  # back to people for everything
    runs = say("describe", "workspace", "workspaces/w", "--pipeline", "small.toml")[1]["runs"]  # the activity: every run, though a full run starts steps.json again
    assert sum(x["what"] == "full run" for x in runs) > 3 and {Path(f).name for x in runs for f in x["files"]} == {"theirs.parquet", "early.parquet", "batch.parquet"}
    gold = pd.read_parquet(ws / "gold.parquet").set_index(uid)
    joined = gold.groupby("cluster_id").filter(lambda x: len(x) > 1)
    assert joined["resolved_by"].eq("review").all()  # only what people said is the same
    assert say("raise", "trust", *pipe)[0] == 2  # above every step already


def test_an_increment_counts_exact_u_again_and_samples_only_a_drifted_comparison(tmp_path, population, monkeypatch):
    import json
    import er.match as M
    from er.run import Run
    s, p, g = population
    new = np.random.default_rng(1).random(len(g.df)) < 0.1
    g.df[~new].to_parquet(tmp_path / "old.parquet", index=False)
    g.df[new].to_parquet(tmp_path / "new.parquet", index=False)
    full = Run(p, s).full(tmp_path / "old.parquet", tmp_path / "c")
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
    inc = Run(p, s).increment(tmp_path / "new.parquet", tmp_path / "c")
    after = json.loads((tmp_path / "c" / "state" / "scoring.json").read_text(encoding="utf-8"))["basis"]
    stale = [k for k, b in after.items() if b["last_check"]["drift_bits"] > (b["last_check"]["se_bits"] or math.inf)]
    assert sampled == stale  # sampled again exactly where drift outgrew the sampling error
    exact = exact_u(model, "records", inc.db)  # the exact levels are always counted on every record
    for c in inc.scoring["comparisons"]:
        for lv in c["comparison_levels"]:
            if lv.get("label_for_charts") in exact.get(c["output_column_name"], {}):
                assert lv["u_probability"] == pytest.approx(exact[c["output_column_name"]][lv["label_for_charts"]])


def test_the_loader_reads_parquet_by_column_name_and_says_what_is_wrong(tmp_path, con_db, monkeypatch):
    from er.source import open_source
    con, _ = con_db
    pd.DataFrame({"cont_id": ["1", "2"], "Phone-Num 4": [599, 1234], "x": ["a", "b"]}).to_parquet(tmp_path / "a.parquet", index=False)
    pd.DataFrame({"CONT_ID": ["3"], "y": ["c"]}).to_parquet(tmp_path / "b.parquet", index=False)
    src = open_source(tmp_path / "a.parquet", con, ["CONT_ID", "PHONE_NUM_4"])  # case, width and separators aside
    assert src.columns == ["CONT_ID", "PHONE_NUM_4", "x"]
    assert con.execute(f"SELECT PHONE_NUM_4 FROM {src.sql}").fetchall() == [("599",), ("1234",)]  # text, zeros lost upstream
    assert any("read as CONT_ID" in x for x in src.notes) and any("stored as a number" in x for x in src.notes)
    both = open_source(tmp_path / "*.parquet", con, ["CONT_ID"])  # a glob: read together by column name
    assert con.execute(f"SELECT count(*) FROM {both.sql}").fetchall()[0][0] == 3 and any("lacks" in x for x in both.notes)

    with pytest.raises(InputError, match="no file matches") as e:
        open_source(tmp_path / "aa.parquet", con, [])
    assert "a.parquet" in e.value.fix  # did you mean
    pd.DataFrame({"CONT_ID": ["1"], "KIND": ["Person"], "Phone": ["x"], "phone__x": ["y"], "kind_2": ["z"]}).to_parquet(tmp_path / "k.parquet")
    named = open_source(tmp_path / "k.parquet", con, ["CONT_ID"], reserved=["kind", "phone"])  # names the run writes itself, in another case
    assert named.columns == ["CONT_ID", "KIND_3", "Phone_2", "phone__x_2", "kind_2"] and any("column KIND read as KIND_3" in n for n in named.notes)
    for d in ("a", "b"):  # a folder named from the home folder: every file in it, kept apart
        (tmp_path / "home" / "exports" / d).mkdir(parents=True)
        pd.DataFrame({"CONT_ID": [f"{d}{i}" for i in range(3)]}).to_parquet(tmp_path / "home" / "exports" / d / "part.parquet")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Windows' home folder
    from er import folder as folders, intake
    part, _ = folders.take_in(tmp_path / "ws_home", "~/exports", intake.InputSpec(), load_settings().paths["reference"])
    assert intake.report(part)["rows"] == 6
    (tmp_path / "empty").mkdir()
    with pytest.raises(InputError, match="holds no CSV, TSV or Parquet file"):  # a folder with no records file: said so, not "did you mean" itself
        open_source(tmp_path / "empty", con, [])
    (tmp_path / "c.parquet").write_text("CONT_ID,name\n1,x\n", encoding="utf-8")
    with pytest.raises(InputError, match="looks like text"):
        open_source(tmp_path / "c.parquet", con, [])
    (tmp_path / "d.parquet").write_bytes((tmp_path / "a.parquet").read_bytes()[:-10])
    with pytest.raises(InputError, match="cut short"):
        open_source(tmp_path / "d.parquet", con, [])
    pd.DataFrame({"cont_id": ["1"], "CONT-ID": ["2"]}).to_parquet(tmp_path / "e.parquet", index=False)
    with pytest.raises(InputError, match="could each be CONT_ID"):
        open_source(tmp_path / "e.parquet", con, ["CONT_ID"])


def test_a_run_sets_aside_what_it_cannot_resolve_and_suggests_a_mapping(tmp_path, population):
    from er.run import Run
    s, p, g = population
    uid = s.data.unique_id
    df = g.df.copy()
    df = pd.concat([df, df.iloc[[0]], df.iloc[[1]].assign(PHONE_NUM_4="9999")], ignore_index=True)  # an exact copy; a clash
    df.loc[2, uid], df.loc[3, uid], df.loc[4, uid], df.loc[5, uid] = " ", "\t", "\xa0", "\u3000"  # no ID: blank in any of its forms
    df.to_parquet(tmp_path / "in.parquet", index=False)
    run = Run(p, s).full(tmp_path / "in.parquet", tmp_path / "run")
    aside = pd.read_parquet(tmp_path / "run" / "set_aside")
    assert sorted(aside["reason"]) == ["no ID"] * 4 + ["the same ID with different content"] * 2
    assert run.n == len(g.df) - 5 and any("kept once" in x for x in run.notes)

    g.df.rename(columns={uid: "customer_no"}).to_parquet(tmp_path / "renamed.parquet", index=False)
    with pytest.raises(InputError, match="lacks a field every run needs") as e:
        Run(p, s).load(tmp_path / "renamed.parquet")
    assert 'id = "customer_no"' in e.value.fix  # suggested from its values: filled and unique


def test_a_run_s_pairs_rows_and_entities_are_read_without_a_run_and_its_merge_conditions_need_none(say, tmp_path, population, monkeypatch):
    """Results, Review and Explore read the run's own files: every pair at 0 points or more with each comparison's level
    (scored/), each record's full row as the file gave it, the entities. Merge conditions join pairs without a run, as a
    run would; turned off, they part only what they joined: people's answers stand, and their "different" never merges."""
    import shutil
    from er import folder
    s, p, g = population
    uid = s.data.unique_id
    g.df.to_parquet(tmp_path / "theirs.parquet", index=False)
    monkeypatch.chdir(tmp_path)
    ws, at = tmp_path / "workspaces" / "w", ("--workspace", "workspaces/w")
    say("create", "workspace", "w")  # strict: nothing merges without people
    assert say("resolve", "records", "theirs.parquet", *at)[0] == 0
    entities = lambda: set(pd.read_parquet(ws / "gold.parquet").groupby("cluster_id")[uid].agg(frozenset))
    assert all(len(e) == 1 for e in entities())

    _, d = say("describe", "results", *at)
    index = pd.read_parquet(ws / "scored")
    rules_alone = int((index["rule"].notna() & index["sources"].isna()).sum())
    listed = next(x["candidates"] for x in json.loads((ws / "steps.json").read_text(encoding="utf-8"))["runs"][0]["steps"] if x["step"] == "candidates")
    assert d["joined"] == 0 and sum(x["pairs"] for x in d["scores"]) == d["candidates"] == listed + rules_alone  # every pair compared: the keys' and the rules' own
    assert ((index["match_weight"] >= 0) | index["rule"].notna()).all()  # 0 or more; the rules' pairs whatever they score
    _, one = say("list", "scored", *at, "--count", 5)
    _, two = say("list", "scored", *at, "--count", 5, "--page", 2)
    points = [x["points"] for x in one["pairs"] + two["pairs"]]
    assert one["total"] == len(index) and len(one["pairs"]) == 5 and points == sorted(points, reverse=True)  # best first, across pages
    assert say("list", "scored", *at, "--status", "waiting", "--from", d["review_from"])[1]["total"] == sum(x["pairs"] for x in d["waiting"])
    best = one["pairs"][0]
    assert set(best["compared"]) == {c.name for c in p.fs.model.comparisons}  # each comparison's level and points
    _, rows = say("show", "records", best["first"], best["second"], "nope", *at)
    given = g.df.set_index(uid, drop=False)
    assert [c["column"] for c in rows["columns"]] == list(g.df.columns) and [x["id"] for x in rows["records"]] == [best["first"], best["second"], "nope"]
    for x in rows["records"][:2]:  # every column as the file gave it
        assert {k: v for k, v in x["row"].items() if v not in (None, "")} == {k: str(v) for k, v in given.loc[x["id"]].items() if pd.notna(v) and str(v) != ""}
    assert rows["records"][2]["row"] is None

    same, apart = (best["first"], best["second"]), (one["pairs"][1]["first"], one["pairs"][1]["second"])
    for (a, b), said in ((same, "match"), (apart, "no_match")):
        assert say("decide", "pair", a, b, said, *at)[0] == 0
    assert say("apply", "decisions", *at)[0] == 0
    people = entities()
    assert {*same} <= next(e for e in people if same[0] in e)
    name = next(c for c in p.fs.model.comparisons if c.name == "name")
    rule = index["rule"].dropna().iloc[0]
    count = lambda m: say("describe", "merging", *at, "--conditions", json.dumps(m))[1]["pairs"]
    high, by_rule, alike = count({"when": [{"points": 12}]}), count({"when": [{"rules": [rule]}]}), count({"when": [{"fields": {"name": name.levels[1].label}}]})
    assert count({"join": "and", "when": [{"points": 12}, {"fields": {"name": name.levels[1].label}}]}) <= min(high, alike)
    either = {"join": "or", "when": [{"points": 12}, {"rules": [rule]}]}
    assert max(high, by_rule) <= count(either) <= high + by_rule
    _, on = say("set", "merging", *at, "--conditions", json.dumps(either))
    merged, said = entities(), pd.read_parquet(ws / "gold.parquet")
    assert on["entities"] > 0 and folder.method(ws)["merge"]["join"] == "or" and merged != people
    assert on["merged"] == count(either) and on["merged"] > len(index[index["match_weight"] >= 12]) // 2  # merged as previewed: undecided pairs counted
    assert not any({*apart} <= e for e in merged if len(e) == 2)  # their "different" never merges by the conditions
    assert say("set", "merging", *at, "--conditions", json.dumps({"when": [{"fields": {"name": "no such step"}}]}))[0] == 2
    assert folder.method(ws)["merge"] == either  # refused before anything changed: the conditions as they were
    from er.report import run_model
    from er.results import merge_where
    assert merge_where({"when": [{"fields": {"gone": "exact"}}]}, run_model(ws), p) == "(FALSE)"  # a comparison the run lacks: never met, no crash
    assert say("reset", "method", *at)[0] == 0  # back to the tuned method, by a run: people's conditions kept
    assert folder.method(ws)["merge"] == either and entities() == merged  # a run takes the same conditions: the same entities
    pd.testing.assert_frame_equal(pd.read_parquet(ws / "gold.parquet")[said.columns], said)  # and says the same of what joined each record
    a, b = sorted(next(e for e in merged if len(e) == 2 and e != frozenset(same)))  # two records only the conditions joined
    assert say("decide", "pair", a, b, "no_match", *at)[0] == 0 and say("apply", "decisions", *at)[0] == 0
    assert not any({a, b} <= e for e in entities())  # said different and applied: apart at once, the conditions still on
    assert say("set", "merging", *at, "--conditions", json.dumps({"when": []}))[0] == 0
    assert entities() == people and "merge" not in folder.method(ws)  # off: what the conditions joined parts; people's answer stands

    g.df.iloc[:440].to_parquet(tmp_path / "first.parquet", index=False)
    g.df.iloc[440:].to_parquet(tmp_path / "batch.parquet", index=False)
    tuned, off = tmp_path / "tuned", ("set", "merging", "--workspace", "tuned", "--conditions", json.dumps({"when": []}))
    assert say("resolve", "records", "first.parquet", "--workspace", "tuned")[0] == 0  # the method as tuned: rules and the model merge by themselves
    run = pd.read_parquet(tuned / "gold.parquet")
    assert say(*off)[0] == 0
    pd.testing.assert_frame_equal(pd.read_parquet(tuned / "gold.parquet"), run)  # no conditions: what the method merges, as its run did
    shutil.rmtree(tuned / "scored")  # a run written before scored/ existed, then a batch: the batch adds no part to an index it lacks
    assert say("add", "records", "batch.parquet", "--workspace", "tuned")[0] == 0 and not (tuned / "scored").exists()
    grouped = lambda: set(pd.read_parquet(tuned / "gold.parquet").groupby("cluster_id")[uid].agg(frozenset))
    added = grouped()
    assert say(*off)[0] == 0 and grouped() == added  # indexed whole, from every part stored: nothing the run or the batch merged lost

    shutil.rmtree(ws / "scored")  # a workspace its run wrote before scored/ existed: indexed once, from the pairs it stored
    assert say("list", "scored", *at)[1]["total"] > 0
    part = next((ws / "scored").glob("part-*.parquet"))
    built = part.stat().st_mtime_ns
    assert say("describe", "results", *at)[0] == 0 and part.stat().st_mtime_ns == built

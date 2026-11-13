"""Keys learned on each file (er.keys) and the edit-distance key they may choose (er.candidates.EditKeys)."""
import itertools
import json
import random
from dataclasses import replace

import pandas as pd
import pytest
from rapidfuzz.distance import Levenshtein

from er.candidates import Records
from er.config import EditKeys, Key, LearnKeys


@pytest.mark.parametrize("k, grouped", [(1, False), (2, False), (2, True), (3, False)])
def test_values_within_k_edits_are_every_pair_brute_force_finds_and_no_other(k, grouped):
    rnd = random.Random(k)
    vals = ["".join(rnd.choice("アイウカキ") for _ in range(rnd.randint(1, 11))) for _ in range(900)] + \
           ["".join(rnd.choice("abc") for _ in range(rnd.randint(1, 9))) for _ in range(300)]  # repeats, short values, two scripts
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(len(vals))], "name": vals, "g": [str(i % 3) for i in range(len(vals))]}, dtype="string")
    within = (Key("g"),) if grouped else ()
    r = Records(df, "uid")
    try:
        got = {tuple(x) for x in r.con.execute(f"SELECT {'g, ' if grouped else ''}v, x FROM {r.near_values(EditKeys(name='e', key=Key('name'), within=within, edits=k), 10**9)}").fetchall()}
    finally:
        r.close()
    u = sorted({(g if grouped else None, v) for v, g in zip(vals, df["g"]) if len(v) >= 2 * (k + 1)})
    want = {((g,) if grouped else ()) + (min(a, b), max(a, b)) for (g, a), (h, b) in itertools.combinations(u, 2)
            if g == h and a != b and Levenshtein.distance(a, b) <= k}
    assert got == want and len(want) > 100  # PassJoin's windows lose none, and cpdist keeps only those within k


def test_a_value_a_crowd_holds_pairs_by_no_edit_key():
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(80)], "name": ["フメイフメイ"] * 70 + ["フメイフメイ1", "フメイフメ", "サトウハナコ", "サトーハナコ", "サトウハナコ", "カトウハナコ", "x", "y", "z", "w"]},
                      dtype="string")
    r = Records(df, "uid")
    try:
        pairs = {tuple(x) for x in r.con.execute(f"SELECT v, x FROM {r.near_values(EditKeys(name='e', key=Key('name'), edits=1), 64)}").fetchall()}
    finally:
        r.close()
    assert ("カトウハナコ", "サトウハナコ") in pairs and not any("フメイフメイ" in p for p in pairs)  # a placeholder's 70 records would pair with each neighbour


def test_atoms_follow_the_method_and_the_records(population):
    from er.keys import atoms
    s, p, g = population
    p = replace(p, keys=LearnKeys())
    have = {"person_name__kana_fold", "phone", "customer_id", "postal_code", "company_name__nfkc_strip_legal_form_kana_fold", "birth_date"}
    found = atoms(p, have)
    assert {a.column for a in found} <= have  # only what the records hold
    assert any(a.column == "person_name__kana_fold" and a.edits == 2 for a in found)  # compared by a similarity: within two edits
    assert any(a.column == "customer_id" and a.edits == 1 for a in found) and not any(a.column == "customer_id" and a.edits == 2 for a in found)


@pytest.fixture(scope="module")
def learned_and_fixed(population, tmp_path_factory):
    from er.run import Run
    s, p, g = population
    d = tmp_path_factory.mktemp("keys")
    g.df.to_parquet(d / "in.parquet", index=False)
    fixed = Run(p, s).full(d / "in.parquet", d / "fixed")
    learned = Run(replace(p, keys=LearnKeys()), s, model=fixed.model).full(d / "in.parquet", d / "learned")  # the same model: only the keys differ
    return s, p, g, d, fixed, learned


def test_learned_keys_stay_in_the_budget_and_lose_no_match_the_method_s_keys_find(learned_and_fixed):
    s, p, g, d, fixed, learned = learned_and_fixed
    facts = next(x for x in learned.steps if x["step"] == "keys")
    assert facts["learned"] and facts["keys"] and all(x["key"].startswith("learned:") for x in facts["keys"])
    assert sum(x["pairs"] for x in facts["keys"]) <= p.fs.budget.max_pairs(learned.n)
    uid, ent = s.data.unique_id, s.data.entity_id
    truth = g.truth.set_index(uid)[ent]
    def found(run):  # the true and the false pairs the run merges
        pairs = run.con.sql(f"SELECT {uid}_l AS a, {uid}_r AS b FROM matches UNION SELECT {uid}_l, {uid}_r FROM rule_kept").df()
        same = pairs["a"].map(truth).to_numpy() == pairs["b"].map(truth).to_numpy()
        return set(map(tuple, pairs[same].to_numpy())), int((~same).sum())
    (true_fixed, false_fixed), (true_learned, false_learned) = found(fixed), found(learned)
    assert true_fixed <= true_learned and false_learned <= false_fixed  # every true pair kept, no false one added


def test_a_learned_key_counts_no_pair_inside_one_of_its_oversized_blocks(population):
    from er.keys import Atom, _normal
    s, p, g = population
    df = pd.DataFrame({"uid": [f"r{i}" for i in range(100)], "pref": ["東京都"] * 90 + ["大阪府"] * 10}, dtype="string")
    r = Records(df, "uid")
    r.con.execute(f"CREATE TABLE records AS SELECT * FROM {r.table}")
    try:
        targets = pd.DataFrame({"a0": ["東京都", "大阪府"], "b0": ["東京都", "大阪府"]})
        from er.keys import blocker
        a = Atom(Key("pref"), 0)
        assert _normal((a,), blocker((a,)), targets, [a], r, 64).tolist() == [False, True]  # 90 records: only the gate could list it
    finally:
        r.close()


def test_an_increment_lists_its_pairs_by_the_keys_the_full_run_learned(learned_and_fixed):
    from er.run import Run
    s, p, g, d, fixed, learned = learned_and_fixed
    kept = json.loads((d / "learned" / "state" / "keys.json").read_text(encoding="utf-8"))
    assert list(kept) == [x["key"] for x in next(x for x in learned.steps if x["step"] == "keys")["keys"]]
    batch = g.df.sample(20, random_state=1).assign(**{s.data.unique_id: lambda x: x[s.data.unique_id] + "_new"})
    batch.to_parquet(d / "batch.parquet", index=False)
    run = Run(replace(p, keys=LearnKeys()), s).increment(d / "batch.parquet", d / "learned")
    assert [b.name for b in run.pipeline.fs.blockers] == list(kept)

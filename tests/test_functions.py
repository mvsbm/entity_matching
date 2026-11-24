"""The functions nayose's SQL calls by name, the same on both engines: the character-level comparisons (rapidfuzz in
DuckDB, JavaScript in BigQuery), the portable hash, and NFKC."""
import json
import unicodedata

import pandas as pd
import pytest

from nayose.engines import FUNCTIONS, STRINGS, DuckDB
from test_bigquery import pairs


@pytest.fixture(scope="module")
def duck():
    engine = DuckDB()
    yield engine
    engine.close()


def test_the_comparisons_score_as_er_s_did_to_the_last_bit(duck):
    from er.engine.duckdb import connect
    old = connect()
    given = pd.DataFrame(pairs(5_000), columns=["a", "b"], dtype="string").assign(i=range(5_000))
    for con in (duck.con, old.con):
        con.register("t", given)
    for name, (similarity, _) in FUNCTIONS.items():
        for cut in ("", ", 0.8" if similarity else ", 1", ", 0.95" if similarity else ", 2"):
            sql = f"SELECT cl_{name}{'_cut' if cut else ''}(a, b{cut}) FROM t ORDER BY i"
            assert duck.con.execute(sql).fetchall() == old.con.execute(sql).fetchall(), (name, cut)


def test_javascript_scores_as_the_duckdb_twins_do(duck):
    mini_racer = pytest.importorskip("py_mini_racer")
    ctx = mini_racer.MiniRacer()
    ctx.eval(STRINGS.read_text(encoding="utf-8"))
    given = pairs(20_000)
    duck.con.register("t2", pd.DataFrame(given, columns=["a", "b"], dtype="string").assign(i=range(len(given))))
    for name in FUNCTIONS:
        got = json.loads(ctx.eval(f"JSON.stringify({json.dumps(given, ensure_ascii=False)}.map(([a, b]) => {name}(a, b)))"))
        want = [x for (x,) in duck.con.execute(f"SELECT cl_{name}(a, b) FROM t2 ORDER BY i").fetchall()]
        assert [(a, b) for (a, b), g, w in zip(given, got, want) if g != w] == [], name


def test_the_portable_hash_and_nfkc(duck):
    from er.engine.duckdb import connect
    old = connect()
    values = ["サトウ", "", None, "12345", "ｶﾌﾞｼｷｶﾞｲｼｬ", "㈱ヤマダ"]
    hashes = lambda con: [r[0] for r in con.execute("SELECT er_hash(x) FROM (SELECT unnest(?) AS x)", [values]).fetchall()]
    assert hashes(duck.con) == hashes(old.con)  # er.config.hashed's: what every sample and order by hash reads
    got = [r[0] for r in duck.con.execute("SELECT nfkc(x) FROM (SELECT unnest(?) AS x)", [values]).fetchall()]
    assert got == [None if v is None else unicodedata.normalize("NFKC", v) for v in values] and got[4] == "カブシキガイシャ" and got[5] == "(株)ヤマダ"

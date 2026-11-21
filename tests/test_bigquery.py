"""The BigQuery engine, checked where no BigQuery is: its comparison functions (JavaScript, run in V8 by mini-racer)
against rapidfuzz's scores, its translation of every statement a run issues, its verbs on a client that records what it
was sent. The parity check (the same records through both engines, by digest) waits for the parts the translation
test finds refused, and for a sandbox dataset."""
import json
import random
from collections import Counter

import pytest

from er.engine.bigquery import FUNCTIONS, UDFS, BigQuery, NotPortable, functions, translate
from er.strings import FUNCTIONS as SCORERS

DATASET = "project.dataset"


def pairs(n: int, seed: int = 0) -> list[tuple[str, str]]:
    """Kana and ASCII values with their typos: a character changed, two swapped, one dropped or added, and unrelated ones."""
    rng = random.Random(seed)
    kana, ascii_ = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンガギグゲゴー", "abcdefgh0123"
    word = lambda alphabet: "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 9)))
    out = []
    for _ in range(n):
        alphabet = kana if rng.random() < 0.7 else ascii_
        a, b = word(alphabet), []
        b = list(a)
        for _ in range(rng.randint(0, 3)):
            op = rng.random()
            if op < 0.3 and b:
                b[rng.randrange(len(b))] = rng.choice(alphabet)
            elif op < 0.5 and len(b) > 1:
                i = rng.randrange(len(b) - 1)
                b[i], b[i + 1] = b[i + 1], b[i]
            elif op < 0.7 and b:
                del b[rng.randrange(len(b))]
            else:
                b.insert(rng.randrange(len(b) + 1), rng.choice(alphabet))
        out.append((a, "".join(b) if rng.random() < 0.8 else word(alphabet)))
    return out


def test_each_comparison_function_in_javascript_scores_as_rapidfuzz_does():
    """20,000 pairs, each function: the same score to the last bit (Jaro–Winkler's boost a fused multiply-add, as
    rapidfuzz's build here computes it). A NULL side is NULL, as DuckDB's functions give it."""
    mini_racer = pytest.importorskip("py_mini_racer")
    ctx = mini_racer.MiniRacer()
    ctx.eval(UDFS.read_text(encoding="utf-8"))
    given = pairs(20_000)
    for name in FUNCTIONS:
        got = json.loads(ctx.eval(f"JSON.stringify({json.dumps(given, ensure_ascii=False)}.map(([a, b]) => {name}(a, b)))"))
        scorer = SCORERS[name].scorer
        want = [float(scorer(a, b)) if name != "jaccard" or a or b else 0.0 for a, b in given]
        wrong = [(a, b, g, w) for (a, b), g, w in zip(given, got, want) if g != w]
        assert not wrong, (name, len(wrong), wrong[:3])


def test_the_deploy_makes_each_function_twice_and_the_hash_once():
    made = functions(DATASET)
    names = [s.split("`")[2].split("(")[0].lstrip(".") for s in made]
    assert names == [f"cl_{f}{cut}" for f in FUNCTIONS for cut in ("", "_cut")] + ["er_hash"]
    assert all(s.startswith(f"CREATE OR REPLACE FUNCTION `{DATASET}`.") for s in made)


def test_a_statement_translates_into_the_session_and_the_dataset_s_functions():
    sql = translate('CREATE OR REPLACE TABLE er_x AS SELECT cl_jaro_winkler(a, b) AS s, er_hash(a) AS h, count(*) FILTER (WHERE x) AS n FROM t GROUP BY ALL', DATASET)
    assert sql.startswith("CREATE OR REPLACE TEMPORARY TABLE er_x")  # the session's own
    assert f"`{DATASET}`.cl_jaro_winkler(" in sql and f"`{DATASET}`.er_hash(" in sql and "COUNTIF(x)" in sql
    for duckdb_only in ("DESCRIBE records", "SELECT * FROM read_parquet('x.parquet')", "SELECT current_setting('threads')", "COPY t TO 'x.parquet'"):
        with pytest.raises(NotPortable):
            translate(duckdb_only, DATASET)


def test_every_statement_of_a_run_translates_or_is_refused_by_name(tmp_path, population, monkeypatch):
    """A full run of the tests' population, every statement it sends its engine translated: each comes out as SQL
    BigQuery's parser reads, or is refused naming the part only DuckDB has (DUCKDB_ONLY, or sqlglot's own). What is
    refused is the BigQuery engine's work still to do; the scoring of pairs, the rules' joins, the counts of u and EM
    translate whole."""
    import sqlglot
    from er.engine.duckdb import DuckDB
    from er.jobs.build import build
    sent = []
    real = DuckDB.run, DuckDB.rows, DuckDB.value, DuckDB.row, DuckDB.frame
    for verb, f in zip(("run", "rows", "value", "row", "frame"), real):
        monkeypatch.setattr(DuckDB, verb, lambda self, sql, params=None, f=f: (sent.append(sql), f(self, sql, params))[1])
    s, p, g = population
    g.df.to_parquet(tmp_path / "in.parquet", index=False)
    build(tmp_path / "in.parquet", tmp_path / "run", s, p)
    refused, made = Counter(), 0
    for sql in sent:
        try:
            for part in sqlglot.parse(translate(sql, DATASET), read="bigquery"):
                assert part is not None
            made += 1
        except NotPortable as e:
            refused[str(e).split(":")[0]] += 1
    scoring = [x for x in sent if "match_probability" in x and "POWER" in x]
    assert scoring and all(translate(x, DATASET) for x in scoring)  # every pair's score, as the run scores it
    assert made > len(sent) / 2, (made, len(sent), refused.most_common())


class Recorded:
    """A BigQuery client that records what it is sent and answers each query with `answer`."""

    class Job:
        def __init__(self, rows):
            self.rows, self.session_info = rows, type("S", (), {"session_id": "s1"})()

        def result(self):
            return self

        def __iter__(self):
            return iter(self.rows)

    def __init__(self, answer):
        self.sent, self.answer = [], answer

    def query(self, sql, job_config=None):
        self.sent.append((sql, job_config))
        return self.Job(self.answer)


def test_the_engine_runs_every_statement_in_one_session():
    """The first statement opens the session, every one after runs in it; what it sends is translated."""
    from types import SimpleNamespace
    config = lambda **k: SimpleNamespace(**k)
    module = SimpleNamespace(QueryJobConfig=config, ConnectionProperty=lambda key, value: SimpleNamespace(key=key, value=value),
                             ScalarQueryParameter=lambda name, kind, value: (kind, value), ArrayQueryParameter=lambda name, kind, value: (kind, value))
    client = Recorded([{"n": 3}])
    engine = BigQuery(DATASET, client=client, bigquery=module)
    assert engine.value("SELECT count(*) AS n FROM t WHERE x = ?", ["a"]) == 3
    engine.run("CREATE OR REPLACE TABLE er_y AS SELECT 1 AS a")
    (_, first), (sql, second) = client.sent
    assert first.create_session and first.query_parameters == [("STRING", "a")]
    assert not second.create_session and second.connection_properties[0].value == "s1" and sql.startswith("CREATE OR REPLACE TEMPORARY TABLE er_y")

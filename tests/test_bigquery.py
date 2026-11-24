"""The BigQuery engine, checked where no BigQuery is: its comparison functions (JavaScript, run in V8 by mini-racer)
against rapidfuzz's scores, its translation of every statement a run issues, its verbs on a client that records what it
was sent. The parity check (the same records through both engines, by digest) waits for the engine's store (a
dataset's tables for the run's files) and a sandbox dataset."""
import json
import random
from collections import Counter

import pandas as pd
import pytest

from er.engine.bigquery import FUNCTIONS, UDFS, BigQuery, NotPortable, functions, translate

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


def test_each_comparison_function_in_javascript_scores_as_duckdb_s_engine_does(engine):
    """20,000 pairs, each function: the score DuckDB's engine gives (cl_<name>, rapidfuzz's through cpdist: Jaro and
    Jaro–Winkler as float32s), the same in JavaScript to the last bit, on every machine: the float32 hides how a build
    of rapidfuzz rounds the double. A NULL side is NULL, as DuckDB's functions give it."""
    import pandas as pd
    mini_racer = pytest.importorskip("py_mini_racer")
    ctx = mini_racer.MiniRacer()
    ctx.eval(UDFS.read_text(encoding="utf-8"))
    given = pairs(20_000)
    engine.register("er_t_pairs", pd.DataFrame(given, columns=["a", "b"], dtype="string").assign(i=range(len(given))))
    try:
        for name in FUNCTIONS:
            got = json.loads(ctx.eval(f"JSON.stringify({json.dumps(given, ensure_ascii=False)}.map(([a, b]) => {name}(a, b)))"))
            want = [x for (x,) in engine.rows(f"SELECT cl_{name}(a, b) FROM er_t_pairs ORDER BY i")]
            wrong = [(a, b, g, w) for (a, b), g, w in zip(given, got, want) if g != w]
            assert not wrong, (name, len(wrong), wrong[:3])
    finally:
        engine.unregister("er_t_pairs")


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


def test_every_statement_a_job_sends_translates_into_sql_bigquery_reads(tmp_path, population, monkeypatch):
    """A full run of the tests' population with its report, an increment, a match run, people's decisions on its table,
    the index kept up to date, lookups by ID, by values and of a file: every statement each sends its engine translates
    (none refused: DUCKDB_ONLY, or sqlglot's own) into SQL BigQuery's parser reads. The name model's own, which runs on
    the job's own DuckDB in its process whatever the engine (er.kind), aside."""
    import traceback
    import sqlglot
    from er.engine.duckdb import DuckDB
    from er.jobs import index
    from er.jobs.build import build
    from er.jobs.decide import decide
    from er.jobs.match import match
    from er.jobs.update import update
    sent = []
    for verb in ("run", "value", "row", "rows", "frame", "numpy", "batches"):
        def said(self, sql, *a, real=getattr(DuckDB, verb), **k):
            if not any(f.filename.endswith("er/kind.py") for f in traceback.extract_stack()):
                sent.append(sql)
            return real(self, sql, *a, **k)
        monkeypatch.setattr(DuckDB, verb, said)
    view, read, slices, answered = DuckDB.view, DuckDB.read, DuckDB.slices, {}  # what DuckDB's engine answered → what BigQuery's does
    monkeypatch.setattr(DuckDB, "view", lambda self, name, sql: (sent.append(sql), view(self, name, sql))[1])
    monkeypatch.setattr(DuckDB, "read", lambda self, *a, **k: (answered.setdefault(x := read(self, *a, **k), f"er_files_{len(answered)}"), x)[1])  # a table
    monkeypatch.setattr(DuckDB, "slices", lambda self, *a, **k: [(answered.setdefault(x, "TRUE"), x)[1] for x in slices(self, *a, **k)])  # one slice: all
    s, p, g = population
    method, n = s.root / "config" / "pipeline.toml", int(len(g.df) * 0.9)
    g.df.iloc[:n].to_parquet(tmp_path / "base.parquet", index=False)
    g.df.iloc[n:].to_parquet(tmp_path / "batch.parquet", index=False)
    run = tmp_path / "run"
    build(tmp_path / "base.parquet", run, s, p, pipeline_file=method)
    update(tmp_path / "batch.parquet", run, s, p, pipeline_file=method)
    pd.read_parquet(match(run, s, p, 6.0)["into"]).head(1).assign(decision="match").to_parquet(tmp_path / "decided.parquet")
    decide(tmp_path / "decided.parquet", run, s, p)
    one = g.df.iloc[0]
    index.look_up(run, s, p, record=str(one[s.data.unique_id]))
    index.look_up(run, s, p, values={c: str(one[c]) for c in ("FULL_NAME_KANA", "PHONE_NUM_4") if pd.notna(one[c])})
    g.df.iloc[n:n + 5].to_parquet(tmp_path / "people.parquet", index=False)
    index.look_up_file(run, s, p, tmp_path / "people.parquet")
    refused = Counter()
    for sql in sent:
        for x in sorted(answered, key=len, reverse=True):
            sql = sql.replace(x, answered[x])
        try:
            assert all(part is not None for part in sqlglot.parse(translate(sql, DATASET), read="bigquery"))
        except (NotPortable, sqlglot.errors.SqlglotError) as e:
            refused[f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"] += 1
    assert len(sent) > 1000 and not refused, refused.most_common(10)
    assert any("match_probability" in x and "POWER" in x for x in sent)  # every pair's score among them


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

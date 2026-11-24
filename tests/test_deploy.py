"""The deploy (deploy/deploy.py, deploy/run.py; nayose.engines.procedures): nayose made in a BigQuery dataset from the
SQL files a run here reads, each job a procedure of its stages' statements with every value they read declared from
config.toml, the method's functions the dataset's and named so by every call; the scripts against a client that
records what it is sent."""
import importlib.util
import math
import re
from pathlib import Path
from types import SimpleNamespace

import sqlglot

from nayose.engines import bigquery_literal, functions, procedures

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
CODE = re.compile(r"--[^\n]*|'(?:[^'\\]|\\.)*'")  # comments and strings: what isn't code


def script(name: str):  # deploy/<name>.py as a module
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_job_is_a_procedure_of_its_stages_with_every_value_it_reads_declared_and_every_function_named():
    out = procedures("p.run", "p.fn")
    made = {re.search(r"FUNCTION `p\.run`\.(\w+)\(", s)[1]: s for s in out if "CREATE OR REPLACE FUNCTION" in s}
    jobs = {re.search(r"PROCEDURE `p\.run`\.(\w+)\(", s)[1]: s for s in out if "CREATE OR REPLACE PROCEDURE" in s}
    assert set(jobs) == {"build", "update", "decide", "match"} and {"read_value", "gamma_name", "weight_of", "bound_of", "household"} <= set(made)
    for job, sql in jobs.items():
        body = sql.split("BEGIN\n", 1)[1].rsplit(";\nEND", 1)[0]
        code = CODE.sub("", body)
        declared = set(re.findall(r"DECLARE (v_\w+)", body)) | ({"v_threshold"} if job == "match" else set())
        assert set(re.findall(r"\bv_\w+", code)) <= declared, job  # every value a statement reads, declared
        assert not re.findall(r"(?<!@)@\w+", code) and "TEMP FUNCTION" not in code, job  # no query parameter, no function of its own
        for declare in (s for s in body.split(";\n") if s.startswith("DECLARE ")):
            assert sqlglot.parse_one(declare, read="bigquery") is not None
    for sql in out:  # a call of the method's SQL functions names the run's dataset; of the JavaScript and Python ones, theirs
        code = CODE.sub("", sql)
        assert not [n for n in made if re.search(rf"(?<![\w.`]){n}\s*\(", code)], sql[:80]
    assert "`p.fn`.fit_model(" in jobs["build"] and "`p.fn`.entities_of(" in jobs["decide"] and "`p.fn`.cl_jaro_winkler_cut(" in made["jaro_winkler_of"]
    levenshtein = [s for s in functions("p.fn") if ".cl_levenshtein" in s]  # BigQuery's own EDIT_DISTANCE: no JavaScript
    assert len(levenshtein) == 2 and all("EDIT_DISTANCE(a, b" in s and "LANGUAGE js" not in s for s in levenshtein)
    assert "DROP TABLE IF EXISTS records" in jobs["build"] and "DROP TABLE IF EXISTS decisions" not in jobs["build"]  # people's decisions stay
    views = re.findall(r"CREATE OR REPLACE VIEW [^;]*", jobs["build"])  # a view's tables named with their dataset: BigQuery reads no default there
    assert len(views) == 2 and all(re.search(r"\bFROM p\.run\.\w+", v) and not re.search(r"\bFROM (?!p\.run\.)\w+\b", v) for v in views), views
    assert "DROP TABLE" not in jobs["update"] and "DECLARE v_refit BOOL DEFAULT FALSE" in jobs["update"]


def test_a_value_is_declared_as_bigquery_reads_it():
    assert bigquery_literal("a\\b'c\td") == "'a\\\\b\\'c\\U00000009d'"
    assert bigquery_literal(["x", "y"]) == "ARRAY<STRING>['x', 'y']" and bigquery_literal([1.5]) == "ARRAY<FLOAT64>[CAST(1.5 AS FLOAT64)]"
    assert bigquery_literal(True) == "TRUE" and bigquery_literal(64) == "64" and bigquery_literal(-math.inf) == "CAST('-inf' AS FLOAT64)"


class Recorded:  # a BigQuery client that records what it is sent
    def __init__(self):
        self.sent, self.loaded = [], []

    def query(self, sql, job_config=None):
        self.sent.append(sql)
        return SimpleNamespace(result=lambda: [], session_info=SimpleNamespace(session_id="s1"))

    def load_table_from_dataframe(self, frame, table, job_config=None):
        self.loaded.append((table, len(frame)))
        return SimpleNamespace(result=lambda: None)

    def load_table_from_uri(self, uris, table, job_config=None):
        self.loaded.append((table, list(uris)))
        return SimpleNamespace(result=lambda: None)


MODULE = SimpleNamespace(QueryJobConfig=lambda **k: SimpleNamespace(**k), ConnectionProperty=lambda key, value: SimpleNamespace(key=key, value=value),
                         LoadJobConfig=lambda **k: SimpleNamespace(**k), ScalarQueryParameter=lambda *a: a, ArrayQueryParameter=lambda *a: a)


def test_the_deploy_makes_the_functions_then_the_procedures_and_loads_the_name_model():
    client = Recorded()
    assert script("deploy").main(["p.run"], client=client, bigquery=MODULE) == 0
    made = [s for s in client.sent if s.startswith("CREATE OR REPLACE")]
    assert made[0].startswith("CREATE OR REPLACE FUNCTION `p.run`.cl_") and made[-1].startswith("CREATE OR REPLACE PROCEDURE `p.run`.match(")
    assert client.loaded[0][0] == "p.run.name_weights" and client.loaded[0][1] > 1000


def test_a_job_loads_its_input_into_the_dataset_and_calls_its_procedure(monkeypatch):
    run = script("run")
    monkeypatch.setattr(run.nayose, "report_text", lambda engine, steps, job: f"report of a {job}")
    client = Recorded()
    assert run.main(["p.run", "build", "gs://b/in/records.parquet"], client=client, bigquery=MODULE) == 0
    assert client.loaded == [("p.run.input", ["gs://b/in/records.parquet"])] and "CALL `p.run`.build()" in client.sent
    client = Recorded()
    assert run.main(["p.run", "match", "8"], client=client, bigquery=MODULE) == 0 and "CALL `p.run`.match(8.0)" in client.sent
    assert run.main(["p.run", "lookup", "x"], client=Recorded(), bigquery=MODULE) == 2  # not a job BigQuery runs

"""The deploy (deploy/deploy.py, deploy/run.py; nayose.engines.procedures): nayose made in a BigQuery dataset from the
SQL files a run here reads, each job a procedure of its stages' statements with every value they read declared from
config.toml, the method's functions the dataset's and named so by every call; the scripts against a client that
records what it is sent."""
import importlib.util
import math
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlglot

import nayose

from nayose.engines import bigquery_literal, functions, procedures

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
CODE = nayose.NOT_CODE  # comments and strings: what isn't code
FILE_BUDGET = 78  # the most tracked files the repository holds: CONTRIBUTING.md, rule 10


def test_the_repository_holds_no_more_files_than_its_budget():
    tracked = subprocess.run(["git", "ls-files"], cwd=DEPLOY.parent, capture_output=True, text=True)
    if tracked.returncode:
        pytest.skip("not a git checkout: no tracked files to count")
    count = len(tracked.stdout.splitlines())
    assert count <= FILE_BUDGET, (f"{count} tracked files, over the budget of {FILE_BUDGET}: remove one, "
                                  "or raise FILE_BUDGET in this file and say why in the pull request")


def script(name: str):  # deploy/<name>.py as a module
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_job_is_a_procedure_of_its_stages_with_every_value_it_reads_declared_and_every_function_named():
    out = procedures("p.run")
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
    for sql in out:  # a call of any of the method's functions names the run's dataset, where the deploy made it
        code = CODE.sub("", sql)
        assert not [n for n in made if re.search(rf"(?<![\w.`]){n}\s*\(", code)], sql[:80]
    assert "`p.run`.fit_model(" in jobs["build"] and "`p.run`.entities_of(" in jobs["decide"] and "`p.run`.cl_jaro_winkler_cut(" in made["jaro_winkler_of"]
    levenshtein = [s for s in functions("p.run") if ".cl_levenshtein" in s]  # BigQuery's own EDIT_DISTANCE: no JavaScript
    assert len(levenshtein) == 2 and all("EDIT_DISTANCE(a, b" in s and "LANGUAGE js" not in s for s in levenshtein)
    dropped = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", jobs["build"]))  # a build starts without the tables it writes, but people's decisions
    assert {"records", "placeholders", "fit", "model", "scored", "gold", "set_aside"} <= dropped and "decisions" not in dropped
    views = re.findall(r"CREATE OR REPLACE VIEW [^;]*", jobs["build"])  # a view's tables named with their dataset: BigQuery reads no default there
    assert len(views) == 1 and all(re.search(r"\bFROM p\.run\.\w+", v) and not re.search(r"\bFROM (?!p\.run\.)\w+\b", v) for v in views), views
    assert "DROP TABLE" not in jobs["update"] and "fit_model(" not in jobs["update"]  # an update scores with the build's model


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


class Tables(Recorded):  # a dataset's tables, each a version and a type, as BigQuery lists them: what a job's statements leave
    def __init__(self, tables: dict, job: dict | None = None, fail: str | None = None):
        super().__init__()
        self.tables, self.job, self.fail = dict(tables), job or {}, fail  # job: the procedure's tables (None: dropped)
        self.kind = dict.fromkeys(tables, "BASE TABLE")
        self.mark, self.sessions, self.running, self.checked_in = {}, 0, set(), []

    def query(self, sql, job_config=None):
        self.sent.append(sql)
        if getattr(job_config, "create_session", False):
            self.sessions += 1
        given, rows = {p[0]: p[2] for p in getattr(job_config, "query_parameters", [])}, []
        props = getattr(job_config, "connection_properties", None) or []
        session = f"s{self.sessions}" if getattr(job_config, "create_session", False) else props[0].value if props else None
        if session in self.running and "ABORT_SESSION" not in sql:  # BigQuery runs one query at a time in a session
            raise RuntimeError(f"Resources exceeded: session {session} is running a query")
        for s in sql.split(";\n"):
            name = [x.split(".")[-1] for x in re.findall(r"`p\.run`\.(\w+)", s)]
            if not name and "INFORMATION_SCHEMA" not in s:  # on the default dataset alone (a lookup's looked_up): recorded, no more
                continue
            if self.fail and self.fail != "procedure" and self.fail in s:
                self.fail = None
                raise RuntimeError(f"failed: {s[:60]}")
            if "INFORMATION_SCHEMA.TABLES" in s:
                kinds = re.findall(r"'([A-Z ]+)'", s)
                rows = [{"table_name": x} for x in sorted(self.tables) if self.kind[x] in kinds]
            elif "INFORMATION_SCHEMA.JOBS_BY_USER" in s:
                rows = [{"n": int(given["session"] in self.running)}]
                self.checked_in.append(getattr(job_config, "connection_properties", None))  # the session it ran in
            elif s.startswith("SELECT session, tables FROM"):
                rows = [self.mark]
            elif s.startswith("CREATE TABLE") and name[0] in self.tables:
                raise RuntimeError(f"Already Exists: {name[0]}")
            elif " CLONE " in s:
                self.tables[name[0]], self.kind[name[0]] = self.tables[name[1]], "CLONE"
            elif s.startswith("CREATE TABLE"):  # the mark
                self.tables[name[0]], self.kind[name[0]] = "mark", "BASE TABLE"
                tail = s.split("AS session, ")
                self.mark = {"session": re.findall(r"'(\w*)'", tail[0])[-1], "tables": re.findall(r"'(\w*)'", tail[1])}
            elif s.startswith("DROP TABLE"):
                del self.tables[name[0]], self.kind[name[0]]
            elif s.startswith("CALL `p.run`."):
                for x, v in self.job.items():
                    if v is None:
                        self.tables.pop(x, None), self.kind.pop(x, None)
                    else:
                        self.tables[x], self.kind[x] = v, "BASE TABLE"
                if self.fail == "procedure":
                    raise RuntimeError("the procedure failed partway")
                if self.fail == "interrupted":  # the client stopped waiting: the procedure carries on in BigQuery
                    self.running.add(session)
                    raise KeyboardInterrupt
        return SimpleNamespace(result=lambda rows=rows: rows, session_info=SimpleNamespace(session_id=session))

    def load_table_from_uri(self, uris, table, job_config=None):
        self.tables[table.split(".")[-1]], self.kind[table.split(".")[-1]] = "loaded", "BASE TABLE"
        return SimpleNamespace(result=lambda: None)

    def get_dataset(self, dataset):
        return SimpleNamespace(location="asia-northeast1")


def test_a_job_on_bigquery_is_all_or_nothing(monkeypatch):
    run = script("run")
    monkeypatch.setattr(run.nayose, "report_text", lambda engine, steps, job: "")
    build = ["p.run", "build", "gs://b/x.parquet"]
    before = {"records": 1, "scored": 1, "decisions": 1, "name_weights": 1}
    made = {"records": 2, "scored": None, "report_steps": 2}  # what the procedure leaves: one replaced, one dropped, one new
    after = {"records": 2, "decisions": 1, "name_weights": 1, "report_steps": 2, "input": "loaded"}
    done = Tables(before, made)
    assert run.main(build, client=done, bigquery=MODULE) == 0 and done.tables == after  # no mark, no clone left
    assert run.main(build, client=done, bigquery=MODULE) == 0 and done.tables == after  # and the next job runs as well
    failed = Tables(before, made, fail="procedure")
    assert run.main(build, client=failed, bigquery=MODULE) == 1  # a JSON line says it failed, and how to go on
    assert failed.tables == before  # each table from its clone, the one dropped too; the input and the new table dropped
    left = Tables(before, made, fail="DROP TABLE `p.run`.before__records")  # a job done, its mark gone, a clone left behind
    assert run.main(build, client=left, bigquery=MODULE) == 1
    left.job, left.fail = {"records": 3}, "CREATE TABLE `p.run`.before__records"  # the next job fails cloning
    assert run.main(build, client=left, bigquery=MODULE) == 1
    assert left.tables == after  # the left clone was dropped first, so nothing older came back
    cut = Tables(before, made, fail="interrupted")  # stopped waiting mid-call: no undo while its procedure runs on
    assert run.main(build, client=cut, bigquery=MODULE) == 75 and cut.tables["records"] == 2 and "job_running" in cut.tables
    cut.running = set()  # it ended: the undo it was told to run puts every table back
    assert run.main(["p.run", "undo"], client=cut, bigquery=MODULE) == 0 and cut.tables == before
    assert cut.checked_in and not any(cut.checked_in)  # each check outside every session, so it never counts itself

    died = Tables(before, made)  # a job whose process died, its procedure run: the next job refuses; undo waits for it, then undoes
    assert run.begin(run.BigQuery("p.run", client=died, bigquery=MODULE), "p.run", "build")
    died.query("CALL `p.run`.build()")
    died.running, died.tables["name_weights"] = {"s1"}, 2  # its procedure still running; a deploy since, with a new name model
    assert run.main(["p.run", "match", "8"], client=died, bigquery=MODULE) == 75 and not [s for s in died.sent if s.startswith("CALL `p.run`.match")]
    assert run.main(["p.run", "undo"], client=died, bigquery=MODULE) == 75 and died.tables["records"] == 2
    died.running, died.fail = set(), "DROP TABLE `p.run`.report_steps"  # it ended; an undo stopped partway runs again
    with pytest.raises(RuntimeError, match="failed"):
        run.main(["p.run", "undo"], client=died, bigquery=MODULE)
    assert run.main(["p.run", "undo"], client=died, bigquery=MODULE) == 0 and died.tables == {**before, "name_weights": 2}
    assert run.main(["p.run", "undo"], client=died, bigquery=MODULE) == 0 and died.tables == {**before, "name_weights": 2}  # nothing marked


def test_python_s_statements_on_bigquery_call_the_deploy_s_functions_and_make_none():
    import nayose
    from nayose.engines import BigQuery
    client = Recorded()
    engine = BigQuery("p.run", client=client, bigquery=MODULE)
    nayose.stage(engine, "functions")
    engine.run("SELECT gamma_company(x, y), cl_jaro_winkler(a, b) FROM t")
    assert not [s for s in client.sent if "TEMP FUNCTION" in s] and "`p.run`.gamma_company(x, y), `p.run`.cl_jaro_winkler(a, b)" in client.sent[-1]


def test_every_function_python_calls_on_bigquery_is_one_the_deploy_makes():  # else a lookup would call one never made
    from nayose import SQL
    made = {re.search(r"FUNCTION `p\.run`\.(\w+)\(", s)[1] for s in procedures("p.run") if "CREATE OR REPLACE FUNCTION" in s}
    called = {n for f in SQL.glob("*.sql") for n in re.findall(r"CREATE OR REPLACE TEMP FUNCTION (\w+)", f.read_text(encoding="utf-8"))}
    assert called <= made, called - made


def test_a_lookup_on_bigquery_writes_its_answer_to_looked_up_and_prints_none_of_it(monkeypatch, capsys):
    run = script("run")
    monkeypatch.setattr(run.nayose, "lookup", lambda engine, record=None, values=None: {"record": {"id": record}, "entities": [{"shown": "ヤマダ"}]})
    client = Tables({"records": 1})
    assert run.main(["p.run", "lookup", "--record", "123"], client=client, bigquery=MODULE) == 0
    said = capsys.readouterr()
    assert "ヤマダ" not in said.out + said.err and '"entities": 1' in said.err
    insert = next(s for s in client.sent if s.startswith("INSERT INTO looked_up"))
    assert "@answer" in insert and "ヤマダ" not in insert  # the answer goes as a parameter, into the run's table
    client.tables["job_running"], client.kind["job_running"] = "mark", "BASE TABLE"
    assert run.main(["p.run", "lookup", "--record", "123"], client=client, bigquery=MODULE) == 75
    assert run.main(["p.run", "lookup", "name"], client=Tables({}), bigquery=MODULE) == 2

"""The deploy (deploy/deploy.py, deploy/run.py; nayose.procedures): nayose made in a BigQuery dataset from the
SQL files a run here reads, each job a procedure of its stages' statements with every value they read declared from
config.toml, the method's functions the dataset's and named so by every call; the scripts against a client that
records what it is sent."""
import importlib.util
import json
import math
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlglot

import nayose

from nayose.engines import bigquery_literal
from nayose.procedures import functions, in_dataset, procedures, stubs
from test_sql import reserved

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
CODE = nayose.NOT_CODE  # comments and strings: what isn't code
FILE_BUDGET = 82  # the most tracked files the repository holds: CONTRIBUTING.md, rule 10


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
    assert set(jobs) == {"build", "update", "decide", "match"} and {"read_value", "name_level", "points_of", "bound_of", "household"} <= set(made)
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
    dropped = set(re.findall(r"DROP TABLE IF EXISTS `p\.run`\.(\w+)", jobs["build"]))  # a build starts without the tables it writes, but people's decisions
    assert {"records", "placeholders", "fit", "model", "scored", "gold", "set_aside"} <= dropped and "decisions" not in dropped
    views = re.findall(r"CREATE OR REPLACE VIEW [^;]*", jobs["build"])  # a view's tables named with their dataset: BigQuery reads no default there
    assert len(views) == 1 and all(re.search(r"\bFROM `p\.run`\.\w+", v) and not re.search(r"\bFROM (?!`p\.run`\.)\w+\b", v) for v in views), views
    assert "DROP TABLE" not in jobs["update"] and "fit_model(" not in jobs["update"]  # an update scores with the build's model
    unchanged = in_dataset(nayose.UNCHANGED, "p.run").split("@fingerprint")[0]  # every job after a build refuses a run another method built
    assert unchanged not in jobs["build"] and all(unchanged in jobs[j] for j in ("update", "decide", "match"))
    assert all(") OPTIONS (strict_mode = FALSE)\nBEGIN" in sql for sql in jobs.values())  # made before any table it reads
    assert not [j for j, sql in jobs.items() if re.search(r"\bLIMIT (?!\d)", CODE.sub("", sql))]  # a number: no variable there
    assert f"LIMIT {nayose.config()['fit']['fit_records']})" in jobs["build"]
    for job in ("build", "update"):  # given no decisions: decide.sql's statements that read given aren't there at all
        assert "given" not in re.findall(r"\bFROM\s+(?:`p\.run`\.)?(\w+)", CODE.sub("", jobs[job])) and "given_text" not in jobs[job]
    assert "FROM `p.run`.given)" in jobs["decide"] and "IF v_given" not in jobs["decide"]  # the decide job: always
    assert not [j for j, sql in jobs.items() if re.search(r"^IF [^\n]*\bv_(lookup|given)\b", sql, re.M)]  # known: folded


def test_a_procedure_names_every_table_with_its_dataset_but_the_job_s_temporary_tables():  # BigQuery reads no default there
    from nayose.procedures import JOBS, job_statements
    made = re.compile(r"\bCREATE (?:OR REPLACE )?TEMP TABLE (?:IF NOT EXISTS )?(\w+)")  # each form the SQL writes
    for job, stages in JOBS.items():
        body = job_statements(job, stages, "p.run", None)[0]
        temp = {t for sql in body for t in made.findall(" ".join(CODE.sub(" ", sql).split()))}
        assert "block_size" in temp or job not in ("build", "update"), job  # made by CREATE TEMP TABLE IF NOT EXISTS
        asked = [f"SELECT {c}" for x in body for c in re.findall(r"^SET v_\w+ = \((.*)\);\n", x)]  # queried_once's
        body = [re.sub(r"^SET v_\w+ = \(.*\);\n", "", x) for x in body]
        for sql in body + asked + [f"SELECT {guard}" for guard in re.findall(r"^IF ([\s\S]*?) THEN\n", "\n".join(body), re.M)]:
            inner = re.fullmatch(r"IF [\s\S]*? THEN\n([\s\S]*);\nEND IF", sql)
            tree = sqlglot.parse_one(inner[1] if inner else sql, read="bigquery")
            ctes = {c.alias_or_name for c in tree.find_all(sqlglot.exp.CTE)}
            bare = {t.name for t in tree.find_all(sqlglot.exp.Table) if not t.args.get("db")} - ctes - temp
            assert not bare, f"{job}: {bare} named without the dataset in {sql[:80]}"
            named = {t.name for t in tree.find_all(sqlglot.exp.Table) if t.args.get("db")}
            assert not named & temp, f"{job}: temporary {named & temp} named with the dataset, which BigQuery refuses"


def test_the_deploy_sends_the_functions_bodies_as_written():  # qualified names the calls of the SQL alone
    from nayose.engines import qualified
    assert [qualified(sql, "p.run") for sql in functions("p.run")] == functions("p.run")


def test_a_condition_on_a_value_the_procedure_declares_is_decided_when_the_deploy_makes_it():
    from nayose.procedures import folded, in_procedure
    known = {"v_lookup": False, "v_given": True}
    assert folded("NOT v_lookup", known) is True and folded("v_lookup", known) is False and folded("v_given", known) is True
    assert folded("NOT v_lookup AND (SELECT batch FROM this_batch) = 0", known) == "(SELECT batch FROM this_batch) = 0"
    assert folded("v_lookup OR EXISTS (SELECT 1 FROM t)", known) == "EXISTS(SELECT 1 FROM t)"
    assert folded("EXISTS (SELECT 1 FROM changed WHERE redone)", known) == "EXISTS (SELECT 1 FROM changed WHERE redone)"
    assert in_procedure("-- when: @lookup\nSELECT 1", "p.run", set(), known) is None  # never runs: left out
    assert in_procedure("-- when: NOT @lookup\nSELECT 1", "p.run", set(), known) == "SELECT 1"  # decided: no IF, no line


def test_a_condition_a_procedure_asks_again_is_asked_once_where_nothing_between_writes_what_it_reads():
    from nayose.procedures import procedures, queried_once
    ask = ["IF EXISTS (SELECT 1 FROM t) THEN\nDELETE FROM a WHERE TRUE;\nEND IF", "SELECT 1",
           "IF EXISTS (SELECT 1 FROM t) THEN\nDELETE FROM b WHERE TRUE;\nEND IF"]
    body, names = queried_once(list(ask))
    assert names == ["condition_1"] and body[0].startswith("SET v_condition_1 = (EXISTS(SELECT 1 FROM t));\nIF v_condition_1 THEN")
    assert body[2].startswith("IF v_condition_1 THEN\nDELETE FROM b")
    assert queried_once([ask[0], "CREATE OR REPLACE TEMP TABLE t AS SELECT 1 AS x", ask[2]])[1] == []  # t made again between
    assert queried_once([ask[0], "CREATE OR REPLACE TEMP TABLE t AS SELECT 1;  -- a note", ask[2]])[1] == []  # its ; then a comment
    assert queried_once([ask[0].replace("FROM a", "FROM t"), "SELECT 1", ask[2]])[1] == []  # the first IF's own statement
    assert queried_once([ask[0], "CALL `p.run`.x()", ask[2]])[1] == []  # a statement it can't read may write t
    negated = queried_once([ask[0], ask[2].replace("IF EXISTS", "IF NOT EXISTS")])[0]
    assert negated[1].startswith("IF NOT v_condition_1 THEN")  # a condition and NOT it: one question
    for job in [s for s in procedures("p.run") if "CREATE OR REPLACE PROCEDURE" in s]:  # each condition a query once
        asked = re.findall(r"^IF (.*) THEN$", job, re.M) + re.findall(r"^SET v_\w+ = \((.*)\);$", job, re.M)
        assert len([c for c in asked if "SELECT" in c]) == len({c for c in asked if "SELECT" in c}), job[:60]


def test_a_when_condition_names_the_run_s_tables_with_the_dataset_as_its_statement_does():
    from nayose.procedures import in_procedure
    sql = in_procedure("-- when: EXISTS (SELECT 1 FROM scored) AND EXISTS (SELECT 1 FROM t)\nSELECT 1", "p.run", {"t"})
    assert sql.startswith("IF EXISTS (SELECT 1 FROM `p.run`.scored) AND EXISTS (SELECT 1 FROM t) THEN\n")


def test_a_procedure_reads_each_value_as_its_variable_outside_strings_alone():  # as run_file reads them
    from nayose.procedures import in_procedure
    sql = "-- when: @a\n-- the run's @b\n/* the customer's @c */ SELECT '@x' AS s, \"@x\" AS d, r'@x' AS r, `@x`.y, @x AS v FROM t"
    assert in_procedure(sql, "p.run", set()) == ("IF v_a THEN\n-- the run's v_b\n/* the customer's @c */ "
                                                 "SELECT '@x' AS s, \"@x\" AS d, r'@x' AS r, `@x`.y, v_x AS v FROM `p.run`.t;\nEND IF")


def test_report_txt_names_the_method_the_run_was_built_by_and_its_engine():  # on BigQuery, the deploy's mapping's
    from nayose.reporting import report_header
    engine = SimpleNamespace(name="bigquery", value=lambda sql: "f" * 64 if sql == "SELECT fingerprint FROM method" else None)
    head = report_header(engine, {"build": 1.0}, None)
    assert head[1].endswith(" · method ffffffffffff") and " · bigquery · " in head[2] and "duckdb" not in head[2]


def test_a_value_is_declared_as_bigquery_reads_it():
    assert bigquery_literal("a\\b'c\td") == "'a\\\\b\\'c\\U00000009d'"
    assert bigquery_literal(["x", "y"]) == "ARRAY<STRING>['x', 'y']" and bigquery_literal([1.5]) == "ARRAY<FLOAT64>[CAST(1.5 AS FLOAT64)]"
    assert bigquery_literal(True) == "TRUE" and bigquery_literal(64) == "64" and bigquery_literal(-math.inf) == "CAST('-inf' AS FLOAT64)"


SENT = []  # what each fake client of a test was sent: no name in it may be one BigQuery refuses


@pytest.fixture(autouse=True)
def no_reserved_name_in_what_python_sends():  # the deploy's, the jobs', the lookup's: as test_sql holds the stage files
    SENT.clear()
    yield
    assert not {n for sent in SENT for sql in sent for n in reserved(sql)}


class Recorded:  # a BigQuery client that records what it is sent
    def __init__(self):
        self.sent, self.loaded = [], []
        SENT.append(self.sent)

    def query(self, sql, job_config=None, job_retry="the library's: a failed job sent again whole"):
        assert job_retry is None, job_retry  # a CALL begun again from its first statement loses the batch's records
        self.sent.append(sql)
        self.labels = getattr(job_config, "labels", None)  # the last query's
        return SimpleNamespace(result=lambda: [], session_info=SimpleNamespace(session_id="s1"))

    def load_table_from_dataframe(self, frame, table, job_config=None):
        self.loaded.append((table, len(frame), len(self.sent)))  # and how many statements came before
        return SimpleNamespace(result=lambda: None)

    def load_table_from_uri(self, uris, table, job_config=None):
        self.loaded.append((table, list(uris)))
        return SimpleNamespace(result=lambda: None)


MODULE = SimpleNamespace(QueryJobConfig=lambda **k: SimpleNamespace(**k), ConnectionProperty=lambda key, value: SimpleNamespace(key=key, value=value),
                         LoadJobConfig=lambda **k: SimpleNamespace(**k), ScalarQueryParameter=lambda *a: a, ArrayQueryParameter=lambda *a: a)


def test_the_deploy_as_files_holds_every_statement_and_the_name_model_and_sends_nothing(tmp_path):
    import pandas as pd
    assert script("deploy").main(["p.run", "--sql", str(tmp_path)], client=None, bigquery=None) == 0  # no client made
    sql = (tmp_path / "deploy.sql").read_text(encoding="utf-8")
    assert sql == ";\n\n".join([*stubs("p.run"), *functions("p.run"), *procedures("p.run")]) + ";\n"
    assert len(sql.encode()) < 1024 ** 2  # the console's limit: 1 MB a query
    weights = pd.read_csv(tmp_path / "name_weights.csv", keep_default_na=False, float_precision="round_trip")
    assert weights.values.tolist() == nayose.name_weights().values.tolist()  # every term and weight, to the last bit


def test_the_deploy_makes_stubs_then_the_functions_and_the_name_model_then_the_procedures():
    client = Recorded()
    assert script("deploy").main(["p.run"], client=client, bigquery=MODULE) == 0
    made = [s for s in client.sent if s.startswith("CREATE OR REPLACE")]
    assert made[:4] == stubs("p.run") and all("ERROR('deploy: " in s for s in made[:4])  # a deploy stopped: jobs refuse
    assert made[4].startswith("CREATE OR REPLACE FUNCTION `p.run`.cl_") and made[-1].startswith("CREATE OR REPLACE PROCEDURE `p.run`.match(")
    table, rows, before = client.loaded[0]
    first_procedure = next(i for i, s in enumerate(client.sent) if s.startswith("CREATE OR REPLACE PROCEDURE `p.run`.build() OPTIONS"))
    assert table == "p.run.name_weights" and rows > 1000  # after the stubs and the functions, before any job's procedure
    assert len(stubs("p.run")) + len(functions("p.run")) <= before <= first_procedure
    for stub, real in zip(stubs("p.run"), [s for s in made if s.startswith("CREATE OR REPLACE PROCEDURE") and " OPTIONS" in s]):
        assert stub.split("\n")[0] == real.split(" OPTIONS")[0]  # each stub takes what its job's procedure takes


def test_a_job_loads_its_input_into_the_dataset_and_calls_its_procedure(monkeypatch):
    run = script("run")
    monkeypatch.setattr(run.nayose, "report_text", lambda engine, steps, job: f"report of a {job}")
    client = Recorded()
    assert run.main(["p.run", "build", "gs://b/in/records.parquet"], client=client, bigquery=MODULE) == 0
    assert client.loaded == [("p.run.input", ["gs://b/in/records.parquet"])] and "CALL `p.run`.build()" in client.sent
    client = Recorded()
    assert run.main(["p.run", "match", "8"], client=client, bigquery=MODULE) == 0 and "CALL `p.run`.match(8.0)" in client.sent
    client = Recorded()
    assert run.main(["p.run", "decide", "gs://b/in/decided.parquet"], client=client, bigquery=MODULE) == 0
    assert client.loaded == [("p.run.given", ["gs://b/in/decided.parquet"])] and "CALL `p.run`.decide()" in client.sent
    assert run.main(["p.run", "lookup", "x"], client=Recorded(), bigquery=MODULE) == 2  # not a job BigQuery runs


PROCEDURE_FAILS = ("procedure", "interrupted", "interrupted as it ends", "changed", "refused", "no input", "unfinished",
                   "raced", "mark answer lost", "refused over lines")  # how a fake procedure call ends


DEPLOYED = {}  # each job's procedure as the deploy makes it in p.run, the body BigQuery's INFORMATION_SCHEMA.ROUTINES holds


class Tables(Recorded):  # a dataset's tables, each a version and a type, as BigQuery lists them: what a job's statements leave
    def __init__(self, tables: dict, job: dict | None = None, fail: tuple = (), deployed: dict | None = None):
        super().__init__()
        if not DEPLOYED:
            DEPLOYED.update({re.search(r"PROCEDURE `p\.run`\.(\w+)\(", x)[1]: x[x.index("\nBEGIN\n"):]
                             for x in procedures("p.run") if "CREATE OR REPLACE PROCEDURE" in x})
        self.deployed = {**DEPLOYED, **(deployed or {})}  # a test's procedure, as an older deploy left it
        self.tables, self.job = dict(tables), job or {}  # job: the procedure's tables (None: dropped)
        self.fails = list(fail)  # each in turn: a statement holding it fails, or the procedure (one of PROCEDURE_FAILS)
        self.kind = dict.fromkeys(tables, "BASE TABLE")
        self.mark, self.sessions, self.running, self.checked_in = {}, 0, set(), []
        self.loading = False  # a load into input that BigQuery still runs, its caller gone

    def query(self, sql, job_config=None, job_retry="the library's: a failed job sent again whole"):
        assert job_retry is None, job_retry  # a CALL begun again from its first statement loses the batch's records
        self.sent.append(sql)
        self.labels = getattr(job_config, "labels", None)  # the last query's
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
            if self.fails and self.fails[0] not in PROCEDURE_FAILS and self.fails[0] in s:
                self.fails.pop(0)
                raise RuntimeError(f"failed: {s[:60]}")
            if "INFORMATION_SCHEMA.TABLES" in s:
                kinds = re.findall(r"'([A-Z ]+)'", s)
                rows = [{"table_name": x} for x in sorted(self.tables) if self.kind[x] in kinds]
            elif "INFORMATION_SCHEMA.ROUTINES" in s:
                if self.fails[:1] == ["raced"]:  # another job makes its mark between this job's listing and its mark
                    self.fails.pop(0)
                    self.tables["job_running"], self.kind["job_running"] = "mark", "BASE TABLE"
                    self.mark = {"session": "another job's", "tables": []}
                rows = [{"routine_definition": self.deployed[given["job"]]}] if given["job"] in self.deployed else []
            elif "INFORMATION_SCHEMA.JOBS_BY_USER" in s:
                load = (self.loading and "job_type = 'LOAD'" in s and "input" in given.get("loaded", [])
                        and given.get("dataset") == "run")
                rows = [{"n": int(given["session"] in self.running or load)}]
                self.checked_in.append(getattr(job_config, "connection_properties", None))  # the session it ran in
            elif s.startswith("SELECT session, tables FROM"):
                rows = [self.mark]
            elif " RENAME TO " in s:
                new = s.rsplit(" ", 1)[1]
                self.tables[new], self.kind[new] = self.tables.pop(name[0]), self.kind.pop(name[0])
            elif s.startswith("CREATE TABLE") and name[0] in self.tables:
                raise RuntimeError(f"Already Exists: {name[0]}")
            elif " CLONE " in s:
                self.tables[name[0]], self.kind[name[0]] = self.tables[name[1]], "CLONE"
            elif s.startswith("CREATE TABLE"):  # the mark
                self.tables[name[0]], self.kind[name[0]] = "mark", "BASE TABLE"
                tail = s.split("AS session, ")
                self.mark = {"session": re.findall(r"'(\w*)'", tail[0])[-1], "tables": re.findall(r"'(\w*)'", tail[1])}
                if self.fails[:1] == ["mark answer lost"]:  # made, but its answer never reaches the job
                    self.fails.pop(0)
                    raise RuntimeError("Connection reset by peer")
            elif s.startswith("DROP TABLE"):
                if name[0] in self.tables or "IF EXISTS" not in s:  # IF EXISTS: a table that isn't there is no error
                    del self.tables[name[0]], self.kind[name[0]]
            elif s.startswith("CALL `p.run`."):
                if self.fails[:1] == ["changed"]:  # UNCHANGED: refused before the procedure writes anything
                    self.fails.pop(0)
                    raise RuntimeError(f"Query error: {nayose.CHANGED}; build the run again at [1:1]")
                if self.fails[:1] == ["refused over lines"]:  # a refusal whose message holds a line break
                    self.fails.pop(0)
                    raise RuntimeError("Query error: given: a decision is match or no_match, not\nmaybe; correct those "
                                       "rows at [p.run.decide:76:1]")
                if self.fails[:1] == ["unfinished"]:  # a deploy stopped partway: its stubs (procedures.stubs) refuse
                    self.fails.pop(0)
                    raise RuntimeError("400 GET https://x: Query error: deploy: the last deploy did not finish; deploy "
                                       "again at [p.run.build:3:1]")
                if self.fails[:1] == ["no input"]:  # a mapping reading input, which no file filled
                    self.fails.pop(0)
                    raise RuntimeError("Query error: Not found: Table p:run.input was not found in location asia-northeast1")
                if self.fails[:1] == ["refused"]:  # as BigQuery says decide.sql's ERROR: the decisions given are wrong
                    self.fails.pop(0)
                    raise RuntimeError("400 GET https://x: Query error: given: a decision is match or no_match, not "
                                       "maybe, match;; correct those rows, or leave them empty at [p.run.decide:76:1]\n\nJob ID: j")
                for x, v in self.job.items():
                    if v is None:
                        self.tables.pop(x, None), self.kind.pop(x, None)
                    else:
                        self.tables[x], self.kind[x] = v, "BASE TABLE"
                if self.fails[:1] == ["procedure"]:
                    self.fails.pop(0)
                    raise RuntimeError("the procedure failed partway")
                if self.fails[:1] == ["interrupted"]:  # the client stopped waiting: the procedure carries on in BigQuery
                    self.fails.pop(0)
                    self.running.add(session)
                    raise KeyboardInterrupt
                if self.fails[:1] == ["interrupted as it ends"]:  # the procedure done, its client stopped waiting then
                    self.fails.pop(0)
                    raise KeyboardInterrupt
        return SimpleNamespace(result=lambda rows=rows: rows, session_info=SimpleNamespace(session_id=session))

    def load_table_from_uri(self, uris, table, job_config=None):
        self.loaded.append((table, list(uris)))
        self.tables[table.split(".")[-1]], self.kind[table.split(".")[-1]] = "loaded", "BASE TABLE"
        return SimpleNamespace(result=lambda: None)

    def get_dataset(self, dataset):
        return SimpleNamespace(location="asia-northeast1")


def interrupt(*args, **kwargs):  # Ctrl-C
    raise KeyboardInterrupt


def test_a_job_on_bigquery_is_all_or_nothing_and_says_how_each_way_it_ends(monkeypatch, capsys):
    run = script("run")
    monkeypatch.setattr(run.nayose, "report_text", lambda engine, steps, job: "")
    build = ["p.run", "build", "gs://b/x.parquet"]
    before = {"records": 1, "scored": 1, "decisions": 1, "name_weights": 1}
    made = {"records": 2, "scored": None, "report_steps": 2}  # what the procedure leaves: one replaced, one dropped, one new
    after = {"records": 2, "decisions": 1, "name_weights": 1, "report_steps": 2}  # the loaded input dropped too

    def ends(client, argv=build) -> tuple[int, dict]:  # the exit code, and the JSON line said last
        code = run.main(argv, client=client, bigquery=MODULE)
        return code, json.loads(capsys.readouterr().err.strip().splitlines()[-1])

    done = Tables(before, made)
    code, said = ends(done)
    assert code == 0 and said["severity"] == "INFO" and "seconds" in said and done.tables == after  # no mark, no clone left
    cloned = set(re.findall(r"CLONE `p\.run`\.(\w+)", "\n".join(done.sent)))
    assert cloned == {"records", "scored", "decisions"}  # the tables a build writes: name_weights it never touches
    matching = Tables({"records": 1, "scored": 1, "matched": 1, "name_weights": 1}, {"matched": 2})
    assert ends(matching, ["p.run", "match", "8"])[0] == 0 and matching.tables["matched"] == 2
    assert set(re.findall(r"CLONE `p\.run`\.(\w+)", "\n".join(matching.sent))) == {"matched"}  # its one table
    older = Tables({"records": 1, "rule_pairs": 1}, {"rule_pairs": 2}, fail=["procedure"],  # prod's procedure, deployed
                   deployed={"update": "\nBEGIN\nINSERT INTO `p.run`.rule_pairs SELECT 1;\nEND"})  # before this code
    assert ends(older, ["p.run", "update", "gs://b/y.parquet"])[0] == 1 and older.tables["rule_pairs"] == 1  # put back
    assert ends(done)[0] == 0 and done.tables == after  # and the next job runs as well
    from_table = Tables({**before, "input": "an earlier job's"}, made)  # no file: the mapping reads the team's table
    code, said = ends(from_table, ["p.run", "build"])
    assert code == 0 and not from_table.loaded and from_table.tables["records"] == 2
    dropped, called = (next(i for i, s in enumerate(from_table.sent) if s.startswith(x))
                       for x in ("DROP TABLE IF EXISTS `p.run`.input", "CALL `p.run`.build()"))
    assert dropped < called  # an old batch is never read as this one
    no_input = Tables(before, made, fail=["no input"])  # no file, and a mapping that reads input
    code, said = ends(no_input, ["p.run", "update"])
    assert code == 2 and "p:run.input" in said["error"] and "docs/console.md" in said["fix"] and no_input.tables == before
    for short in (["p.run", "decide"], ["p.run", "match"]):  # a file or a threshold each needs: the help, exit 2
        client = Tables(before, made)
        assert run.main(short, client=client, bigquery=MODULE) == 2 and not client.sent
    failed = Tables(before, made, fail=["procedure"])
    code, said = ends(failed)
    assert code == 1 and said == {"severity": "ERROR", "job": "build", "dataset": "p.run", "error": "the procedure failed partway", "fix": "run this job again"}
    assert failed.tables == before  # each table from its clone, the one dropped too; the input and the new table dropped
    stuck = Tables(before, made, fail=["procedure", "CREATE OR REPLACE TABLE `p.run`.records CLONE"])  # and its undo fails
    code, said = ends(stuck)
    assert code == 1 and said["error"] == "the procedure failed partway" and said["undo_error"].startswith("failed: CREATE OR REPLACE TABLE")
    assert said["fix"] == "undo it (python deploy/run.py p.run undo), then run this job again" and "job_running" in stuck.tables
    assert ends(stuck, ["p.run", "undo"])[0] == 0 and stuck.tables == before
    left = Tables(before, made, fail=["DROP TABLE `p.run`.before__records"])  # a job done, its mark gone, a clone left behind
    code, said = ends(left)
    assert code == 1 and said["finished"] and said["failed"].startswith("ending it") and said["error"].startswith("failed: DROP TABLE")
    assert said["fix"] == "run nothing again: the next job drops the clones left" and "job_running" not in left.tables
    left.job, left.fails = {"records": 3}, ["CREATE TABLE `p.run`.before__records"]  # the next job fails cloning
    code, said = ends(left)
    assert code == 1 and said["error"].startswith("failed: CREATE TABLE") and said["fix"] == "run this job again"
    assert left.tables == after  # the left clone was dropped first, so nothing older came back
    renamed = Tables(before, made, fail=["DROP TABLE `p.run`.before__job_running"])  # a job done, its mark renamed, left
    code, said = ends(renamed)
    assert code == 1 and said["finished"] and said["fix"] == "run nothing again: the next job drops the clones left"
    assert "job_running" not in renamed.tables and "before__job_running" in renamed.tables
    assert ends(renamed, ["p.run", "undo"])[1]["undone"] is False  # no mark: every table as the job made it
    assert {t: v for t, v in renamed.tables.items() if not t.startswith("before__")} == after
    renamed.job = {"records": 3}
    assert ends(renamed)[0] == 0 and renamed.tables == {**after, "records": 3}  # the next job drops what was left, and runs
    marked = Tables(before, made, fail=["ALTER TABLE `p.run`.job_running RENAME"])  # a job done, its mark left: an undo would take it back
    code, said = ends(marked)
    assert code == 1 and said["finished"] and "drop the mark alone" in said["fix"] and "never undo" in said["fix"]
    monkeypatch.setattr(run.nayose, "report_text", lambda engine, steps, job: 1 / 0)
    unreported = Tables(before, made)
    code, said = ends(unreported)
    assert code == 1 and said["finished"] and said["failed"] == "report.txt" and said["error"] == "division by zero"
    assert unreported.tables == after and "run nothing again" in said["fix"]
    cut = Tables(before, made, fail=["interrupted"])  # stopped waiting mid-call: no undo while its procedure runs on
    code, said = ends(cut)
    assert code == 75 and said["cause"] == "KeyboardInterrupt" and said["fix"] == "undo once it ends: python deploy/run.py p.run undo"
    assert cut.tables["records"] == 2 and "job_running" in cut.tables
    cut.running = set()  # it ended: the undo it was told to run puts every table back
    assert ends(cut, ["p.run", "undo"]) == (0, {"severity": "INFO", "job": "undo", "dataset": "p.run", "undone": True}) and cut.tables == before
    assert cut.checked_in and not any(cut.checked_in)  # each check outside every session, so it never counts itself
    loading = Tables(before, made)  # Ctrl-C while the input loads, or as the procedure ends: undone, and said so
    loading.load_table_from_uri = interrupt
    for stopped in (loading, Tables(before, made, fail=["interrupted as it ends"])):
        code, said = ends(stopped)
        assert code == 1 and said["error"] == "KeyboardInterrupt" and said["fix"] == "run this job again" and stopped.tables == before
    changed = Tables(before, made, fail=["changed"])  # another method built the run: the procedure refuses it
    code, said = ends(changed, ["p.run", "update", "gs://b/y.parquet"])
    assert code == 2 and nayose.CHANGED in said["error"] and said["fix"] == nayose.build_again("update") and changed.tables == before
    refused = Tables(before, made, fail=["refused"])  # the file given is wrong: exit 2, what to fix, every table as it was
    code, said = ends(refused, ["p.run", "decide", "gs://b/d.parquet"])
    assert (code, said["error"], said["fix"]) == (2, "given: a decision is match or no_match, not maybe, match;",  # a ; given
                                                  "correct those rows, or leave them empty") and refused.tables == before
    alter = next(s for s in refused.sent if s.startswith("ALTER TABLE"))  # every column decide reads: one a file lacks
    assert all(f"`{c}`" in alter for c in ("id_l", "id_r", "decision", "why"))  # is empty, and decide.sql refuses it
    unfinished = Tables(before, made, fail=["unfinished"])  # a deploy stopped partway left its stubs: refused, exit 2
    code, said = ends(unfinished)
    assert (code, said["fix"]) == (2, "deploy again") and unfinished.tables == before
    raced = Tables(before, made, fail=["raced"])  # another job marked the dataset first: this one waits, and undoes nothing
    assert ends(raced)[0] == 75 and raced.tables == {**before, "job_running": "mark"}
    monkeypatch.setattr(run.nayose, "report_text", lambda engine, steps, job: "")  # report.txt works again
    lost = Tables(before, made, fail=["mark answer lost"])  # this job's own mark made, its answer lost: the job goes on
    assert ends(lost)[0] == 0 and lost.tables == after
    stub = {"build": "\nBEGIN\nSELECT ERROR('" + run.UNFINISHED + "');\nEND"}  # a deploy under way, done before the CALL
    stubbed = Tables({**before, "matched": 1}, made, deployed=stub)
    assert ends(stubbed)[0] == 0  # every table cloned, matched too, which a build's procedure never writes
    assert set(re.findall(r"CLONE `p\.run`\.(\w+)", "\n".join(stubbed.sent))) == {"records", "scored", "decisions", "matched"}
    lines = Tables(before, made, fail=["refused over lines"])
    code, said = ends(lines, ["p.run", "decide", "gs://b/d.parquet"])
    assert (code, said["fix"]) == (2, "correct those rows") and "\nmaybe" in said["error"]
    left = Tables(before, made)  # Ctrl-C while BigQuery loads the file: the load runs on, so undo waits for it

    def load_left_running(uris, table, job_config=None):
        left.loading = True
        raise KeyboardInterrupt
    left.load_table_from_uri = load_left_running
    code, said = ends(left)
    assert code == 75 and said["fix"] == "undo once it ends: python deploy/run.py p.run undo"
    left.loading = False  # it ended: the undo puts every table back
    assert ends(left, ["p.run", "undo"])[0] == 0 and left.tables == before
    for threshold in ("nan", "inf", "8,5", "-1"):  # no number of points, or under keep_from: refused before any query
        nothing = Tables(before, made)
        code, said = ends(nothing, ["p.run", "match", threshold])
        assert code == 2 and not nothing.sent and ("keep_from" in said["fix"]) == (threshold == "-1"), threshold
    monkeypatch.setattr(run.nayose, "lookup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    code, said = ends(Tables(before, made), ["p.run", "lookup", "--record", "1"])  # a lookup that fails says so too
    assert (code, said["error"], said["fix"]) == (1, "boom", "look it up again")

    died = Tables(before, made)  # a job whose process died, its procedure run: the next job refuses; undo waits for it, then undoes
    assert run.begin(run.BigQuery("p.run", client=died, bigquery=MODULE), "p.run", "build") is not None
    died.query("CALL `p.run`.build()", job_retry=None)
    died.running, died.tables["name_weights"] = {"s1"}, 2  # its procedure still running; a deploy since, with a new name model
    assert ends(died, ["p.run", "match", "8"])[0] == 75 and not [s for s in died.sent if s.startswith("CALL `p.run`.match")]
    assert ends(died, ["p.run", "undo"])[0] == 75 and died.tables["records"] == 2
    died.running, died.fails = set(), ["DROP TABLE `p.run`.report_steps"]  # it ended; an undo stopped partway runs again
    code, said = ends(died, ["p.run", "undo"])
    assert code == 1 and said["error"].startswith("failed: DROP TABLE") and said["fix"] == "undo again: python deploy/run.py p.run undo"
    assert ends(died, ["p.run", "undo"])[0] == 0 and died.tables == {**before, "name_weights": 2}
    assert ends(died, ["p.run", "undo"])[1]["undone"] is False and died.tables == {**before, "name_weights": 2}  # nothing marked


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
    assert client.labels == {"nayose_job": "lookup"}  # each query labelled with its job: INFORMATION_SCHEMA.JOBS by job
    client.tables["before__job_running"], client.kind["before__job_running"] = "mark", "BASE TABLE"  # a job done's, left
    assert run.main(["p.run", "lookup", "--record", "123"], client=client, bigquery=MODULE) == 0
    client.tables["job_running"], client.kind["job_running"] = "mark", "BASE TABLE"
    assert run.main(["p.run", "lookup", "--record", "123"], client=client, bigquery=MODULE) == 75
    assert run.main(["p.run", "lookup", "name"], client=Tables({}), bigquery=MODULE) == 2


def test_the_sandbox_check_sends_each_dml_statement_as_ddl_that_leaves_the_same_rows():
    from nayose.engines import DuckDB
    check = script("bigquery_check")
    for sql in ("DELETE FROM t WHERE id IN (SELECT id FROM gone)",  # gone holds a NULL: NOT IN would keep nothing
                "INSERT INTO t SELECT id + 10, v FROM t WHERE v IS NOT NULL  -- a comment closing the statement",
                "INSERT INTO t (id, v) SELECT 99, 'z'",
                "UPDATE t SET v = (SELECT MAX(v) FROM t) WHERE id = 2"):
        left = []
        for text in (sql, check.as_ddl(sql, set())):
            engine = DuckDB()
            engine.run("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'a'), (2, NULL), (3, 'c')) AS x(id, v)")
            engine.run("CREATE TABLE gone AS SELECT 1 AS id UNION ALL SELECT NULL")
            engine.run(text)
            left.append(engine.rows("SELECT * FROM t ORDER BY id"))
        assert left[0] == left[1], sql
    assert check.as_ddl("UPDATE t SET v = 1 WHERE id = 2", {"t"}, {"t": "id"}).startswith("CREATE OR REPLACE TEMP TABLE t AS")
    assert check.as_ddl("DELETE FROM t WHERE id = 2", set(), {"t": "id"}).startswith("CREATE OR REPLACE TABLE t CLUSTER BY id AS")
    for job in [s for s in procedures("p.run") if "CREATE OR REPLACE PROCEDURE" in s]:  # every job's, none left
        sent = ";\n".join(check.as_ddl(x, set()) for x in nayose.statements(job + ";"))
        assert not check.DML.search(re.sub(r"--[^\n]*", "", sent)), job[:60]

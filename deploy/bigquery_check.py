"""Run every job on a BigQuery sandbox, a project without billing, and hold what each leaves to DuckDB's, for free.

    python deploy/bigquery_check.py PROJECT [--entities 400] [--plans plans.json] [--keep]

It deploys nayose (deploy/deploy.py) in the dataset PROJECT.nayose_check, made anew, then runs the jobs through
deploy/run.py on the tests' generated records: a build, an update, a match, people's decisions, a match again, two
lookups, and a decide that fails and is undone. DuckDB runs the same jobs on the same files. Every table each job
leaves (tests/test_parity.py's, floats to 9 places) and each lookup's answer must be the same on both.
Each procedure's statements are listed with what BigQuery measured (slot time, bytes processed and billed), the
costliest printed; --plans writes every statement's, with its query plan's stages, to a JSON file. The run's tables'
size is printed last: a sandbox stores 10 GiB in its lifetime, and deleting a table gives none of it back.

A sandbox refuses DML, so the check's client (Sandbox) sends each DML statement as the DDL that leaves its table the
same rows (as_ddl), and loads the jobs' files from this machine, as a sandbox has no Cloud Storage. Before anything
else it makes sure the project refuses DML: a project that takes it bills, and the check stops.
Not checked here: DML as BigQuery runs it (an INSERT's types are: records' columns are held to records.sql's), Cloud
Storage, a billed project's costs and quotas, and anything past the generated records' size.
Needs pydata-google-auth (pip install pydata-google-auth): a browser sign-in, kept in ~/.config/pydata.
"""
import argparse
import importlib.util
import io
import json
import re
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # this checkout's nayose and design

import nayose  # noqa: E402
from nayose.engines import FUNCTIONS, BigQuery, DuckDB  # noqa: E402
from nayose.procedures import TEMP_TABLE as TEMP  # noqa: E402

SCOPE = ["https://www.googleapis.com/auth/bigquery"]
# US list prices (cloud.google.com/bigquery/pricing; asia-northeast1's are higher, in about the same ratio): on demand
# bills bytes, a Standard edition reservation slot time, by the second with fluid scaling. Standard is the cheaper
# where a job bills more than PER_SLOT_HOUR / PER_TIB TiB a slot-hour, about 6.6 GiB. Its cost here is the slot time
# used, the least a reservation bills: the autoscaler adds slots 50 at a time, so a short job bills more.
PER_TIB, PER_SLOT_HOUR = 6.25, 0.04
ROWS_UP_TO = 4000  # entities: past these, each table is compared by its rows' count, as reading every row costs quota
SEEN = ((0x0000, 0x024F), (0x2000, 0x206F), (0x3000, 0x30FF), (0x3400, 0x9FFF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF))
DML = re.compile(r"\b(DELETE FROM|INSERT INTO|UPDATE(?=\s+\S+\s+SET\b))\s+((?:`[^`]+`\.)?(\w+))\s*")
CLUSTERED = re.compile(r"CREATE TABLE IF NOT EXISTS (?:`[^`]+`\.)?(\w+)\b[^;]*?\bCLUSTER BY ((?:\w+\s*,\s*)*\w+)")


def as_ddl(statement: str, temp: set, clusters: dict | None = None) -> str:
    """Return a DML statement as the DDL that leaves its table the same rows; any other statement as it is.

    DELETE FROM t WHERE c          CREATE OR REPLACE TABLE t AS SELECT * FROM t WHERE (c) IS NOT TRUE
    INSERT INTO t [(columns)] q    CREATE OR REPLACE TABLE t AS SELECT * | columns FROM t UNION ALL (q)
    UPDATE t SET x = v WHERE c     CREATE OR REPLACE TABLE t AS SELECT * REPLACE (IF((c) IS TRUE, v, x) AS x) FROM t
    A table in `temp` is made TEMP, and one of the run's in `clusters` keeps its CLUSTER BY, as BigQuery replaces a
    table only with its own. A column list must be the table's columns in order, and an UPDATE sets one column.
    """
    code = blanked(statement)
    m = DML.search(code)
    if not m:
        return statement
    head, verb, table, rest = statement[:m.start()], m[1], m[2], statement[m.end():]
    clustered = f"CLUSTER BY {clusters[m[3]]} " if m[3] in (clusters or {}) and m[3] not in temp else ""
    made = f"{head}CREATE OR REPLACE {'TEMP ' if m[3] in temp else ''}TABLE {table} {clustered}AS "
    if verb == "DELETE FROM":
        return f"{made}SELECT * FROM {table} WHERE (\n{re.sub(r'^WHERE', '', rest.strip())}\n) IS NOT TRUE"
    if verb == "INSERT INTO":
        listed = re.match(r"\(([^)]*)\)\s*", rest)
        columns, query = (listed[1], rest[listed.end():]) if listed else ("*", rest)
        return f"{made}SELECT {columns} FROM {table} UNION ALL (\n{query}\n)"
    column, value, condition = re.fullmatch(r"SET\s+(\w+)\s*=\s*([\s\S]+?)\s+WHERE\s+([\s\S]+)", rest.strip()).groups()
    return f"{made}SELECT * REPLACE (IF(({condition}) IS TRUE, {value}, {column}) AS {column}) FROM {table}"


def blanked(sql: str) -> str:
    """Return `sql` with its -- comments made spaces, so that each position holds."""
    return re.sub(r"--[^\n]*", lambda m: " " * len(m[0]), sql)


class Sandbox:
    """A BigQuery client for a sandbox: DML sent as DDL (as_ddl), a job's files loaded from this machine.

    It keeps the session's temporary tables' names, as an UPDATE of a lookup's records is one, counts the bytes each
    query processed, and keeps each CALL's job, whose statements plan_of lists.
    """

    def __init__(self, client: object) -> None:
        self.client, self.temp, self.bytes, self.queries, self.calls, self.clusters = client, set(), 0, 0, [], {}

    def query(self, sql: str, job_config: object = None) -> object:
        if job_config is not None and getattr(job_config, "create_session", False):
            self.temp = set()  # a new session: none of the old one's temporary tables
        temp = self.temp | set(TEMP.findall(sql))
        self.clusters |= dict(CLUSTERED.findall(blanked(sql)))  # each table as first made, in the SQL that makes it
        pieces = nayose.statements(sql + ";") if DML.search(sql) else None
        sent = ";\n".join(as_ddl(s, temp, self.clusters) for s in pieces) if pieces else sql
        if not sql.lstrip().upper().startswith("CREATE OR REPLACE PROCEDURE"):
            self.temp |= set(TEMP.findall(sql))  # a procedure's temporary tables are made when it is called
        job = self.client.query(sent, job_config=job_config)
        self.queries += 1
        if sql.lstrip().startswith("CALL `"):  # a job's procedure, not BQ.ABORT_SESSION
            self.calls.append(job)
        return Counted(job, self)

    def load_table_from_uri(self, uris: list[str], table: str, job_config: object = None) -> object:
        (path,) = uris  # one file a job, here
        with open(path, "rb") as f:
            return self.client.load_table_from_file(f, table, job_config=job_config)

    def __getattr__(self, name: str) -> object:
        return getattr(self.client, name)


class Counted:
    """A query job that adds the bytes it processed to its Sandbox's count once its result is read."""

    def __init__(self, job: object, sandbox: Sandbox) -> None:
        self.job, self.sandbox = job, sandbox

    def result(self, *args, **kwargs) -> object:
        out = self.job.result(*args, **kwargs)
        self.sandbox.bytes += self.job.total_bytes_processed or 0
        return out

    def __getattr__(self, name: str) -> object:
        return getattr(self.job, name)


def script(name: str) -> object:
    """Return deploy/<name>.py as a module."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def files(folder: Path, entities: int) -> tuple[dict[str, Path], str]:
    """Write the jobs' files from the tests' generated population (tests/conftest.py's), as tests/test_parity.py
    makes its runs: the first half, with two crowds of 70 (one block the gate skips, one it lists); the rest, with 70
    records of one phone number, a placeholder the update finds, so records are made again.

    Return them, and a name of the first file's, for a typed lookup.
    """
    import pandas as pd
    from design.generate import generate, load_reference, load_spec
    spec = replace(load_spec(ROOT / "config" / "generator.toml")[0], entities=entities, households={})
    df = generate(spec, *load_reference(ROOT / "data" / "reference")).df
    named = df[df["FULL_NAME_KANA"].notna()]
    crowd, kin = named.head(70).copy(), named.iloc[70:140].copy()
    crowd["CONT_ID"], kin["CONT_ID"] = [f"9{i:09d}" for i in range(70)], [f"8{i:09d}" for i in range(70)]
    crowd["GIVEN_NAME_KANA"], crowd["POST_CD"] = "タロウ", "1000005"
    kin["FULL_NAME_KANA"], kin["GIVEN_NAME_KANA"], kin["POST_CD"] = "ヤマダ ハナコ", "ハナコ", "1500001"
    kin["CIF_ID"] = ["80000001", "80000002"] * 35
    first, rest = df.iloc[: len(df) // 2].copy(), df.iloc[len(df) // 2:]
    first.loc[first.index[:2], "PHONE_NUM_4"] = "4321"
    many = df.iloc[140:210].copy().assign(CONT_ID=[f"7{i:09d}" for i in range(70)], PHONE_NUM_4="4321", CIF_ID=None)
    out = {"first": folder / "first.parquet", "batch": folder / "batch.parquet"}
    pd.concat([first, crowd, kin]).to_parquet(out["first"], index=False)
    pd.concat([rest, many]).to_parquet(out["batch"], index=False)
    return out, str(first["FULL_NAME_KANA"].dropna().iloc[0])


def normal(v: object) -> object:
    """Return a value as both engines' rows can be compared: floats to 9 places, arrays as tuples, NaN as None."""
    if hasattr(v, "tolist") and not isinstance(v, (str, bytes)):
        v = v.tolist()
    if isinstance(v, (list, tuple)):
        return tuple(normal(x) for x in v)
    if isinstance(v, dict):
        return {k: normal(x) for k, x in sorted(v.items())}
    if isinstance(v, float):
        return None if v != v else round(v, 9) + 0.0
    return v


def same(what: str, ours: list, theirs: list) -> bool:
    """Print PASS or FAIL for two lists of rows, compared in order, and the first that differs; return whether same."""
    a, b = [normal(r) for r in ours], [normal(r) for r in theirs]
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None if len(a) == len(b) else min(len(a), len(b)))
    detail = f"{len(a)} rows" if first is None else f"DuckDB {len(a)} rows, BigQuery {len(b)}; row {first} differs"
    if first is not None and first < min(len(a), len(b)):
        cut = [j for j, (x, y) in enumerate(zip(a[first], b[first])) if x != y][:3]
        detail += ": " + "; ".join(f"column {j}: {a[first][j]!r} / {b[first][j]!r}" for j in cut)
    return say(what, first is None, detail)


failed: list[str] = []


def say(check: str, ok: bool, detail: str = "") -> bool:
    """Print one check's line, counting it if it failed; return ok."""
    print(f"{'PASS' if ok else 'FAIL'}  {check}" + (f": {detail}" if detail else ""), flush=True)
    if not ok:
        failed.append(check)
    return ok


def tables(duck: DuckDB, bq: BigQuery, step: str, rows: bool) -> None:
    """Compare each of test_parity's tables on both engines after a step: every row, or (rows false) their count.

    A table that is temporary on BigQuery (gated) ends with its job's session, so it is named and left out.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    from test_parity import TABLES
    kept = {t.table_id for t in bq.client.list_tables(bq.dataset)}
    for name, sql in TABLES.items():
        if name not in kept:
            print(f"SKIP  {step}: {name}: temporary on BigQuery, gone with its job", flush=True)
            continue
        sql = sql if rows else f"SELECT COUNT(*) FROM ({sql})"
        same(f"{step}: {name}" + ("" if rows else ", rows counted"), duck.rows(sql), bq.rows(sql))


def same_functions(duck: DuckDB, bq: BigQuery) -> None:
    """Hold the deployed functions to DuckDB's twins: each comparison and er_hash on pairs of the run's names, and nfkc
    on every code point to Python's NFKC (DuckDB's twin), in the blocks the records' characters come from (SEEN)."""
    import unicodedata

    import pandas as pd
    names = [n for (n,) in duck.rows("SELECT person_name FROM records WHERE person_name IS NOT NULL ORDER BY id")]
    a = [*names, "", "サトウ", "ｻﾄｳ", "佐藤", "サトー", "ab", "ヴァ"]
    b = [*names[1:], names[0], "", "サトウ", "サトウ", "佐籐", "サトウ", "ba", "バ"]
    duck.put("pairs", pd.DataFrame({"i": range(len(a)), "a": a, "b": b}))
    calls = ", ".join([*(f"cl_{n}(a, b)" for n in FUNCTIONS), "er_hash(a)"])
    ours = duck.rows(f"SELECT {calls} FROM pairs ORDER BY i")
    theirs = bq.rows(f"SELECT {calls} FROM UNNEST(@a) AS a WITH OFFSET AS i JOIN UNNEST(@b) AS b WITH OFFSET AS j "
                     "ON i = j ORDER BY i", {"a": a, "b": b})
    same(f"cl_{', cl_'.join(FUNCTIONS)} and er_hash on {len(a)} pairs", ours, theirs)
    points = [c for c in range(1, 0x30000) if not 0xD800 <= c <= 0xDFFF]
    got = [n for (n,) in bq.rows("SELECT nfkc(CODE_POINTS_TO_STRING([c])) FROM UNNEST(GENERATE_ARRAY(1, 196607)) AS c "
                                 "WHERE c NOT BETWEEN 55296 AND 57343 ORDER BY c")]
    differ = [c for c, n in zip(points, got) if n != unicodedata.normalize("NFKC", chr(c))]
    seen = [c for c in differ if any(lo <= c <= hi for lo, hi in SEEN)]
    say(f"nfkc as Python's NFKC (Unicode {unicodedata.unidata_version}) in the records' blocks", not seen,
        f"{len(points) - len(differ):,} of {len(points):,} code points the same; differ: "
        + (" ".join(f"U+{c:04X}" for c in differ[:12]) or "none") + (" …" if len(differ) > 12 else ""))


def schema_kept(bq: BigQuery) -> None:
    """Hold records' columns to records.sql's: an INSERT sent as UNION ALL would widen a type an INSERT refuses."""
    declared = re.search(r"CREATE TABLE IF NOT EXISTS records \(([\s\S]*?)\)\s*CLUSTER",
                         (nayose.SQL / "records.sql").read_text(encoding="utf-8"))[1]
    want = [tuple(c.split()) for c in " ".join(declared.split()).split(", ")]
    got = [(n, t.replace("FLOAT", "FLOAT64").replace("INTEGER", "INT64").replace("BOOLEAN", "BOOL"))
           for n, t in bq.columns("records")]
    say("records' columns as records.sql declares them", got == want, f"{len(got)} columns")


def job(run: object, client: Sandbox, dataset: str, plans: list, *argv: str) -> tuple[int, str]:
    """Run one job through deploy/run.py; print its last line and its costliest statements, adding them all to
    `plans`; return its exit code and what it printed."""
    out, err, calls = io.StringIO(), io.StringIO(), len(client.calls)
    with redirect_stdout(out), redirect_stderr(err):
        code = run.main([dataset, *argv], client=client)
    said = err.getvalue().strip().splitlines()[-1] if err.getvalue().strip() else ""
    print(f"      {argv[0]}: exit {code} {said if code else ''}", flush=True)
    for call in client.calls[calls:]:
        statements, call = plan_of(client.client, call), client.client.get_job(call.job_id)  # its times, read again
        plans.append({"job": argv[0], "seconds": (call.ended - call.started).total_seconds(), "statements": statements})
        slot, done = sum(x["slot_ms"] for x in statements) / 1000, plans[-1]["seconds"]
        print(f"      {len(statements)} statements in {done:,.0f} s: {slot:,.1f} slot-seconds, "
              f"{sum(x['processed'] for x in statements) / 1e6:,.0f} MB processed, "
              f"{sum(x['billed'] for x in statements) / 1e6:,.0f} MB billed; the costliest:")
        billed, slot_hours = sum(x["billed"] for x in statements), slot * 1000 / 3_600_000
        print(f"      on demand ${billed / 2 ** 40 * PER_TIB:.4f}, Standard ${slot_hours * PER_SLOT_HOUR:.4f}: "
              f"{billed / 2 ** 30 / max(slot_hours, 1e-9):,.1f} GiB a slot-hour, Standard the cheaper above "
              f"{PER_SLOT_HOUR / PER_TIB * 1024:.1f}")
        for x in sorted(statements, key=lambda x: -x["slot_ms"])[:5]:
            print(f"        {x['slot_ms'] / 1000:7.1f} slot-s {x['processed'] / 1e6:7.1f} MB  {x['what'][:80]}")
    return code, out.getvalue()


def plan_of(client: object, call: object) -> list[dict]:
    """Return each statement a CALL ran, in order, with what BigQuery measured and its query plan's stages."""
    out = []
    for child in sorted(client.list_jobs(parent_job=call.job_id), key=lambda j: j.created):
        j = client.get_job(child.job_id)  # the whole job: a listed one may lack its plan
        out.append({
            "what": " ".join(re.sub(r"--[^\n]*|/\*[\s\S]*?\*/", " ", j.query or "").split())[:300],
            "type": j.statement_type, "seconds": (j.ended - j.started).total_seconds() if j.started and j.ended else 0,
            "slot_ms": j.slot_millis or 0, "processed": j.total_bytes_processed or 0,
            "billed": j.total_bytes_billed or 0,
            "stages": [{"name": x.name, "slot_ms": x.slot_ms, "read": x.records_read, "written": x.records_written,
                        "shuffle": x.shuffle_output_bytes, "spilled": x.shuffle_output_bytes_spilled,
                        "compute_avg_ms": x.compute_ms_avg, "compute_max_ms": x.compute_ms_max,
                        "steps": [f"{step.kind}: {'; '.join(step.substeps)}" for step in x.steps]}
                       for x in j.query_plan or []]})
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the check in the project the arguments name; return 0 if every check passed, else 1."""
    p = argparse.ArgumentParser(prog="deploy/bigquery_check.py", description="every job on a BigQuery sandbox")
    p.add_argument("project", help="a project without billing (a BigQuery sandbox)")
    p.add_argument("--location", default="asia-northeast1", help="the dataset's location")
    p.add_argument("--keep", action="store_true", help="keep the dataset nayose_check to look at")
    p.add_argument("--entities", type=int, default=400, help="the generated population's entities (the tests': 400)")
    p.add_argument("--plans", type=Path, help="write each statement's costs and query plan to this JSON file")
    a = p.parse_args(argv)
    import pydata_google_auth
    from google.cloud import bigquery
    real = bigquery.Client(project=a.project, location=a.location,
                           credentials=pydata_google_auth.get_user_credentials(SCOPE))
    dataset, client = f"{a.project}.nayose_check", None
    real.delete_dataset(dataset, delete_contents=True, not_found_ok=True)
    real.create_dataset(bigquery.Dataset(dataset))
    try:
        real.query(f"CREATE TABLE `{dataset}`.billing AS SELECT 1 AS x").result()
        try:
            real.query(f"INSERT INTO `{dataset}`.billing (x) VALUES (2)").result()
            say("the project refuses DML: no billing", False, "it took an INSERT, so it bills: stopped")
            return 1
        except Exception as e:  # noqa: BLE001 -- the refusal is the answer
            if not say("the project refuses DML: no billing", "Billing has not been enabled" in str(e), str(e)[:120]):
                return 1
        client = Sandbox(real)
        run, folder = script("run"), Path(tempfile.mkdtemp(prefix="nayose_check_"))
        given, name, plans = *files(folder, a.entities), []
        say("deploy", script("deploy").main([dataset], client=client) == 0)
        duck, bq = DuckDB(), BigQuery(dataset, client=real)

        nayose.build(duck, [given["first"]])
        code, report = job(run, client, dataset, plans, "build", str(given["first"]))
        say("build, and its report.txt", code == 0 and "ENTITIES" in report)
        rows = a.entities <= ROWS_UP_TO
        matched = "SELECT * FROM matched ORDER BY id_l, id_r" if rows else "SELECT COUNT(*) FROM matched"
        tables(duck, bq, "build", rows)
        nayose.update(duck, [given["batch"]])
        code, report = job(run, client, dataset, plans, "update", str(given["batch"]))
        say("update, and its report.txt", code == 0 and "ENTITIES" in report)
        tables(duck, bq, "update", rows)
        schema_kept(bq)
        same_functions(duck, bq)

        nayose.match(duck, 6.0)
        say("match", job(run, client, dataset, plans, "match", "6")[0] == 0)
        same("match: matched", *(e.rows(matched) for e in (duck, bq)))
        decided = duck.frame("SELECT id_l, id_r, CASE WHEN rule IS NOT NULL OR points >= 12 THEN 'match' "
                             "ELSE 'no_match' END AS decision FROM matched")
        decided.to_parquet(folder / "decided.parquet", index=False)
        nayose.decide(duck, [folder / "decided.parquet"])
        say("decide", job(run, client, dataset, plans, "decide", str(folder / "decided.parquet"))[0] == 0)
        tables(duck, bq, "decide", rows)
        nayose.match(duck, 6.0)
        say("match again", job(run, client, dataset, plans, "match", "6")[0] == 0)
        same("match again: matched", *(e.rows(matched) for e in (duck, bq)))

        record = duck.value("SELECT id FROM records ORDER BY id LIMIT 1")
        for asked, words in ((dict(record=record), ["--record", record]),
                             (dict(record="9000000000"), ["--record", "9000000000"]),  # in the crowd the gate lists
                             (dict(values={"FULL_NAME_KANA": name, "PHONE_NUM_4": "1234"}),
                              ["FULL_NAME_KANA=" + name, "PHONE_NUM_4=1234"]),
                             (dict(values={"FULL_NAME_KANA": "ヤマダ ハナコ", "POST_CD": "1500001"}),  # the kin
                              ["FULL_NAME_KANA=ヤマダ ハナコ", "POST_CD=1500001"])):
            ours = nayose.lookup(duck, **asked)
            code, _ = job(run, client, dataset, plans, "lookup", *words)
            theirs = json.loads(bq.value("SELECT answer FROM looked_up ORDER BY asked_at DESC LIMIT 1"))
            say(f"lookup {' '.join(words)[:40]}: exit 0", code == 0)
            same(f"lookup {' '.join(words)[:40]}: the answer", [json.loads(json.dumps(ours))], [theirs])

        before = {n: bq.rows(s) for n, s in (("decisions", "SELECT * FROM decisions ORDER BY id_l, id_r, round"),
                                             ("gold", "SELECT * FROM gold ORDER BY id"))}
        decided.assign(decision="maybe").to_parquet(folder / "wrong.parquet", index=False)
        code, _ = job(run, client, dataset, plans, "decide", str(folder / "wrong.parquet"))
        say("a decide given a wrong file is refused (exit 2) and undone", code == 2)
        for n, rows in before.items():
            same(f"undone: {n} as before", rows, bq.rows(f"SELECT * FROM {n} ORDER BY " +
                                                         ("id_l, id_r, round" if n == "decisions" else "id")))
        left = [t for (t,) in bq.rows(f"SELECT table_name FROM `{dataset}`.INFORMATION_SCHEMA.TABLES "
                                      "WHERE STARTS_WITH(table_name, 'before__') OR table_name IN "
                                      "('job_running', 'input', 'given')")]
        say("no mark, clone or loaded file left", not left, ", ".join(left))
        size = sum(real.get_table(t.reference).num_bytes or 0 for t in real.list_tables(dataset))
        print(f"the run's tables hold {size / 1e6:,.1f} MB, its temporary tables aside")
        if a.plans:
            a.plans.write_text(json.dumps(plans, indent=1, default=str), encoding="utf-8")
    finally:
        if client is not None:
            print(f"used {client.queries} queries, {client.bytes / 1e9:.2f} GB processed of the free 1 TB a month")
        if not a.keep:
            real.delete_dataset(dataset, delete_contents=True, not_found_ok=True)
    print("every check passed" if not failed else f"{len(failed)} failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

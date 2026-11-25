"""What the deploy makes in a run's BigQuery dataset: the functions (functions) and one procedure a job (procedures).

A procedure is its job's stages' statements in order, as the SQL files hold them, made for BigQuery: each of the
run's tables named with its dataset (in_dataset), each @value a declared variable, each -- when: an IF, decided at
the deploy where it reads only a declared TRUE or FALSE (folded) and asked once where IFs ask it again
(queried_once). deploy/deploy.py runs what these return; the engines (nayose.engines) run the statements here and
on DuckDB alike. For example, score.sql's

    -- when: NOT @lookup AND EXISTS (SELECT 1 FROM this_batch WHERE batch = 0)
    CREATE OR REPLACE TEMP TABLE rule_blocks AS ... FROM rule_keys ...

is in the build procedure, whose v_lookup is FALSE (values_of), as

    SET v_condition_3 = (EXISTS(SELECT 1 FROM this_batch WHERE batch = 0));   asked once: key_blocks asks it too,
    IF v_condition_3 THEN                                                        and the next two ask NOT it
    CREATE OR REPLACE TEMP TABLE rule_blocks AS ... FROM `project.dataset`.rule_keys ...;
    END IF

(this_batch is the job's temporary table, so it keeps no dataset).
"""
import re
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.simplify import simplify

import nayose
from nayose import TEMP_FUNCTION, WRITE, em, entities
from nayose.engines import BUILT_IN, FUNCTIONS, STRINGS, bigquery_literal, bigquery_type, qualified


def functions(dataset: str) -> list[str]:
    """Return the statements that make the method's non-SQL functions in `dataset` (project.dataset), run once a deploy.

    They are: each comparison of FUNCTIONS, as cl_<name> and cl_<name>_cut (the same score; the threshold isn't read),
    in JavaScript or over BigQuery's own function (BUILT_IN); the portable hash er_hash; nfkc; one_byte_hash; and the
    Python UDFs, EM's fit_model (nayose/em.py) and decide's entities_of (nayose/entities.py).
    """
    library = STRINGS.read_text(encoding="utf-8")
    out = []
    for name in FUNCTIONS:
        if name in BUILT_IN:  # BigQuery's own, counting characters as the twin does: no JavaScript
            own, made = BUILT_IN[name], f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}"
            out.append(f"{made}(a STRING, b STRING) AS (CAST({own}(a, b) AS FLOAT64))")
            # past the threshold, threshold + 1, as the cut twin gives
            out.append(f"{made}_cut(a STRING, b STRING, threshold FLOAT64) AS "
                       f"(CAST(LEAST({own}(a, b), FLOOR(threshold) + 1) AS FLOAT64))")
            continue
        body = f"{library}\nreturn a === null || b === null ? null : {name}(a, b);"
        for suffix, extra in (("", ""), ("_cut", ", threshold FLOAT64")):
            out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.cl_{name}{suffix}(a STRING, b STRING{extra}) "
                       f"RETURNS FLOAT64 LANGUAGE js AS r\"\"\"{body}\"\"\"")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.er_hash(x ANY TYPE) AS "
               "(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(COALESCE(CAST(x AS STRING), ''))), 1, 15)) AS INT64))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.nfkc(x STRING) AS (NORMALIZE(x, NFKC))")
    out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.one_byte_hash(x STRING) AS "
               "(CODE_POINTS_TO_STRING(ARRAY(SELECT 33 + MOD(c, 94) "
               "FROM UNNEST(TO_CODE_POINTS(x)) AS c WITH OFFSET AS i ORDER BY i)))")
    python_udfs = ((em, "fit_model", "counts STRING, settings STRING, given_fit STRING", "fit"),
                   (entities, "entities_of", "pairs STRING", "of"))
    for module, name, args, entry in python_udfs:
        source = Path(module.__file__).read_text(encoding="utf-8")  # python-3.11 there, and the standard library only
        assert "'''" not in source, f"{module.__name__}: no triple single quotes, which end BigQuery's raw string"
        out.append(f"CREATE OR REPLACE FUNCTION `{dataset}`.{name}({args}) RETURNS STRING LANGUAGE python "
                   f"OPTIONS (runtime_version = 'python-3.11', entry_point = '{entry}') AS r'''{source}'''")
    return out


# A new job reaches, besides JOBS: values_of for a new stage (nayose/__init__.py), which the fingerprint hashes for
# every stage named here; its local job and CLI command (nayose/__init__.py, nayose/__main__.py); deploy/run.py's
# call_procedure, for the files it loads and the arguments it passes; and tests/test_deploy.py.
# Each job BigQuery runs as a procedure of the run's dataset: its stages in order, each with what values_of() is told.
# There is no lookup procedure: nayose.lookup runs its own statements, each step in a session of its own
# (BigQuery.scratch), writing temporary tables alone.
JOBS = {
    "build": [("functions", {}), ("mapping", {}), ("records", {}), ("fit", {"refit": True}), ("score", {}),
              ("decide", {"given": False}), ("report", {})],
    "update": [("functions", {}), ("mapping", {}), ("records", {}), ("score", {}),
               ("decide", {"given": False}), ("report", {})],
    "decide": [("functions", {}), ("decide", {"given": True})],
    "match": [("functions", {}), ("match", {})],
}
ARGUMENTS = {"match": {"threshold": "FLOAT64"}}  # a procedure's own values: given when it is called, not declared
KEPT = ("decisions",)  # people's decisions: a build keeps them, as the CLI's build does


def in_dataset(sql: str, dataset: str, temp: set = frozenset()) -> str:
    """Return a statement with each table it names written with the dataset, but a WITH's names and `temp`'s.

    BigQuery reads a procedure's and a view's tables without a default dataset: SET @@dataset_id names none there.
    The rest of the statement is as written, its comments too: each name is found by its place in the parse.
    """
    tree = sqlglot.parse_one(sql, read="bigquery")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    starts = {t.this.meta["start"] for t in tree.find_all(exp.Table)
              if isinstance(t.this, exp.Identifier) and not t.args.get("db") and t.name not in ctes | set(temp)}
    for start in sorted(starts, reverse=True):
        sql = f"{sql[:start]}`{dataset}`.{sql[start:]}"
    return sql


def stage_statements(stage: str, mapping: Path | None) -> list[str]:
    """Return a stage's statements: its file's, or, for the stage mapping, the deployment's mapping, checked."""
    if stage == "mapping":
        return nayose.mapping_statements(mapping or nayose.mapping())  # the one fingerprint() hashes
    return nayose.statements((nayose.SQL / f"{stage}.sql").read_text(encoding="utf-8"))


def procedures(dataset: str, mapping: Path | None = None) -> list[str]:
    """Return the statements the deploy runs in `dataset` (project.dataset), after functions().

    First, the method's own SQL functions (sql_functions). Then one procedure a job (JOBS): its stages' statements in
    order, with the values they read (@name, from nayose.values_of) declared at its top as v_name. `mapping` is the
    deployment's mapping.sql. Every call of the method's functions names the dataset, where the deploy made them.
    """
    fingerprint = bigquery_literal(nayose.fingerprint(mapping_file=mapping))  # what each job after a build checks
    out = sql_functions(dataset, mapping)
    for job, stages in JOBS.items():
        body, declared, written = job_statements(job, stages, dataset, mapping)
        out.append(procedure(job, body=body, declared=declared, written=written, dataset=dataset,
                             fingerprint=fingerprint))
    return out


def sql_functions(dataset: str, mapping: Path | None) -> list[str]:
    """Return each stage file's CREATE TEMP FUNCTION made a function of `dataset`, in the order the jobs meet them."""
    made = {}
    for stage in dict.fromkeys(stage for stages in JOBS.values() for stage, _ in stages):
        for sql in stage_statements(stage, mapping):
            if function := TEMP_FUNCTION.match(sql):
                rest = sql[function.end():]
                made.setdefault(function["name"],
                                f"{function['lead']}CREATE OR REPLACE FUNCTION `{dataset}`.{function['name']}{rest}")
    return [qualified(sql, dataset) for sql in made.values()]


def job_statements(job: str, stages: list, dataset: str, mapping: Path | None) -> tuple[list[str], dict, list[str]]:
    """Return one job's statements for its procedure, the values they read, and the run's tables they write.

    Each statement is as the procedure runs it (in_procedure), or left out where its `-- when:` condition is false
    whatever the run holds. A CREATE TEMP FUNCTION is left out: sql_functions makes it a function of the dataset. The
    tables written are the run's (run_table_written), in the order first written.
    """
    declared, written = {}, {}
    plain = []
    for stage, told in stages:
        declared |= nayose.values_of(stage, **told)
        plain += [sql for sql in stage_statements(stage, mapping) if not TEMP_FUNCTION.match(sql)]
    temp = {t for sql in plain for t in TEMP_TABLE.findall(nayose.NOT_CODE.sub(" ", sql))}
    known = {f"v_{k}": v for k, v in declared.items() if isinstance(v, bool) and k not in ARGUMENTS.get(job, {})}
    body = [x for x in (in_procedure(sql, dataset, temp, known) for sql in plain) if x is not None]
    body, conditions = queried_once(body)
    declared |= {name: False for name in conditions}
    for sql in plain:
        if table := run_table_written(sql):
            written.setdefault(table)
    assert not temp & set(written), f"{job}: tables both temporary and the run's: {temp & set(written)}"
    arguments = ARGUMENTS.get(job, {})
    return body, {k: v for k, v in declared.items() if k not in arguments}, list(written)


def in_procedure(sql: str, dataset: str, temp: set, known: dict | None = None) -> str | None:
    """Return a stage's statement as its procedure runs it, or None where it never runs there.

    Each @name becomes v_name, in the code and in its -- comments, where a `-- when:` condition is read from, but never
    in a string, a quoted name or a /* */ comment, which run_file leaves as written too. Each of the run's tables is
    named with its dataset (in_dataset); the job's temporary tables (`temp`) aren't. A statement with a `-- when:`
    condition is wrapped in IF ... END IF, its condition first given each value the procedure declares as TRUE or
    FALSE (`known`, v_name: value), as folded() does: a condition then always true needs no IF, and a statement whose
    condition is always false is left out. BigQuery runs each other condition as a query of its own, about a second.
    """
    sql = in_dataset(VALUE_OR_NOT_CODE.sub(as_variable, sql), dataset, temp)
    guard = nayose.when(sql)  # a comment, which in_dataset leaves: its tables are named here
    if guard:  # its -- when: line goes: the IF says it, where the deploy hasn't decided it
        lead = re.match(nayose.LEAD, sql, re.S)["lead"]
        sql = re.sub(r"^[ \t]*--\s*when:.*\n", "", lead, count=1, flags=re.M | re.I) + sql[len(lead):]
        guard = folded(guard, known or {})
        if guard is False:
            return None
        if guard is not True:
            return f"IF {in_dataset(f'SELECT {guard}', dataset, temp).removeprefix('SELECT ')} THEN\n{sql};\nEND IF"
    return sql


IF_BLOCK = re.compile(r"IF ([\s\S]*?) THEN\n([\s\S]*);\nEND IF")  # a statement under its condition (in_procedure)


def queried_once(body: list[str]) -> tuple[list[str], list[str]]:
    """Return a procedure's statements with each condition its IFs ask more than once asked once, and the names of the
    variables (condition_1, ...) that hold the answers, which the procedure declares.

    BigQuery runs each IF's condition as a query of its own, about a second. A condition and NOT it are one question.
    It is asked once only where no statement from its first IF to its last (the first's own statement in, the
    last's out, as it runs after its condition) writes a table it reads (writes): the variable then holds what each
    query would have found. Its first IF becomes SET v_condition_n = (condition), and
    each IF reads the variable, or NOT it.
    """
    places: dict[str, list[tuple[int, bool]]] = {}
    for i, sql in enumerate(body):
        if m := IF_BLOCK.fullmatch(sql):
            tree = sqlglot.parse_one(m[1], read="bigquery")
            negated = isinstance(tree, exp.Not)
            places.setdefault((tree.this if negated else tree).sql(dialect="bigquery"), []).append((i, negated))
    names = []
    for condition, at in places.items():
        reads = {t.name for t in sqlglot.parse_one(f"SELECT {condition}", read="bigquery").find_all(exp.Table)}
        if len(at) < 2 or any((w := writes(sql)) is None or w & reads for sql in body[at[0][0]:at[-1][0]]):
            continue
        names.append(f"condition_{len(names) + 1}")
        for k, (i, negated) in enumerate(at):
            ask = f"SET v_{names[-1]} = ({condition});\n" if k == 0 else ""
            body[i] = f"{ask}IF {'NOT ' * negated}v_{names[-1]} THEN\n{IF_BLOCK.fullmatch(body[i])[2]};\nEND IF"
    return body, names


WRITES = (exp.Create, exp.Insert, exp.Delete, exp.Update, exp.Merge, exp.Drop, exp.Alter, exp.TruncateTable)
ASKED = re.compile(r"SET v_\w+ = \(.*\);\n")  # the SET queried_once puts before an IF: a variable written, no table


def writes(sql: str) -> set[str] | None:
    """Return the names of the tables a procedure's statement writes, or None for a statement this can't read (a CALL),
    which may write any. A query, and a SET, write none."""
    sql = sql[m.end():] if (m := ASKED.match(sql)) else sql
    m = IF_BLOCK.fullmatch(sql)
    out = set()
    for tree in sqlglot.parse(m[2] if m else sql, read="bigquery"):
        if tree is None or isinstance(tree, (exp.Semicolon, exp.Query, exp.Set)):  # nothing (a comment after ;), a read
            continue
        if not isinstance(tree, WRITES):
            return None
        out |= {t.name for t in (tree.expressions if isinstance(tree, exp.TruncateTable) else [tree.find(exp.Table)])
                if t is not None}
    return out


def folded(condition: str, known: dict) -> str | bool:
    """Return a condition with each of `known`'s values (v_name: TRUE or FALSE) put in, as far as they decide it.

    True or False where they decide it alone, the rest of the condition where they decide a part (NOT v_lookup AND x
    is x where v_lookup is FALSE), and the condition as written where it names none of them.
    """
    def value(node: exp.Expression) -> exp.Expression:
        return exp.Boolean(this=known[node.name]) if isinstance(node, exp.Column) and not node.table \
            and node.name in known else node
    tree = sqlglot.parse_one(condition, read="bigquery")
    if not any(value(c) is not c for c in tree.find_all(exp.Column)):
        return condition
    tree = simplify(tree.transform(value))
    return tree.this if isinstance(tree, exp.Boolean) else tree.sql(dialect="bigquery")


VALUE_OR_NOT_CODE = re.compile(nayose.NOT_CODE.pattern + r"|@(\w+)", re.S)  # what isn't code, or a value it reads


def as_variable(part: re.Match) -> str:
    """Return a part VALUE_OR_NOT_CODE found as a procedure reads it: @name as v_name, also in a -- comment."""
    if part[1]:
        return f"v_{part[1]}"
    return nayose.PARAMETER.sub(r"v_\1", part[0]) if part[0].startswith("--") else part[0]


def run_table_written(sql: str) -> str | None:
    """Return the run's table a statement writes, or None: a view, a temporary table and KEPT's tables aren't."""
    head = WRITE.match(sql)
    if not head:
        return None
    verb = nayose.verb_of(head)
    return None if "VIEW" in verb or "TEMP" in verb or head["table"] in KEPT else head["table"]


TEMP_TABLE = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?TEMP(?:ORARY)?\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
LIMIT_VALUE = re.compile(r"\bLIMIT v_(\w+)")  # a LIMIT of a value, as in_procedure writes it


def procedure(job: str, body: list[str], declared: dict, written: list[str], dataset: str, fingerprint: str) -> str:
    """Return the CREATE PROCEDURE statement of one job, from its statements (job_statements).

    The procedure declares its values. A build first drops every table it writes, so it starts as an empty run, and
    last stores the method's fingerprint; every other job first refuses a run whose fingerprint differs. Each of the
    run's tables is named with its dataset. strict_mode is off: BigQuery would otherwise refuse, when the deploy makes
    it, a procedure that reads a table no build has made yet; each statement is checked when it runs instead. A LIMIT
    takes its value as a number, as BigQuery takes a literal or a query parameter there, never a variable. So a
    procedure reads:

        CREATE OR REPLACE PROCEDURE `project.dataset`.job(its arguments) OPTIONS (strict_mode = FALSE)
        BEGIN
        DECLARE v_name TYPE DEFAULT value;            each value its stages read
        DROP TABLE IF EXISTS table; ...               a build: each run's table it writes
          or SELECT IF(... UNCHANGED ...);            every other job: the fingerprint checked
        the stages' statements, each as in_procedure gives it;
        CREATE OR REPLACE TABLE method AS ...;        a build: the fingerprint stored (METHOD)
        END
    """
    arguments = ", ".join(f"v_{k} {kind}" for k, kind in ARGUMENTS.get(job, {}).items())
    head = [f"DECLARE v_{k} {bigquery_type(v)} DEFAULT {bigquery_literal(v)}" for k, v in declared.items()]
    if job == "build":
        head += [f"DROP TABLE IF EXISTS `{dataset}`.{x}" for x in written]
        body = [*body, in_dataset(nayose.METHOD.replace("@fingerprint", fingerprint), dataset)]
    else:
        head.append(in_dataset(nayose.UNCHANGED.replace("@fingerprint", fingerprint), dataset))
    body = [LIMIT_VALUE.sub(lambda m: f"LIMIT {int(declared[m[1]])}", qualified(sql, dataset)) for sql in body]
    statements = ";\n".join([*head, *body])
    return (f"CREATE OR REPLACE PROCEDURE `{dataset}`.{job}({arguments}) OPTIONS (strict_mode = FALSE)\n"
            f"BEGIN\n{statements};\nEND")

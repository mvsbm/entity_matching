"""The design is the contract: docs/diagrams/*.puml, the HLD and LLD that docs/architecture.md shows, checked against the
code. Each check fails with exactly what to draw or to remove.

    modules     the components diagram's edges are the imports between er/ and scripts/ (ast)
    names       every path and every function a diagram or a doc names exists
    calls       each step box names the functions its step reaches in the run layer (er/run.py, folder.py, report.py), and
                those of other modules they call (ast)
    tables      each step's DuckDB tables, made and used, as a test run's query log says (DuckDB's QueryLog, parsed by sqlglot)
    files       the data diagram's files and columns are those a test run leaves in its folder
    rendered    each SVG holds its .puml's source: rendered after the last edit

Render after an edit: plantuml -tsvg docs/diagrams/*.puml
"""
import ast
import importlib
import re
import string
import zlib
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "docs" / "diagrams"
PLUMBING = {"candidates.q", "source.lit", "Run._count", "Run._done", "Run.columns", "Run._resolved", "Run._singletons"}  # SQL quoting, counting
TRANSIENT = {"pending.json", "jobs.jsonl"}  # in a run folder only while a write is cut short; the scheduler's ledger
EXTENSIONS = {"py", "toml", "md", "parquet", "json", "jsonl", "txt", "npz", "svg", "puml", "lock", "tmp", "ipynb", "pdf"}


# ---------- reading the diagrams ----------

def parse(name: str) -> tuple[dict[str, tuple[str, str]], list[tuple[str, str]], dict[str, list[str]]]:
    """A diagram's elements (id → kind, label), its edges (from, to) and its entities' fields: the subset of PlantUML the
    diagrams use. C4: Person|System|Container|Component…(id, "label", …), its label all its texts, and Rel…(a, b, …).
    UML: <kind> "label" as id, a --> b, entity "label" as id { one field per line }, and package "label" as id { … }:
    an edge to a package is an edge to each step (rectangle) in it."""
    text = (DIAGRAMS / f"{name}.puml").read_text(encoding="utf-8")
    elements, edges, fields, members, open_ = {}, [], {}, defaultdict(list), []
    for kind, eid, rest in re.findall(r'^\s*((?:Person|System|Container|Component)\w*)\(\s*(\w+)\s*,(.*)\)\s*$', text, re.M):
        elements[eid] = (kind, " · ".join(re.findall(r'"([^"]*)"', rest)).replace("\\n", " · "))
    for kind, label, eid in re.findall(r'^\s*(rectangle|database|file|folder|actor|entity|card|collections)\s+"([^"]*)"\s+as\s+(\w+)', text, re.M):
        elements[eid] = (kind, label)
    edges += re.findall(r'^\s*Rel\w*\(\s*(\w+)\s*,\s*(\w+)', text, re.M)
    edges += re.findall(r'^\s*(\w+)\s+[-.]+(?:\[[^\]]*\])?[-.]*>\s+(\w+)', text, re.M)
    for eid, body in re.findall(r'^\s*entity\s+"[^"]*"\s+as\s+(\w+)\s*\{(.*?)^\s*\}', text, re.M | re.S):
        fields[eid] = [line.strip() for line in body.splitlines() if line.strip() and not line.strip().startswith(("--", ".."))]
    for line in text.splitlines():  # which steps each package holds
        if (m := re.match(r'^\s*package\s+"[^"]*"\s+as\s+(\w+)\s*\{', line)):
            open_.append(m.group(1))
        elif re.match(r"^\s*package\b.*\{", line):
            open_.append(None)
        elif re.match(r"^\s*\}", line) and open_:
            open_.pop()
        elif (m := re.match(r'^\s*rectangle\s+"[^"]*"\s+as\s+(\w+)', line)):
            for g in filter(None, open_):
                members[g].append(m.group(1))
    edges = [(x, y) for a, b in edges for x in members.get(a, [a]) for y in members.get(b, [b])]
    return elements, edges, fields


MODULES = {f.stem for f in (ROOT / "er").glob("*.py")} - {"__init__"}
RANK = {"tools_run": 4, "tools_design": 4, "design": 3, "run": 2, "steps": 1, "configuration": 0}  # components.puml: each layer imports only those below
CLASSES = {"Run": "er.run", "Classifier": "er.kind", "NameModel": "er.kind", "Fitted": "er.kind"}
RUN_LAYER = ("run", "folder", "report")  # the run's modules: a step box names what it reaches in them


def names_in(label: str) -> set[str]:
    """The functions a label names: module.function (a module of er/, er. left off), Run.method, Classifier.method,
    NameModel.method; file names (run.py) aside."""
    found = re.findall(r"(?<![\w./])(?:er\.)?((?:[A-Z]\w*|[a-z_]+)\.[A-Za-z_]\w*)", label.replace("\\n", " "))
    return {n for n in found if n.split(".")[0] in MODULES | set(CLASSES) and n.split(".")[1] not in EXTENSIONS}


def resolve_name(name: str) -> bool:
    head, attr = name.split(".", 1)
    if head in CLASSES:  # a method or field, or an attribute each instance sets (self.x = …)
        cls = getattr(importlib.import_module(CLASSES[head]), head)
        source = (ROOT / CLASSES[head].replace(".", "/")).with_suffix(".py").read_text(encoding="utf-8")
        return hasattr(cls, attr) or attr in getattr(cls, "__dataclass_fields__", {}) or f"self.{attr}" in source
    return hasattr(importlib.import_module(f"er.{head}"), attr)


# ---------- what the code does ----------

def imports() -> set[tuple[str, str]]:
    """Every import of an er module by a file of er/ or scripts/, as repo-relative paths. Imports for type checking only
    are left out: they make no dependency at run time."""
    out = set()
    for f in [*sorted((ROOT / "er").glob("*.py")), *sorted((ROOT / "scripts").glob("*.py"))]:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        typing_only = {id(n) for node in ast.walk(tree) if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)
                       for n in ast.walk(node)}
        for node in ast.walk(tree):
            if id(node) in typing_only:
                continue
            mods = ([node.module] if isinstance(node, ast.ImportFrom) and node.module else
                    [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            for m in mods:
                if m.startswith("er.") and f.name != "__init__.py":
                    out.add((str(f.relative_to(ROOT)), f"er/{m.split('.')[1]}.py"))
    return out


class RunCode:
    """The run layer (er/run.py, er/folder.py, er/report.py) read with ast: which functions a step reaches. A step's
    reach follows Run's methods (other steps aside) and the run layer's functions, named module.function; it stops at a
    function of another er module, named module.function too."""

    def __init__(self):
        self.local, self.names = {}, {}  # module.function → its ast; per module, each name it sees → module.function
        for m in RUN_LAYER:
            tree = ast.parse((ROOT / "er" / f"{m}.py").read_text(encoding="utf-8"))
            names = self.names[m] = {}
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("er."):
                    mod = importlib.import_module(node.module)
                    for a in node.names:
                        if callable(getattr(mod, a.name)) and not isinstance(getattr(mod, a.name), type):  # functions, not classes
                            names[a.asname or a.name] = f"{node.module.split('.')[1]}.{a.name}"
                elif isinstance(node, ast.ImportFrom) and node.module == "er":  # from er import folder: folder.stage
                    names.update({a.asname or a.name: a.name for a in node.names})
                elif isinstance(node, ast.FunctionDef):
                    self.local[f"{m}.{node.name}"] = node
                    names[node.name] = f"{m}.{node.name}"
                elif isinstance(node, ast.ClassDef) and node.name == "Run":
                    self.methods = {n.name: n for n in node.body if isinstance(n, ast.FunctionDef)}

    def body(self, name: str) -> ast.FunctionDef:
        return self.methods[name.split(".")[1]] if name.startswith("Run.") else self.local[name]

    def reach(self, roots: set[str], steps: set[str] = frozenset()) -> set[str]:
        seen, todo = set(), list(roots)
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            if name in PLUMBING:
                continue
            names = self.names["run" if name.startswith("Run.") else name.split(".")[0]]
            for node in (n for stmt in self.body(name).body for n in ast.walk(stmt)):  # decorators aside
                found = None
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr in self.methods:
                    found = None if node.attr in steps else f"Run.{node.attr}"
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and names.get(node.value.id) in RUN_LAYER:
                    found = f"{names[node.value.id]}.{node.attr}"  # called by its module's name: a function, not a constant
                    found = found if found in self.local else None
                elif isinstance(node, ast.Name) and node.id in names and "." in names[node.id]:
                    found = names[node.id]
                if found in self.local or (found or "").startswith("Run."):
                    if found not in seen:
                        todo.append(found)
                elif found:
                    seen.add(found)
        return seen - PLUMBING

    def steps_of_full(self) -> dict[str, set[str]]:
        """Run.full's steps in order: each step method it calls, with the helpers it calls just before (in that step)."""
        out, pending = {}, set()
        for node in ast.walk(self.methods["full"]):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr in self.methods:
                pending.add(f"Run.{node.attr}")
                if not node.attr.startswith("_"):
                    out[node.attr], pending = pending, set()
        return out


# ---------- what a run does: its query log ----------

def lineage(statements: list[str]) -> tuple[set[str], set[str]]:
    """The tables a list of SQL statements creates or fills, and those they read (CTEs and table functions aside)."""
    made, read = set(), set()
    for sql in statements:
        try:
            tree = sqlglot.parse_one(sql, read="duckdb")
        except sqlglot.errors.ParseError:  # what sqlglot can't read: its CREATE, FROM and JOIN by pattern
            made |= set(re.findall(r'CREATE (?:OR REPLACE )?(?:TEMP |TEMPORARY )?(?:TABLE|VIEW) (?:IF NOT EXISTS )?"?(\w+)', sql))
            read |= set(re.findall(r'(?:FROM|JOIN)\s+"?([A-Za-z_]\w*)', sql)) - set(re.findall(r'(\w+) AS \(', sql))
            continue
        if tree is None:
            continue
        ctes = {c.alias for c in tree.find_all(exp.CTE)}
        target = tree.this if isinstance(tree, (exp.Create, exp.Insert)) else None
        target = target.this if isinstance(target, exp.Schema) else target
        own = {target.name} if isinstance(target, exp.Table) else set()
        made |= own
        read |= {t.name for t in tree.find_all(exp.Table) if t.name and t.name not in ctes} - own
    keep = lambda names: {n for n in names if not n.startswith("__splink") and n not in {"duckdb_logs"}}
    return keep(made), keep(read)


class Logged:
    """A Run whose every query is logged, and given to the step that finishes after it (Run.echo)."""

    def __init__(self, run):
        self.run, self.by_step = run, defaultdict(list)
        run.con.execute("CALL enable_logging('QueryLog')")
        run.echo = lambda step: self.cut(step["step"])

    def cut(self, step: str) -> None:
        rows = self.run.con.execute("SELECT message FROM duckdb_logs WHERE type = 'QueryLog'").fetchall()
        self.run.con.execute("CALL truncate_duckdb_logs()")
        self.by_step[step] += [m for m, in rows if "duckdb_logs" not in m]


def drawn_tables(steps: dict[str, list[str]]) -> tuple[set[tuple[str, str]], set[str]]:
    """The edges a diagram must draw: step → table it makes, table → step that uses it without making it, for every
    table made in one step and used in another. A table one step makes and uses alone is its scratch."""
    made, read = {}, {}
    for step, statements in steps.items():
        made[step], read[step] = lineage(statements)
    shared = {t for s in made for t in made[s] if any(t in read[o] and t not in made[o] for o in read if o != s)}
    edges = {(s, t) for s in made for t in made[s] & shared} | {(t, s) for s in read for t in (read[s] - made[s]) & shared}
    return edges, shared


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    return logged_runs(tmp_path_factory.mktemp("design"))


def logged_runs(tmp: Path) -> tuple:
    """The population of tests/test_er.py through a full run and its report, an increment and its report, and a set of
    decisions, each with its query log."""
    from er.config import load_pipeline
    from er.generate import generate, load_reference, load_spec
    from er.run import Run
    from er.settings import load_settings
    s = load_settings()  # the population of tests/test_er.py
    p = load_pipeline(s.root / "config" / "final.toml", s.standardize, s.chains, s.columns)
    g = generate(replace(load_spec(s.root / "config" / "generator.toml")[0], entities=400), *load_reference(s.paths["reference"]))
    batch = np.random.default_rng(0).random(len(g.df)) < 0.2
    g.df[~batch].to_parquet(tmp / "first.parquet", index=False)
    pd.concat([g.df[batch], g.df[~batch].head(1)]).to_parquet(tmp / "new.parquet", index=False)  # one already in the run: set aside
    pd.DataFrame({s.data.unique_id: g.df[~batch][s.data.unique_id].astype("string")[:3], "kind": [1] * 3}).to_parquet(tmp / "answers.parquet")
    out, pipeline, logs = tmp / "run", s.root / "config" / "final.toml", {}
    for mode in ("full", "increment"):
        run = Run(p, s, kind_labels=tmp / "answers.parquet" if mode == "full" else None)
        logs[mode] = Logged(run)
        run.full(tmp / "first.parquet", out, pipeline_file=pipeline) if mode == "full" else run.increment(tmp / "new.parquet", out, pipeline_file=pipeline)
    sheet = pd.read_parquet(out / "review.parquet")
    sheet.iloc[:1].assign(decision="match").to_parquet(tmp / "decided.parquet")
    run = Run(p, s)
    logs["decisions"] = Logged(run)
    run.decide(tmp / "decided.parquet", out)
    return s, out, {mode: dict(log.by_step) for mode, log in logs.items()}


# ---------- the checks ----------

def layers() -> dict[str, str]:
    """Each module's box in components.puml: its layer."""
    elements, _, _ = parse("components")
    layer = {}
    for eid, (_, label) in elements.items():
        for f in re.findall(r"\b(?:er|scripts)/\w+\.py", label):
            assert f not in layer, f"{f} is in two boxes of components.puml: {layer[f]}, {eid}"
            layer[f] = eid
    return layer


def test_the_components_diagram_holds_every_module_once_and_draws_the_imports_between_its_layers():
    _, edges, _ = parse("components")
    layer = layers()
    files = {f"er/{m}.py" for m in MODULES} | {str(f.relative_to(ROOT)) for f in (ROOT / "scripts").glob("*.py")}
    assert files == set(layer), f"components.puml: modules to place {sorted(files - set(layer))}, to remove {sorted(set(layer) - files)}"
    code = {(layer[a], layer[b]) for a, b in imports() if layer[a] != layer[b]}
    drawn = {(a, b) for a, b in edges if a in layer.values() and b in layer.values()}
    assert not code - drawn, f"components.puml: imports between these boxes to draw {sorted(code - drawn)}"
    assert not drawn - code, f"components.puml: arrows no import makes {sorted(drawn - code)}"
    against = sorted((a, b) for a, b in imports() if layer[a] != layer[b] and RANK[layer[a]] <= RANK[layer[b]])
    assert not against, f"imports against the layers (each layer imports only those below it): {against}"


def test_every_path_and_function_a_diagram_or_a_doc_names_exists():
    texts = {f.relative_to(ROOT): f.read_text(encoding="utf-8") for f in [*DIAGRAMS.glob("*.puml"), *(ROOT / "docs").rglob("*.md"), ROOT / "README.md", ROOT / "CONTRIBUTING.md"]}
    missing_paths, missing_names = set(), set()
    for f, text in texts.items():
        text = re.sub(r"</?(?:b|i|u|size|color|font)(?::[^>]*)?>", "", text)  # PlantUML's formatting, not part of a path
        for p in re.findall(r"\b((?:er|scripts|config|docs|reports|notebooks|tests|data/reference)/[\w./*<>-]*\w)", text):
            pattern = re.sub(r"<[^>]+>|part-n", "*", p)
            if not list(ROOT.glob(pattern)) and not (ROOT / pattern).exists():
                missing_paths.add(f"{f}: {p}")
        labels = [label for _, label in parse(f.stem)[0].values()] if f.suffix == ".puml" else re.findall(r"`([^`]+)`", text)
        for label in labels:
            for n in names_in(label):
                if not resolve_name(n):
                    missing_names.add(f"{f}: {n}")
    assert not missing_paths, f"paths that don't exist: {sorted(missing_paths)}"
    assert not missing_names, f"functions that don't exist: {sorted(missing_names)}"


def test_each_step_box_names_the_functions_its_step_reaches():
    code = RunCode()
    elements, _, _ = parse("full-run")
    steps = code.steps_of_full() | {"report": {"Run.report"}}
    wrong = {}
    for step, roots in steps.items():
        named = names_in(elements[step][1])
        expected = code.reach(roots, steps=set(steps) - {r.split(".")[1] for r in roots})
        if named != expected:
            wrong[step] = dict(to_draw=sorted(expected - named), to_remove=sorted(named - expected))
    assert not wrong, f"full-run.puml: {wrong}"
    for diagram, method in (("increment", "increment"), ("decisions", "decide")):
        elements, _, _ = parse(diagram)
        named = set().union(*(names_in(label) for eid, (kind, label) in elements.items() if kind == "rectangle" and eid != "report"))
        expected = code.reach({f"Run.{method}"}, steps={"report"})  # the report: its own box, as in the full run's
        assert named == expected, f"{diagram}.puml: to draw {sorted(expected - named)}, to remove {sorted(named - expected)}"


@pytest.mark.parametrize("mode, diagram", [("full", "full-run"), ("increment", "increment"), ("decisions", "decisions")])
def test_each_step_s_tables_are_those_its_queries_make_and_use(runs, mode, diagram):
    _, _, logs = runs
    expected, shared = drawn_tables(logs[mode])
    elements, edges, _ = parse(diagram)
    table = {eid: label for eid, (kind, label) in elements.items() if kind == "database"}
    steps = {eid for eid, (kind, _) in elements.items() if kind == "rectangle"}
    drawn = {(a if a in steps else table[a], b if b in steps else table[b]) for a, b in edges
             if (a in steps and b in table) or (a in table and b in steps)}
    assert not expected - drawn, f"{diagram}.puml: table edges to draw {sorted(expected - drawn)}"
    assert not drawn - expected, f"{diagram}.puml: table edges no query makes {sorted(drawn - expected)}"


def test_the_data_diagram_holds_the_run_folder_s_files_and_columns(runs):
    s, out, _ = runs
    uid = s.data.unique_id
    elements, _, fields = parse("data")
    norm = lambda p: re.sub(r"part-\d+", "part-n", str(p.relative_to(out)))
    on_disk = {norm(f) for f in out.rglob("*") if f.is_file() and f.name != ".lock"}
    drawn = {label for kind, label in elements.values() if kind == "entity"} - TRANSIENT
    assert on_disk == drawn, f"data.puml: files to draw {sorted(on_disk - drawn)}, to remove {sorted(drawn - on_disk)}"
    for eid, cols in fields.items():
        label = elements[eid][1]
        if not label.endswith(".parquet"):
            continue
        actual = set(pd.read_parquet(next(f for f in out.rglob("*.parquet") if norm(f) == label)).columns)
        listed = {c.split(":")[0].strip().lstrip("*").strip().replace("<id>", uid) for c in cols}
        fixed = {c for c in listed if "<" not in c and c != "…"}
        assert fixed <= actual, f"data.puml {label}: columns not in the file {sorted(fixed - actual)}"
        if "…" not in listed and not any("<" in c for c in listed):
            assert actual == fixed, f"data.puml {label}: columns to draw {sorted(actual - fixed)}"


def plantuml_source(svg: str) -> str:
    """The source PlantUML stores in an SVG it renders: deflated, then base64 in its own alphabet."""
    code = re.search(r"<\?plantuml-src (\S+)\?>", svg).group(1)
    alphabet = string.digits + string.ascii_uppercase + string.ascii_lowercase + "-_"
    bits = "".join(f"{alphabet.index(c):06b}" for c in code)
    data = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits) - len(bits) % 8, 8))
    return zlib.decompressobj(-15).decompress(data).decode("utf-8")


@pytest.mark.parametrize("puml", sorted(DIAGRAMS.glob("*.puml")), ids=lambda p: p.stem)
def test_each_svg_is_rendered_from_its_puml(puml):
    svg = puml.with_suffix(".svg")
    assert svg.exists(), f"render it: plantuml -tsvg {puml.relative_to(ROOT)}"
    lines = lambda text: [x.rstrip() for x in text.strip().splitlines() if x.strip() and not x.startswith(("@startuml", "@enduml"))]  # stored without them
    assert lines(plantuml_source(svg.read_text(encoding="utf-8"))) == lines(puml.read_text(encoding="utf-8")), \
        f"{svg.name} is older than its source: plantuml -tsvg {puml.relative_to(ROOT)}"


def test_the_commands_reference_is_the_declarations():
    from er.cli import reference
    assert (ROOT / "docs" / "commands.md").read_text(encoding="utf-8") == reference() + "\n", \
        "docs/commands.md differs from er/cli.py's declarations: .venv/bin/python scripts/document_commands.py"


# ---------- the engineering rules (CONTRIBUTING.md) that code can check ----------

def calls(tree: ast.AST) -> list[tuple[str, int]]:  # every call, by its dotted name: print, sys.exit, contextlib.redirect_stderr
    def name(f: ast.expr) -> str:
        return f.id if isinstance(f, ast.Name) else f"{name(f.value)}.{f.attr}" if isinstance(f, ast.Attribute) else ""
    return [(name(n.func), n.lineno) for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_code_nayose_runs_never_prints_or_exits():
    """Rule 1, errors are values: the command line (er/cli.py) owns the terminal; the code its commands run raises
    InputError or returns, since nayose open ui runs it in threads of a long-lived server."""
    runs = {f for f, box in layers().items() if f.startswith("er/") and box in ("tools_run", "run", "steps", "configuration")} - {"er/cli.py"}
    found = []
    for f in sorted(runs):
        tree = ast.parse((ROOT / f).read_text(encoding="utf-8"))
        found += [f"{f}:{line} {c}" for c, line in calls(tree) if c in ("print", "exit", "quit", "sys.exit", "os._exit")]
        found += [f"{f}:{n.lineno} raise SystemExit" for n in ast.walk(tree) if isinstance(n, ast.Raise) and "SystemExit" in ast.unparse(n)]
    assert not found, f"print or exit outside er/cli.py: {found}"


def test_no_code_in_er_changes_process_wide_state():
    """Rule 2: the server runs commands in threads, which share the process's streams, working folder and environment."""
    banned_calls = ("redirect_stdout", "redirect_stderr", "os.chdir", "os.putenv", "os.environ.update", "os.environ.pop",
                    "os.environ.setdefault", "os.environ.clear", "sys.path.insert", "sys.path.append")
    found = []
    for f in sorted((ROOT / "er").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        found += [f"{f.name}:{line} {c}" for c, line in calls(tree) if c.split(".")[-1] in banned_calls or c in banned_calls]
        for n in ast.walk(tree):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AugAssign) else []
            found += [f"{f.name}:{n.lineno} {ast.unparse(t)} =" for t in targets
                      if ast.unparse(t).split("[")[0] in ("sys.stdout", "sys.stderr", "sys.stdin", "sys.argv", "sys.path", "os.environ")]
    assert not found, f"process-wide state changed in er/: {found}"


def test_a_store_that_grows_says_what_bounds_it():
    """Rule 3: a module-level dict, list or set that code adds to names its bound on the line that makes it
    (bounded: …), or the limit it doesn't have (shortcut: …)."""
    found = []
    for f in sorted((ROOT / "er").glob("*.py")):
        text = f.read_text(encoding="utf-8")
        tree, lines = ast.parse(text), text.splitlines()
        stores = {}
        for n in tree.body:
            target, value = (n.targets[0], n.value) if isinstance(n, ast.Assign) else (n.target, n.value) if isinstance(n, ast.AnnAssign) else (None, None)
            if isinstance(target, ast.Name) and (isinstance(value, ast.Dict | ast.List | ast.Set) or
                                                 (isinstance(value, ast.Call) and ast.unparse(value.func) in ("dict", "list", "set", "defaultdict", "threading.local"))):
                stores[target.id] = n.lineno
        grown = {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store) and isinstance(n.value, ast.Name)}
        grown |= {c.split(".")[0] for c, _ in calls(tree) if c.split(".")[-1] in ("append", "add", "update", "setdefault", "extend", "insert")}
        for name, line in stores.items():
            said = " ".join(lines[line - 1:line + 2])
            if name in grown and "bounded:" not in said and "shortcut:" not in said:
                found.append(f"{f.name}:{line} {name}")
    assert not found, f"stores that grow without saying what bounds them: {found}"


def test_the_page_reaches_the_network_through_one_call_that_never_throws():
    """Rule 5: every request the page makes goes through api(), which turns a lost server into a value."""
    html = (ROOT / "er" / "ui.html").read_text(encoding="utf-8")
    api = re.search(r"async function api\(.*?\n}\n", html, re.S)
    assert html.count("fetch(") == 1 and api and "fetch(" in api.group(0) and "try {" in api.group(0) and "catch" in api.group(0)

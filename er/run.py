"""The run on any file of records, without labels: a chosen pipeline (config/final.toml) end to end on DuckDB tables,
so memory stays bounded at any size (past config/settings.toml [compute] memory_limit, DuckDB spills to disk). Each
step is a method of Run, called in order by full(), or one at a time by the demo notebook. Each records its Big-O,
with the numbers filled in, and its time.

    load        O(N·L)                           read through er.source (Parquet), check the fields, set aside what can't be
                                                 resolved, standardize each chunk, each record's kind (er.kind) → table records
    budget      O(N)                             exact block sizes per rule and generator, before any join; blocks of
                                                 64+ records flagged (a rule doesn't trust them; candidates sample them)
    fit         O(n + S·K + P_em·K) + O(N + S·K) λ and m by EM on a fixed-size sample of n records (or a fitted model),
                                                 then u on this file
    rules       O(N + Σ P_r·L²) + O(E·d + N)     one join per rule (the first rule wins), then the rules' cascade
    candidates  O(N·L + Σ P_g)                   every generator; pairs inside one rule cluster dropped; a flagged block
                                                 joined only if a sample of its pairs, scored as the run scores, reaches
                                                 the review floor
    score       O(C·K·L²)                        every candidate scored
    cluster     O(C + E·d + N)                   accept at the threshold, then cluster with the rules' pairs
    write       O(N + C)                         gold clusters and matches, as Parquet; the state for increments; and,
                                                 built first, the report
    report      O(review pairs) + O(N) in SQL    for people: qa.md, report.txt, review.parquet, kind_review.parquet

increment() adds a batch Δ of new records to a written run: the batch is joined against all records, rule by rule and
generator by generator, scored, and merged into the existing clusters, each cluster one node. Its cost is
O(|Δ|·(L + Σ b) + C_Δ·K·L²) plus narrow O(N) scans (the stored key columns, the exact u counts, gold rewritten),
whatever N; b is a block's size, C_Δ the pairs touching the batch. It keeps the stored model, and samples u again
only for a comparison whose drift has outgrown its sampling error (er.match.refreshed_u). A full run re-fits and
re-scores everything.

decide() applies people's decisions on the review sheet (qa) without scoring anything: a `match` pair merges two
clusters. Decisions are kept in decisions/, which a full run on the same folder applies again; people's person/company
answers in kind_answers/, a part per sheet as given, which every later run on the folder reads.

Writes are staged: every file is written under a temporary name; once all are complete, the list of moves still owed is
saved (pending.json), then they are done. A run's reports are among its files, and steps.json replaces itself whole. A write interrupted before that list exists left the run as it was: run it
again. One interrupted after it is finished by the next run, increment or set of decisions (finish_writes). A full run
refuses a folder that already holds a run unless told to overwrite it, and then replaces the old run only once the new
one is complete. A run folder takes one writer at a time (run_lock): a full run, an increment or a set of decisions holds
it for as long as it writes.

N records, L characters per value, P pairs in a rule's or generator's key blocks, C candidates, K comparisons,
S sampled pairs for u, E accepted pairs, d cluster diameter (Splink's connected components take up to d rounds, over
the edges' records only: each existing cluster is one node, see er.cluster.merge).
"""
import fcntl
import functools
import hashlib
import json
import math
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from er.candidates import candidates, estimate, q
from er.config import FSSpec, InputError, Key, KeyBlocker, Pipeline, sources_text
from er.io import config_hash, markdown
from er.cluster import merge
from er.kind import COMPANY, NAME_MODEL, PERSON, SAYS, UNSURE, classifier as kind_classifier, kind_review_sheet, merge_answers
from er.match import (counted, ELSE, levels, parameters, pattern_coverage, refreshed_u, rule_edges, scaled_prior,
                      score_fs, scored_u, train_fs, u_basis)
from er.settings import SPECIAL, Settings, fit_to_file, present_fields
from er.source import lit, open_source, suggest
from er.standardize import prepare
from er.strings import connect


def peak_gb() -> float:  # the process's peak resident memory so far (ru_maxrss: bytes on macOS, KB on Linux)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)


BYTES_PER_PAIR = 350  # shortcut: measured at 1M (candidate and score tables held together); measure again if those tables change
PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
RUN_FILES = ("gold.parquet", "steps.json", PENDING, "matches", "rule_kept", "state", "set_aside",  # what a run writes in its folder
             "qa.md", "report.txt", "review.parquet", "kind_review.parquet")
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them
KIND_ANSWERS = "kind_answers"  # people's person/company answers, a part per sheet as given: kept as decisions are
FULL_TMP = ".full.tmp"  # a full run's new files, until they replace the old run's


class Busy(InputError):
    """Another job is writing to the run folder: no mistake, so scripts/resolve.py exits 75, to be tried again."""


@contextmanager
def run_lock(out: Path):
    """One writer per run folder: an OS lock on <out>/.lock for as long as a run, an increment or a set of decisions
    writes there. The system releases it when the process ends, even if it dies, so it never goes stale.
    shortcut: flock holds on a local disk, not on network or object storage; there, run one job per folder at a time."""
    out.mkdir(parents=True, exist_ok=True)
    with open(out / ".lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(f"another job is writing to {out}", fix="wait for it to finish: a run folder takes one writer at a time") from None
        yield


def locked(method: Callable) -> Callable:  # the run folder (the method's `out`) locked for the whole method
    @functools.wraps(method)
    def wrapper(self: "Run", path: str | Path, out: Path, *args: object, **kwargs: object) -> object:
        with run_lock(Path(out)):
            return method(self, path, Path(out), *args, **kwargs)
    return wrapper


def code_version(root: Path) -> str:
    """The commit of the code that ran, and the tracked files changed in this copy (the column mapping, say)."""
    def git(*args: str) -> str:
        try:
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10).stdout.strip()
        except OSError:
            return ""
    changed = git("diff", "--name-only", "HEAD").splitlines()
    return (git("rev-parse", "--short", "HEAD") or "unknown (not a git checkout)") + (f" · changed here: {', '.join(changed)}" if changed else "")


def size_bytes(text: str) -> int:  # one of DuckDB's sizes: "8.0 GiB", "512.0 MiB", "1.5 GB"
    num, unit = re.match(r"([\d.]+)\s*([A-Za-z]*)", text).groups()
    scale = {"": 1, "b": 1, "bytes": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40}
    return int(float(num) * scale[unit.lower()])


def finish_writes(out: Path) -> None:
    """Complete the moves of a write that was interrupted after its new files were complete; nothing otherwise. Each
    move [new, dest] replaces dest, a file or a folder, if new is still there; [None, dest] deletes dest. So done
    twice, they do the same as done once."""
    pending = out / PENDING
    if pending.exists():
        for new, dest in json.loads(pending.read_text(encoding="utf-8")):
            if new is None or os.path.exists(new):
                if os.path.isdir(dest):
                    shutil.rmtree(dest)
                elif os.path.exists(dest) and new is None:
                    os.unlink(dest)
                if new is not None:
                    os.replace(new, dest)
        shutil.rmtree(out / FULL_TMP, ignore_errors=True)
        pending.unlink()


@dataclass
class Run:
    pipeline: Pipeline                        # the chosen pipeline; fitted to the file by load()
    settings: Settings
    model: dict | None = None                 # a fitted model (Splink JSON from train_fs); None: fit on this file
    chunk_rows: int = 200_000
    steps: list[dict] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    echo: Callable[[dict], None] | None = None  # called with each step as it finishes: progress for people (scripts/resolve.py)
    kind_labels: Path | None = None           # people's person/company labels (a filled-in kind_review.parquet); an increment keeps the run's

    def __post_init__(self) -> None:
        self.con, self.db = connect(self.settings.compute)
        self.uid = self.settings.data.unique_id
        self.l, self.r = f"{self.uid}_l", f"{self.uid}_r"
        self.notes: list[str] = []            # what the loader detected or fixed, for the run's summary; never a record's value
        self.examples: list[str] = []         # notes that quote a record's value: the summary and qa.md show them, report.txt doesn't
        self.added: int | None = None         # an increment's new records (0: nothing new)
        self.gated = pd.DataFrame()           # the oversized blocks the candidates checked, and what was decided
        self.present: dict = {}               # each field the file holds, and the source columns it is built from
        self.scoring: dict | None = None      # the model with u from this file (fit): what the gate and the scores use
        self.basis: dict = {}                 # what an increment needs to tell whether those u went stale (er.match.u_basis)
        self.classifier = None                # each record's kind, person or company (er.kind); None: the pipeline doesn't ask
        self.labels: pd.DataFrame | None = None  # the person/company answers it rests on: the folder's sheets and the one given
        self.given: pd.DataFrame | None = None   # the filled rows of the sheet given (kind_labels), as given
        self.tables: dict[str, pd.DataFrame] = {}  # qa's tables, the summary first, once report() built them
        self.fields = [f for f in self.settings.columns if f not in SPECIAL]  # the logical fields of [columns]
        self.inputs: list[dict] = []          # the files read: path, bytes, SHA-256 (steps.json)
        # what decides the answer: the pipeline as given and the settings that shape the records; an increment needs the full run's
        self.config = config_hash((self.pipeline, self.settings.columns, self.settings.standardize, self.settings.flag_company))
        if {self.pipeline.rules.resolver.method, self.pipeline.fs.resolver.method} != {"connected_components"}:
            raise InputError("the run clusters by connected components only; the pipeline asks for "
                             f"{self.pipeline.rules.resolver.method} (rules) and {self.pipeline.fs.resolver.method} (model)",
                             fix='set resolver = { method = "connected_components" } in both stages of the pipeline')

    def _done(self, name: str, big_o: str, filled: str, t: float, **facts: object) -> None:
        self.steps.append(dict(step=name, big_o=big_o, filled=filled, seconds=round(time.perf_counter() - t, 2),
                               peak_memory_gb=round(peak_gb(), 2), **facts))
        if self.echo:
            self.echo(self.steps[-1])

    def _count(self, sql: str) -> int:
        return self.con.execute(f"SELECT count(*) FROM {sql}").fetchall()[0][0]

    # ---------- the steps ----------

    def load(self, path: str | Path, into: str = "records", stored: str | None = None) -> None:
        """Read the file through er.source (Parquet; columns matched to config/settings.toml [columns]); check its fields
        against config/pipeline.toml [fields]; set aside what can't be resolved (_set_aside); standardize each chunk with
        er.standardize.prepare (each record on its own, so chunking changes nothing) into the table `into`."""
        t = time.perf_counter()
        src = open_source(path, self.con, {c for f, alts in self.settings.columns.items() if f != "entity" for alt in alts for c in alt})
        self.notes, self.inputs = list(src.notes), file_facts(src.files)
        present = self.present = present_fields(self.settings, src.columns)
        hints = suggest(src, self.con, [f for f in self.settings.columns if f not in present and f != "entity"], self.settings.detect)
        try:
            self.pipeline, self.disabled = fit_to_file(self.pipeline, self.settings, src.columns)
        except InputError as e:
            raise InputError(f"{e}. The file's columns: {', '.join(src.columns)}", e.fix + (
                ". Suggested from the file's values, check them first:\n  [columns]" + "".join(
                    f"\n  {f} = \"{c}\"   # {why}" for f, (c, _, why) in hints.items()) if hints else "")) from None
        self.notes += [f"no column for {f}; {c} may be it ({why})" for f, (c, share, why) in hints.items() if share > 0.5]
        if self.model is not None:  # a given model must compare exactly what this file's fields let the pipeline compare
            fitted = {(c["output_column_name"], lv["label_for_charts"]) for c in self.model["comparisons"]
                      for lv in c["comparison_levels"] if not lv.get("is_null_level")}
            here = {(c.name, label) for c in self.pipeline.fs.model.comparisons for label in (*(lv.label for lv in c.levels), ELSE)}
            if fitted != here:
                raise InputError(f"{path}: the model was fitted on other comparison levels (only in the model: {sorted(fitted - here)}; "
                                 f"only here: {sorted(here - fitted)})", fix="run without --model: the run then fits its model on this file")
        rows = self._set_aside(src.sql, stored)
        self.con.execute(f"DROP TABLE IF EXISTS {into}")
        self.n = 0
        if not self._count(rows):
            if stored is None:
                raise InputError(f"{path}: no record left to resolve ({'; '.join(self.notes)})", fix="give the records IDs, one per record")
            return
        fs, rules, spec = self.pipeline.fs, self.pipeline.rules, self.pipeline.kind
        if spec and spec.name_field in present:
            if self.labels is None:  # full() and increment() merge them with the run's first
                self.labels = merge_answers(None, self._given(), self.uid)
            self.classifier = kind_classifier(self.settings, spec, self.labels)
            self._known(rows, path)
            self.inputs += file_facts([self.settings.root / NAME_MODEL, *([Path(self.kind_labels)] if self.kind_labels else [])])
        normalized, used = [*rules.normalized(), *fs.normalized()], rules.used() | fs.used()
        reader = self.con.cursor().sql(f"SELECT * FROM {rows}").to_arrow_reader(self.chunk_rows)  # its own cursor: inserts go on alongside
        for i, batch in enumerate(reader):
            chunk = prepare(fs.standardize, batch.to_pandas().astype("string"), normalized, used, kind=self.classifier)
            self.con.register("er_chunk", chunk)
            self.con.execute(f"CREATE TABLE {into} AS SELECT * FROM er_chunk" if i == 0 else f"INSERT INTO {into} SELECT * FROM er_chunk")
            self.con.unregister("er_chunk")
        self.n = self._count(into)
        kinds = {}
        if self.classifier is not None:  # how many records each kind holds
            kinds = dict(self.con.execute(f"SELECT kind, count(*) FROM {into} GROUP BY 1").fetchall())
            kinds = {"companies": kinds.get(2, 0), "persons": kinds.get(1, 0), "not sure": kinds.get(0, 0),
                     "decided by people": self._count(f"{into} WHERE kind_by = 'people'"), "held back": self._count(f"{into} WHERE kind_held")}
        self._done("load", "O(N·L)", f"O({self.n:,}·L)", t, records=self.n, disabled=len(self.disabled), set_aside=self._count("set_aside"), **kinds)

    def _known(self, rows: str, path: str | Path) -> None:
        """The trust boundary of the answers given (kind_labels): each names a record of this file, as each decision must.
        A spreadsheet reads 0000000151 as the number 151: that sheet's answers would stand for no record. O(answers + N)."""
        if self.given is None or not len(self.given):
            return
        self.con.register("er_given_ids", self.given[[self.uid]])
        unknown = [x for x, in self.con.execute(f"""SELECT {q(self.uid)} FROM er_given_ids WHERE {q(self.uid)} NOT IN
            (SELECT {q(self.uid)} FROM {rows}) ORDER BY 1 LIMIT 5""").fetchall()]
        self.con.unregister("er_given_ids")
        if unknown:
            raise InputError(f"{self.kind_labels}: answers for records not in {path}: {unknown}",
                             fix="check the IDs, as the run wrote them in kind_review.parquet: a spreadsheet may have read them as numbers")

    def _set_aside(self, src: str, stored: str | None) -> str:
        """The records a run can resolve. Rows identical in every column are kept once. Set aside, with the reason, in
        the table set_aside (written to set_aside/, to be fixed and added by an increment): a record without an ID;
        every record of an ID that holds different content; with `stored` (an increment), a record already in the run.
        O(N) to count; the rest only when something is off."""
        u = q(self.uid)
        blank, known = f"nullif(trim({u}), '') IS NULL", f"{u} IN (SELECT {u} FROM {stored})" if stored else "FALSE"
        n, ids, empty, clash = self.con.execute(f"""SELECT count(*), count(DISTINCT {u}), count(*) FILTER (WHERE {blank}),
            count(*) FILTER (WHERE {known}) FROM {src}""").fetchall()[0]
        self.con.execute(f"CREATE OR REPLACE TABLE set_aside AS SELECT *, ''::VARCHAR AS reason FROM {src} WHERE FALSE")
        if n and empty == n:
            raise InputError(f"no record has an ID in column {self.uid}", fix="map id in config/settings.toml [columns] to the column holding each record's ID")
        if not empty and ids == n and not clash:
            return src
        self.con.execute(f"CREATE OR REPLACE TABLE er_in AS SELECT DISTINCT * FROM {src}")
        if (kept := self._count("er_in")) < n:
            self.notes.append(f"{n - kept:,} rows identical to another in every column, kept once")
        self.con.execute(f"""INSERT INTO set_aside SELECT *, CASE WHEN {blank} THEN 'no ID' WHEN {known} THEN 'already in the run'
                ELSE 'the same ID with different content' END FROM er_in
            WHERE {blank} OR {known} OR {u} IN (SELECT {u} FROM er_in GROUP BY {u} HAVING count(*) > 1)""")
        self.notes += [f"{k:,} records set aside: {reason}" for reason, k in
                       self.con.execute("SELECT reason, count(*) FROM set_aside GROUP BY 1 ORDER BY 1").fetchall()]
        return f"(SELECT * FROM er_in WHERE NOT ({blank}) AND {u} NOT IN (SELECT {u} FROM set_aside WHERE {u} IS NOT NULL))"

    def budget(self) -> pd.DataFrame:
        """Exact block sizes on this file, per rule and generator, by group-by, before any join: pairs, pairs per record,
        the largest block, and the oversized blocks (budget.min_oversized() records or more). Those are never joined
        blind: a generator checks each on a sample first (er.candidates), and a rule never trusts their values
        (_untrusted). The run stops only if the pairs of the normal blocks alone would not fit (capacity)."""
        t, rows = time.perf_counter(), []
        m = self.pipeline.fs.budget.min_oversized()
        rules = [KeyBlocker(name=rule.name, keys=tuple(map(Key, st.keys(rule)))) for st in self.pipeline.rules.stages for rule in st.rules]
        for kind, x in [*(("rule", k) for k in rules), *(("generator", g) for g in self.pipeline.fs.blockers)]:
            rows.append(dict(kind=kind, name=x.name, **estimate(x, "records", 0 if kind == "rule" else self.n, self.con, oversized_from=m)))
        plan = pd.DataFrame(rows).assign(per_record=lambda d: (d["est_pairs"] / max(self.n, 1)).round(2),
                                         normal=lambda d: d["est_pairs"] - d["oversized_pairs"])
        self._done("budget", "O(N)", f"O({self.n:,}) per rule and generator", t, pairs=int(plan["est_pairs"].sum()),
                   oversized_blocks=int(plan["oversized_blocks"].sum()))
        if (normal := int(plan["normal"].sum())) > (cap := self.capacity()):
            raise InputError(f"the normal blocks alone would make {normal:,} pairs, more than fit in memory and the temp disk "
                             f"({cap:,} pairs at about {BYTES_PER_PAIR} bytes each); the most: " +
                             ", ".join(f"{x.name} {x.normal:,}" for x in plan.nlargest(3, "normal").itertuples()),
                             fix="give DuckDB more room (--compute memory_limit=… temp_directory=<a disk with space>), or resolve the file in parts")
        self.plan = plan
        return plan

    def capacity(self) -> int:
        """The pairs that fit in DuckDB's memory limit plus the room it may spill to, at BYTES_PER_PAIR."""
        limit = self.con.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]
        return int((size_bytes(limit) + self.spill_room()) / BYTES_PER_PAIR)

    def spill_room(self) -> float:
        """The bytes DuckDB may spill: its temp directory's free space, capped as DuckDB caps it (max_temp_directory_size:
        by default 90% of that space)."""
        temp, cap = self.con.execute("SELECT current_setting('temp_directory'), current_setting('max_temp_directory_size')").fetchall()[0]
        free = shutil.disk_usage(temp if temp and os.path.isdir(temp) else ".").free
        return 0.9 * free if "%" in cap else min(free, size_bytes(cap))

    def _untrusted(self, i: int, rule: str, rule_keys: list[str], within: str | None = None) -> str | None:
        """The values of a rule's keys held by an oversized block (with `within`, a table of records: only the values
        they hold), as a table; None if none. One value on that many records is not one entity's, so the rule leaves
        it out, and the summary names it. O(N), a group-by."""
        m, cols = self.pipeline.fs.budget.min_oversized(), ", ".join(q(c) for c in rule_keys)
        filled = " AND ".join(f"{q(c)} IS NOT NULL" for c in rule_keys)
        held = f" AND ({cols}) IN (SELECT {cols} FROM {within})" if within else ""
        name = f"er_untrusted_{i}"
        self.con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT {cols}, count(*) AS __n FROM records WHERE {filled}{held} "
                         f"GROUP BY {cols} HAVING count(*) >= {m} ORDER BY __n DESC")
        n, records = self.con.execute(f"SELECT count(*), coalesce(sum(__n), 0) FROM {name}").fetchall()[0]
        if not n:
            return None
        top = self.con.execute(f"SELECT * FROM {name} LIMIT 1").fetchall()[0]
        self.notes.append(f"rule {rule} doesn't trust {n:,} value{'s' if n > 1 else ''} held by {m}+ records ({int(records):,} records)")
        self.examples.append(f"rule {rule}: {', '.join(f'{c} = {v}' for c, v in zip(rule_keys, top))} in {top[-1]:,} records")
        return name

    def fit(self) -> dict:
        """λ from the near-certain rules, u by random sampling, m by EM, on a fixed-size sample of whole postal areas
        (households stay together, and the cost doesn't grow with the file); skipped when a fitted model was given. Then
        u measured on this file (the model's choice), which the gate on oversized blocks and the scores both use: the
        sample's u would under-credit a field whose values grow with the file. On a file no bigger than the sample, a fit
        that samples as many pairs as the file's u (fit_u_max_pairs unset) shares that sample (er.match.scored_sample). Keeps the basis an increment needs to judge whether these u
        have gone stale (er.match.u_basis)."""
        t, fs = time.perf_counter(), self.pipeline.fs
        if self.model is None:
            n = self.pipeline.fit_rows
            area = q("postal_code__first3") if "postal_code__first3" in self._columns() else None
            order = f"hash({area}), hash({q(self.uid)})" if area else f"hash({q(self.uid)})"
            sample = self.con.execute(f"SELECT * FROM records ORDER BY {order} LIMIT {n}").df().astype("string")
            self.model = train_fs(fs.model, sample, self.db, self.uid)
            self.notes += [f"the fit found no two records sharing {f} in its sample of {len(sample):,}, so it learned nothing from them"
                           for f in self.model["er"].get("skipped", [])]
        self.scoring, self.basis = self.model, {}
        if fs.model.u_from_scored:
            self.scoring, sampled, exact = scored_u(fs.model, self.model, "records", self.db, self.uid)
            self.basis = u_basis(fs.model, sampled, exact, "records", self.db)
        self._done("fit", "O(n + S·K + P_em·K) + O(N + S·K)", f"n = {self.model['er']['fit_rows']:,}; u on {self.n:,} records", t)
        return self.model

    def _columns(self) -> set[str]:
        return {c[0] for c in self.con.execute("DESCRIBE records").fetchall()}

    def _resolved(self, clusters: str) -> str:  # the records in a cluster of two or more
        return f"(SELECT {q(self.uid)} FROM {clusters} WHERE cluster_id IN (SELECT cluster_id FROM {clusters} GROUP BY 1 HAVING count(*) > 1))"

    def rules(self) -> None:
        """One join per rule (the first rule wins a pair), then the cascade: a later stage adds a pair only if it
        touches a record still unresolved; clusters are merged after each stage."""
        t = time.perf_counter()
        self.con.execute(f"CREATE OR REPLACE TABLE rule_clusters AS SELECT {q(self.uid)}, {q(self.uid)} AS cluster_id FROM records")
        self._rules()
        p = self._count("rule_edges")
        self._done("rules", "O(N + Σ P_r·L²) + O(E·d + N)", f"O({self.n:,} + {p:,} pairs)", t, pairs=p, kept=self._count("rule_kept"))

    def _rules(self, batch: str | None = None) -> None:
        """The rules' pairs (er.match.rule_edges: every record, or a batch against all), less the values each rule
        doesn't trust (_untrusted), then the cascade into rule_clusters, which the caller starts: a stage's pair is kept
        only if it touches a record still unresolved, and merged in (er.cluster.merge)."""
        l, r, rules = q(self.l), q(self.r), self.pipeline.rules
        trust = {}
        for i, (st, rule) in enumerate((st, rule) for st in rules.stages for rule in st.rules):
            if (untrusted := self._untrusted(i, rule.name, st.keys(rule), within=batch)):
                trust[i] = f"NOT EXISTS (SELECT 1 FROM {untrusted} z WHERE {' AND '.join(f'z.{q(c)} = l.{q(c)}' for c in st.keys(rule))})"
        _, self.rule_seconds = rule_edges(rules, "records", self.db, self.uid, batch=batch, trust=trust, into="rule_edges")
        self.con.execute("CREATE OR REPLACE TABLE rule_kept AS SELECT * FROM rule_edges WHERE FALSE")
        for st in rules.stages:
            done = self._resolved("rule_clusters")
            self.con.execute(f"""CREATE OR REPLACE TABLE er_stage AS SELECT * FROM rule_edges WHERE stage = '{st.name}'
                AND NOT ({l} IN {done} AND {r} IN {done})""")
            self.con.execute("INSERT INTO rule_kept SELECT * FROM er_stage")
            merge(self.con, self.db, "rule_clusters", "er_stage", "rule_clusters", self.uid)

    def candidates(self) -> pd.DataFrame:
        t, fs = time.perf_counter(), self.pipeline.fs
        assert self.scoring is not None, "fit() before candidates(): the gate scores oversized blocks' samples with the model"
        if not fs.bridge:  # the query: the records the rules left alone
            self.con.execute(f"CREATE OR REPLACE TABLE er_query AS SELECT * FROM {self._singletons('rule_clusters')}")
        _, report = candidates(fs.blockers, "records", self.uid, None if fs.bridge else "er_query", fs.budget,
                               clusters="rule_clusters" if fs.bridge else None, con=self.con, into="cands",
                               gate=self._gate, floor=review_floor(self.pipeline), capacity=self.capacity())
        self._gated(report.attrs["gated"])
        c = self._count("cands")
        self._done("candidates", "O(N·L + Σ P_g)", f"O({self.n:,}·L + {int(report['pairs'].sum()):,})", t, candidates=c,
                   oversized_kept=int((self.gated.get("decision", pd.Series(dtype=str)) == "kept").sum()),
                   oversized_skipped=int(self.gated.get("decision", pd.Series(dtype=str)).str.startswith("skipped").sum()))
        return report

    def _gate(self, pairs: pd.DataFrame) -> pd.DataFrame:  # an oversized block's sampled pairs, scored as the candidates will be
        return score_fs(self.scoring, "records", pairs, self.db, self.uid, n_records=self.n)

    def _gated(self, records: list[dict]) -> None:  # the oversized blocks' decisions, kept for qa and named in the summary
        self.gated = gated = pd.DataFrame(records)
        if gated.empty:
            return
        floor = review_floor(self.pipeline)
        for x in gated.sort_values("pairs", ascending=False).head(5).itertuples():
            self.notes.append(f"{x.generator}: a block of {x.records:,} records ({x.pairs:,} pairs); {int(x.hits)} of {int(x.sampled)} "
                              f"sampled pairs reach {floor:g} bits: {x.decision}")
            self.examples.append(f"{x.generator}: {x.value} holds {x.records:,} records: {x.decision}")
        if len(gated) > 5:
            kept = (gated["decision"] == "kept").sum()
            self.notes.append(f"{len(gated):,} oversized blocks in all: {kept:,} kept, {len(gated) - kept:,} skipped (qa.md lists them)")

    def _singletons(self, clusters: str) -> str:
        return f"(SELECT {q(self.uid)} FROM {clusters} WHERE cluster_id IN (SELECT cluster_id FROM {clusters} GROUP BY 1 HAVING count(*) = 1))"

    def score(self) -> None:
        """Every candidate scored by Splink, with the model and u that fit() settled."""
        t, k = time.perf_counter(), len(self.pipeline.fs.model.comparisons)
        score_fs(self.scoring, "records", "cands", self.db, self.uid, into="scores")
        self._done("score", "O(C·K·L²)", f"O({self._count('scores'):,}·{k}·L²)", t)

    def scored(self) -> str:
        """Every scored pair with its generators (sources) and what acceptance reads besides the weight: named, a name
        compared (fs.needs); keep, the pair joins two rule clusters (bridge) or touches a record the rules left alone. As
        SQL, for _accept, and for design time to accept at other weights (er.pipeline)."""
        fs, l, r, u = self.pipeline.fs, q(self.l), q(self.r), q(self.uid)
        done = self._resolved("rule_clusters")
        keep = "a.cluster_id <> b.cluster_id" if fs.bridge else f"NOT (s.{l} IN {done} AND s.{r} IN {done})"
        return f"""SELECT s.*, c.sources, {named_sql(fs)} AS named, {keep} AS keep FROM scores s JOIN cands c USING ({l}, {r})
            JOIN rule_clusters a ON a.{u} = s.{l} JOIN rule_clusters b ON b.{u} = s.{r}"""

    def _accept(self) -> None:
        """matches: the scored pairs at the threshold or above that are named and kept (scored), less those people
        decided are no match; kept: those, the rules' pairs, and the pairs people decided are a match (er_decisions,
        loaded by full() from the run folder; empty otherwise)."""
        fs, l, r = self.pipeline.fs, q(self.l), q(self.r)
        self.con.execute(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
        self.con.execute(f"""CREATE OR REPLACE TABLE matches AS
            SELECT s.{l}, s.{r}, s.match_weight, s.match_probability, s.sources FROM ({self.scored()}) s
            WHERE s.match_weight >= {fs.min_match_weight} AND s.named AND s.keep
              AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r} AND d.decision = 'no_match')""")
        self.con.execute(f"""CREATE OR REPLACE TABLE kept AS SELECT {l}, {r} FROM rule_kept UNION ALL SELECT {l}, {r} FROM matches
            UNION ALL SELECT {l}, {r} FROM er_decisions WHERE decision = 'match'""")

    def _gold(self, old: str | None = None) -> None:
        """Each record's cluster, and what resolved it: if the rules put it in a cluster, the first rule (in rule order)
        among its kept rule pairs; else the model, if one of its pairs was accepted; else people (review), if a pair
        they decided joined it. An increment passes the stored gold as `old`, whose answers stand."""
        fs, l, r, u = self.pipeline.fs, q(self.l), q(self.r), q(self.uid)
        order = " ".join(f"WHEN '{rule.name}' THEN {i}" for i, rule in enumerate(rule for st in self.pipeline.rules.stages for rule in st.rules))
        stage = f"CASE WHEN rz.n > 1 THEN '{fs.previous_stage}' WHEN m.id IS NOT NULL THEN '{fs.stage}' WHEN z.n > 1 THEN 'review' END"
        by = f"CASE WHEN rz.n > 1 THEN f.rule WHEN m.id IS NOT NULL THEN '{fs.model.name}' WHEN z.n > 1 THEN 'review' END"
        if old:
            stage, by = f"coalesce(o.resolved_stage, {stage})", f"coalesce(o.resolved_by, {by})"
        kinds = "kind" in self._columns()  # each record's kind, and its customer's (customer_kinds)
        self.con.execute(f"""CREATE OR REPLACE TABLE gold AS
            WITH touch AS (SELECT {l} AS id, rule FROM rule_kept UNION ALL SELECT {r}, rule FROM rule_kept),
                 first AS (SELECT id, arg_min(rule, CASE rule {order} END) AS rule FROM touch GROUP BY id),
                 rsize AS (SELECT cluster_id, count(*) AS n FROM rule_clusters GROUP BY 1),
                 size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1),
                 matched AS (SELECT {l} AS id FROM matches UNION SELECT {r} FROM matches)
                 {f", customer AS ({customer_kinds('clusters', 'records', u)})" if kinds else ""}
            SELECT k.{u}, k.cluster_id, {stage} AS resolved_stage, {by} AS resolved_by{", x.kind, x.kind_p, x.kind_by, x.kind_held, c.customer_kind" if kinds else ""}
            FROM clusters k JOIN size z USING (cluster_id) JOIN rule_clusters rc USING ({u}) JOIN rsize rz ON rz.cluster_id = rc.cluster_id
                 LEFT JOIN first f ON f.id = k.{u} LEFT JOIN matched m ON m.id = k.{u} {f"LEFT JOIN {old} o USING ({u})" if old else ""}
                 {f"JOIN records x USING ({u}) JOIN customer c USING (cluster_id)" if kinds else ""}
            ORDER BY k.{u}""")

    def cluster(self) -> None:
        """Accept at min_match_weight, then cluster every kept pair, the rules' and these; then gold."""
        t = time.perf_counter()
        self._accept()
        merge(self.con, self.db, "rule_clusters", "kept", "clusters", self.uid)
        self._gold()
        e = self._count("matches")
        self._done("cluster", "O(C + E·d + N)", f"O({self._count('scores'):,} + {e:,}·d + {self.n:,})", t, accepted=e,
                   expected_false=self._expected_false())

    def _expected_false(self) -> float:  # the false links the model expects among those it accepted: Σ (1 − match probability), O(E)
        return round(self.con.execute("SELECT coalesce(sum(1 - match_probability), 0) FROM matches").fetchall()[0][0], 2)

    def write(self, out: Path, part: int = 0, replace: list[Path] | None = None, report: tuple[str | Path, Path] | None = None) -> None:
        """Gold (each record's cluster, the stage and rule that resolved it, its kind and its customer's), the accepted
        pairs with their weights, the rules' pairs, as Parquet; and the state an increment needs: the standardized
        records, the rules' clusters and people's person/company answers. Records, rules' pairs and matches are folders
        that increments append to. `replace` (a full run): the old run's files, which the new ones replace. `report`
        (the input and the pipeline file): the reports for people (report()), built first and written with these files.
        Staged: see the module."""
        people, frames = self.report(report[0], out, report[1]) if report else ([], [])
        t, state, name = time.perf_counter(), out / "state", f"part-{part:05d}.parquet"
        aside = [("SELECT * FROM set_aside", out / "set_aside" / name)] if self._count("set_aside") else []
        texts = [(json.dumps(self.model, ensure_ascii=False), state / "model.json"), (self.config, state / "config.txt")] if part == 0 else []
        if self.basis:  # the u this run scored with, and what an increment needs to tell when they go stale
            texts.append((json.dumps(dict(model=self.scoring, basis=self.basis), ensure_ascii=False), state / "scoring.json"))
        sheets, n = [], next_part(out / KIND_ANSWERS)
        if n == 0 and (old := state / "kind_labels.parquet").exists():  # a folder that keeps its answers in state/: its first sheet
            sheets, n = [(f"SELECT * FROM read_parquet({lit(old)})", out / KIND_ANSWERS / "part-00000.parquet")], 1
        if self.given is not None and len(self.given):  # the sheet given, kept as it came: the next run reads it again
            self.con.register("er_given", self.given)
            sheets.append(("SELECT * FROM er_given", out / KIND_ANSWERS / f"part-{n:05d}.parquet"))
        self._stage(out, [("SELECT * FROM rule_kept", out / "rule_kept" / name), ("SELECT * FROM matches", out / "matches" / name),
                          (f"SELECT * FROM gold ORDER BY {q(self.uid)}", out / "gold.parquet"),
                          ("SELECT * FROM rule_clusters", state / "rule_clusters.parquet"),
                          (f"SELECT * FROM {'records' if part == 0 else 'new_records'}", state / "records" / name), *aside, *sheets],
                    texts + people, replace, frames)
        self._done("write", "O(N + C)", f"O({self.n:,} + {self._count('matches'):,})", t)
        self._log(out, part > 0, part=part, disabled=self.disabled)

    def _stage(self, out: Path, tables: list[tuple[str, Path]], texts: list[tuple[str, Path]] = (), replace: list[Path] | None = None,
               frames: list[tuple[pd.DataFrame, Path]] = ()) -> None:
        """Write every file under a temporary name; once all are complete, save the moves still owed (pending.json),
        then do them. An interruption before that leaves the folder as it was; one after it, finish_writes completes.
        With `replace` (a full run), the new run files are written in FULL_TMP, and each of its entries replaces the old
        run's; the old entries the new run doesn't write go. A file outside the run files (people's work) is only added."""
        if replace is not None:
            shutil.rmtree(out / FULL_TMP, ignore_errors=True)  # the files of a full run cut short before its moves
        whole = lambda d: replace is not None and d.relative_to(out).parts[0] in RUN_FILES
        tmp = lambda d: out / FULL_TMP / d.relative_to(out) if whole(d) else d.with_name(d.name + ".tmp")
        for sql, dest in tables:
            tmp(dest).parent.mkdir(parents=True, exist_ok=True)
            self.con.execute(f"COPY ({sql}) TO {lit(tmp(dest))} (FORMAT parquet)")
        for text, dest in texts:
            tmp(dest).parent.mkdir(parents=True, exist_ok=True)
            tmp(dest).write_text(text, encoding="utf-8")
        for frame, dest in frames:  # sheets for people: pandas keeps their empty answer columns typed
            tmp(dest).parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(tmp(dest))
        dests = [dest for _, dest in (*tables, *texts, *frames)]
        staged = [[str(tmp(d)), str(d)] for d in dests if not whole(d)]
        if replace is not None:
            new = sorted({d.relative_to(out).parts[0] for d in dests if whole(d)})
            staged += [[None, str(x)] for x in replace if x.name not in new] + [[str(out / FULL_TMP / x), str(out / x)] for x in new]
        (out / (PENDING + ".tmp")).write_text(json.dumps(staged), encoding="utf-8")
        os.replace(out / (PENDING + ".tmp"), out / PENDING)  # from here on the write is done, whatever happens next
        finish_writes(out)

    def _log(self, out: Path, append: bool, **entry: object) -> None:
        """steps.json: one entry per run, increment or set of decisions: when, the code and config that ran, the files
        read with their SHA-256, and each step."""
        log = out / "steps.json"
        runs = json.loads(log.read_text())["runs"] if append and log.exists() else []
        entry = dict(at=datetime.now().isoformat(timespec="seconds"), code=code_version(self.settings.root), config=self.config,
                     inputs=self.inputs, **entry, steps=self.steps)
        tmp = log.with_name(log.name + ".tmp")  # complete before it replaces the log: a write cut short leaves the old one
        tmp.write_text(json.dumps(dict(runs=[*runs, entry]), indent=1, default=str))
        os.replace(tmp, log)

    def report(self, path: str | Path, out: Path, pipeline: Path) -> tuple[list[tuple[str, Path]], list[tuple[pd.DataFrame, Path]]]:
        """Step 9, for people: qa.md (the label-free checks, qa), report.txt (the run on a page with no record's value in
        it), review.parquet (the pairs to decide and to audit; an increment keeps the previous sheet's open rows) and, on
        a full run that tells persons from companies, kind_review.parquet (records to answer, none answered already; a
        record an increment holds back reaches the next full run's sheet). Built before the run's files are written, and
        returned as texts and frames for write() to stage with them: a run never lands without its reports, which a
        retry could not make again, since nothing is new by then. `path` is the input, `pipeline` the pipeline file, both
        named in the reports. Keeps qa's tables, the summary first, in self.tables."""
        t = time.perf_counter()
        tables = qa(self, previous=out / "review.parquet" if self.added is not None else None)
        frames = [(tables.pop("review_sheet"), out / "review.parquet")]
        text = ["# Run checks", "", f"Input: `{path}` · {self.n:,} records", ""]
        for name, table in tables.items():
            text += [f"## {name.replace('_', ' ')}", "", markdown(table.round(4)) if len(table) else "none", ""]
        if self.classifier is not None and self.added is None:
            answered = self.labels[self.uid].astype("string") if self.labels is not None else ()
            frames.append((kind_review_sheet(self.con, "records", self.uid, self.pipeline.kind, self.settings.flag_company, answered),
                           out / "kind_review.parquet"))
        self.tables = tables
        texts = [("\n".join(text), out / "qa.md"), (report_text(self, tables, pipeline), out / "report.txt")]
        self._done("report", "O(review pairs) + O(N)", f"O({len(frames[0][0]):,} review pairs + {self.n:,})", t)
        return texts, frames

    # ---------- increments ----------

    @locked
    def increment(self, path: str | Path, out: Path, pipeline_file: Path | None = None) -> "Run":
        """Add a batch of new records to the run written in `out`, with its reports as full() writes them. See the module
        docstring for the cost."""
        state, u, l, r = out / "state", q(self.uid), q(self.l), q(self.r)
        finish_writes(out)
        if not (state / "model.json").exists():
            raise InputError(f"no run in {out} to add records to", fix="resolve the records into that folder first, without --increment")
        if (state / "config.txt").exists() and (state / "config.txt").read_text(encoding="utf-8") != self.config:
            raise InputError(f"the pipeline or the column mapping changed since the full run in {out}: an increment would resolve its batch otherwise",
                             fix="run a full run with --overwrite, or the increment with the pipeline and config/settings.toml that run used")
        self.model = json.loads((state / "model.json").read_text(encoding="utf-8"))
        part = next_part(state / "records")
        parts = ", ".join(lit(x) for x in sorted((state / "records").glob("part-*.parquet")))  # not a glob: this run's own part comes later
        self.con.execute(f"CREATE OR REPLACE VIEW old_records AS SELECT * FROM read_parquet([{parts}], union_by_name = true)")
        self.labels = self._answers(out)  # the batch's kinds rest on the run's answers, and any given with it
        self.load(path, into="new_records", stored="old_records")  # a record already in the run is set aside: a retry adds nothing twice
        self.added = self.n
        if not self.added:
            other = self.con.execute("SELECT count(*) FROM set_aside WHERE reason <> 'already in the run'").fetchall()[0][0]
            if other:
                raise InputError(f"{path}: no new record to add ({'; '.join(self.notes)})", fix="give the records set aside IDs, one per record")
            return self  # every record is already in the run: nothing to do
        self.con.execute("CREATE OR REPLACE TABLE records AS SELECT * FROM old_records UNION ALL BY NAME SELECT * FROM new_records")  # read by every step: once
        self.con.execute(f"CREATE OR REPLACE TABLE new_ids AS SELECT {u} FROM new_records")
        self.n = self._count("records")

        t, again, fs = time.perf_counter(), [], self.pipeline.fs  # the stored model; u settled before the gate needs them
        self.scoring, self.basis = self.model, {}
        if fs.model.u_from_scored:  # exact levels counted again; a comparison sampled again only once it is stale
            stored = state / "scoring.json"
            basis = json.loads(stored.read_text(encoding="utf-8"))["basis"] if stored.exists() else {}
            self.scoring, self.basis, again = refreshed_u(fs.model, self.model, basis, "records", self.db, self.uid)
            self.notes += [f"u of {c} measured again: it drifted {self.basis[c]['last_check']['drift_bits']:.3f} bits, more than "
                           f"its sampling error ({self.basis[c]['last_check']['se_bits']:.3f})" for c in again if self.basis[c]['last_check']['drift_bits'] is not None]
        self._done("fit", "O(N + S·K_stale)", f"O({self.n:,} + {fs.model.u_max_pairs:,.0f}·{len(again)})", t, sampled_again=len(again))

        t = time.perf_counter()  # the rules: each against the batch only, then the cascade on the merged clusters
        self.con.execute(f"""CREATE OR REPLACE TABLE rule_clusters AS SELECT * FROM read_parquet({lit(state / 'rule_clusters.parquet')})
            UNION ALL SELECT {u}, {u} AS cluster_id FROM new_ids""")
        self._rules("new_records")
        self._done("rules", "O(|Δ|·Σ b + scan)", f"O({self._count('new_ids'):,} new records)", t, kept=self._count("rule_kept"))

        t = time.perf_counter()
        _, report = candidates(fs.blockers, "records", self.uid, "new_ids", fs.budget,
                               clusters="rule_clusters" if fs.bridge else None, con=self.con, into="cands", touching=True,
                               gate=self._gate, floor=review_floor(self.pipeline), capacity=self.capacity())
        self._gated(report.attrs["gated"])
        self._done("candidates", "O(|Δ|·Σ b + scan)", f"{self._count('cands'):,} pairs touching the batch", t)

        t = time.perf_counter()
        self.con.execute(f"""CREATE OR REPLACE TABLE touched AS SELECT * FROM records WHERE {u} IN
            (SELECT {l} FROM cands UNION SELECT {r} FROM cands)""")
        score_fs(self.scoring, "touched", "cands", self.db, self.uid, into="scores", n_records=self.n)
        self._done("score", "O(C_Δ·K·L²)", f"O({self._count('cands'):,}·{len(fs.model.comparisons)}·L²)", t)

        t = time.perf_counter()
        self._accept()
        self.con.execute(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM read_parquet({lit(out / 'gold.parquet')})")
        self.con.execute(f"CREATE OR REPLACE TABLE er_base AS SELECT {u}, cluster_id FROM gold_old UNION ALL SELECT {u}, {u} FROM new_ids")
        merge(self.con, self.db, "er_base", "kept", "clusters", self.uid)
        self._gold("gold_old")
        self._done("cluster", "O(C_Δ + touched clusters)", f"{self._count('matches'):,} accepted", t, accepted=self._count("matches"),
                   expected_false=self._expected_false())
        self.write(out, part, report=(path, pipeline_file) if pipeline_file else None)
        return self

    def _answers(self, out: Path) -> pd.DataFrame | None:
        """People's person/company answers: the sheets the folder `out` keeps, newest first, then the one given on top.
        O(answers)."""
        parts = sorted((out / KIND_ANSWERS).glob("part-*.parquet"), reverse=True) or [
            f for f in [out / "state" / "kind_labels.parquet"] if f.exists()]  # a folder that keeps its answers in state/
        kept = pd.concat([pd.read_parquet(f).astype({self.uid: "string"}) for f in parts], ignore_index=True) if parts else None
        return merge_answers(kept, self._given(), self.uid)

    def _given(self) -> pd.DataFrame | None:
        """The answered sheet given (kind_labels), checked: the trust boundary. Its filled rows, read once."""
        if self.kind_labels is None or self.given is not None:
            return self.given
        path = Path(self.kind_labels)
        if not path.is_file():
            raise InputError(f"{path}: no such file of person/company answers", fix="give --kind-labels the answered kind_review.parquet")
        given = pd.read_parquet(path)
        if {self.uid, "kind"} - set(given.columns):
            raise InputError(f"{path}: needs the columns {self.uid} and kind; it has {sorted(given.columns)}",
                             fix="give back kind_review.parquet with kind filled in: 1 person, 2 company, 0 can't tell")
        given = given[pd.to_numeric(given["kind"], errors="coerce").isin([PERSON, COMPANY, UNSURE]).to_numpy()].reset_index(drop=True)
        given[self.uid] = given[self.uid].astype("string")  # as the run reads every ID: text
        if (blank := int(given[self.uid].str.strip().fillna("").eq("").sum())):
            raise InputError(f"{path}: {blank:,} answered rows have no {self.uid}", fix="fill in each answered row's ID, or clear its answer")
        self.given = given
        return self.given

    # ---------- people's decisions ----------

    def _load_decisions(self, out: Path) -> None:
        """The decisions stored in this run folder, on records of this file, the latest per pair, for _accept."""
        u, l, r, parts = q(self.uid), q(self.l), q(self.r), out / DECISIONS
        if any(parts.glob("part-*.parquet")):
            self.con.execute(f"""CREATE OR REPLACE TABLE er_decisions AS SELECT {l}, {r}, arg_max(decision, filename) AS decision
                FROM read_parquet({lit(parts / 'part-*.parquet')}, filename = true)
                WHERE {l} IN (SELECT {u} FROM records) AND {r} IN (SELECT {u} FROM records) GROUP BY {l}, {r}""")

    @locked
    def decide(self, path: str | Path, out: Path) -> "Run":
        """Apply people's decisions on review pairs (a Parquet file: uid_l, uid_r, decision) to the run in `out`,
        scoring nothing. Each `match` pair merges its two clusters, each cluster one node, and a record joined only this
        way is resolved by `review`. A `no_match` pair splits nothing here; every decision is stored in decisions/, and a
        full run on this folder applies them again, never accepting a `no_match` pair. Rows without a decision are
        skipped. O(D + touched clusters) + O(N) to rewrite gold."""
        t, u, l, r = time.perf_counter(), q(self.uid), q(self.l), q(self.r)
        finish_writes(out)
        if not (out / "gold.parquet").exists():
            raise InputError(f"no run in {out} to apply decisions to", fix="resolve the records into that folder first (--input … --output …)")
        self.con.execute(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM read_parquet({lit(out / 'gold.parquet')})")
        source = open_source(path, self.con, [self.l, self.r, "decision"])
        src, cols, self.inputs = source.sql, set(source.columns), file_facts(source.files)
        if {self.l, self.r, "decision"} - cols:  # the trust boundary: say what is wrong, row by row where it can
            raise InputError(f"{path}: needs the columns {self.l}, {self.r} and decision; it has {sorted(cols)}",
                             fix="give back review.parquet with decision filled in, or a file with those three columns")
        self.con.execute(f"""CREATE OR REPLACE TABLE er_decisions AS SELECT DISTINCT least({l}::VARCHAR, {r}::VARCHAR) AS {l},
            greatest({l}::VARCHAR, {r}::VARCHAR) AS {r}, lower(trim(decision::VARCHAR)) AS decision FROM {src}
            WHERE nullif(trim(decision::VARCHAR), '') IS NOT NULL""")
        bad = self.con.execute("SELECT DISTINCT decision FROM er_decisions WHERE decision NOT IN ('match', 'no_match')").fetchall()
        if bad:
            raise InputError(f"{path}: a decision is match or no_match, not {sorted(x for x, in bad)}", fix="correct those rows, or leave them empty")
        both = self.con.execute(f"SELECT {l}, {r} FROM er_decisions GROUP BY ALL HAVING count(*) > 1 LIMIT 5").fetchall()
        if both:
            raise InputError(f"{path}: pairs decided both ways: {both}", fix="keep one decision per pair")
        unknown = self.con.execute(f"""SELECT id FROM (SELECT {l} AS id FROM er_decisions UNION SELECT {r} FROM er_decisions)
            WHERE id NOT IN (SELECT {u} FROM gold_old) ORDER BY id LIMIT 5""").fetchall()
        if unknown:
            raise InputError(f"{path}: records not in the run in {out}: {[x for x, in unknown]}", fix="check --output, or the IDs in the file")
        self.n = self._count("gold_old")
        self.con.execute(f"CREATE OR REPLACE TABLE er_base AS SELECT {u}, cluster_id FROM gold_old")
        self.con.execute(f"CREATE OR REPLACE TABLE er_review AS SELECT {l}, {r} FROM er_decisions WHERE decision = 'match'")
        merge(self.con, self.db, "er_base", "er_review", "clusters", self.uid)
        kinds = "kind" in {c[0] for c in self.con.execute("DESCRIBE gold_old").fetchall()}  # each record's kind stands; its customer's follows the merge
        self.con.execute(f"""CREATE OR REPLACE TABLE gold AS WITH size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1)
                 {f", customer AS ({customer_kinds('clusters', 'gold_old', u)})" if kinds else ""}
            SELECT c.{u}, c.cluster_id, coalesce(o.resolved_stage, CASE WHEN z.n > 1 THEN 'review' END) AS resolved_stage,
                   coalesce(o.resolved_by, CASE WHEN z.n > 1 THEN 'review' END) AS resolved_by
                   {", o.kind, o.kind_p, o.kind_by, o.kind_held, k.customer_kind" if kinds else ""}
            FROM clusters c JOIN size z USING (cluster_id) JOIN gold_old o USING ({u}) {"JOIN customer k USING (cluster_id)" if kinds else ""}
            ORDER BY c.{u}""")
        d, m = self._count("er_decisions"), self._count("er_review")
        before, after = (self.con.execute(f"SELECT count(DISTINCT cluster_id) FROM {x}").fetchall()[0][0] for x in ("gold_old", "gold"))
        self._done("decide", "O(D + touched clusters) + O(N)", f"O({d:,} decisions + {self.n:,})", t,
                   decisions=d, matches=m, clusters_joined=before - after)
        parts = out / DECISIONS
        parts.mkdir(exist_ok=True)
        self._stage(out, [(f"SELECT * FROM gold ORDER BY {u}", out / "gold.parquet"),
                          ("SELECT * FROM er_decisions", parts / f"part-{next_part(parts):05d}.parquet")])
        self._log(out, True, decisions=str(path))
        return self

    @locked
    def full(self, path: str | Path, out: Path, overwrite: bool = False, pipeline_file: Path | None = None) -> "Run":
        """Steps 1–8 on the file at `path` into the run folder `out`; with `pipeline_file` (named in the reports), step 8
        writes step 9's reports with the run's files."""
        finish_writes(out)
        held = [out / f for f in RUN_FILES if (out / f).exists()]
        if held and not overwrite:
            raise FileExistsError(f"{out} already holds a run: choose another folder, or overwrite it (scripts/resolve.py --overwrite)")
        self.labels = self._answers(out)  # read before the folder's old state goes
        self.load(path)
        self.budget()
        self.fit()
        self.rules()
        self.candidates()
        self.score()
        self._load_decisions(out)
        self.cluster()
        self.write(out, replace=held, report=(path, pipeline_file) if pipeline_file else None)  # the old run goes only once the new one is complete
        return self


def next_part(folder: Path) -> int:  # one past the highest part-n.parquet: a part deleted by hand frees no number to write over
    return max((int(f.stem.removeprefix("part-")) for f in folder.glob("part-*.parquet")), default=-1) + 1


def file_facts(files: list[Path]) -> list[dict]:
    """Each file read: its path, size and SHA-256, so a run says exactly what went in. O(bytes)."""
    def sha256(f: Path) -> str:
        with open(f, "rb") as fh:
            return hashlib.file_digest(fh, "sha256").hexdigest()
    return [dict(file=str(f), bytes=f.stat().st_size, sha256=sha256(f)) for f in files]


def customer_kinds(clusters: str, kinds: str, u: str) -> str:
    """Each cluster's customer_kind, from its records' kind and kind_p (`kinds`: a table holding both): 2 company if any
    record surely is one; 1 person if no record leans company and one surely is a person; else 0 not sure. O(N)."""
    return f"""SELECT k.cluster_id, CASE WHEN bool_or(x.kind = 2) THEN 2 WHEN coalesce(max(x.kind_p), 0) < 0.5 AND bool_or(x.kind = 1)
               THEN 1 ELSE 0 END::TINYINT AS customer_kind FROM {clusters} k JOIN {kinds} x USING ({u}) GROUP BY 1"""


def named_sql(fs: FSSpec, s: str = "s") -> str:  # er.pipeline.named on scores aliased `s`
    return "(" + (" OR ".join(f"{s}.{q('gamma_' + c)} >= 0" for c in fs.needs) or "TRUE") + ")"


def review_floor(p: Pipeline) -> float:
    """The lowest weight people are asked to decide: the threshold rule's safety margin below min_match_weight, i.e. the
    [threshold] grid point margin_steps below it. Pairs there were clean on cross-validated train, but held back."""
    below = sorted(g for g in p.threshold.grid if g < p.fs.min_match_weight)
    if not p.threshold.margin_steps or not below:
        return p.fs.min_match_weight
    return below[-min(p.threshold.margin_steps, len(below))]


def fill_rates(run: "Run", fields: list[str] | None = None, sample: int = 10_000) -> pd.DataFrame:
    """Each field's share of filled records, flagged under 5%: a field almost never filled is often a mapping mistake.
    Then, on a random sample of `sample` records, the share of filled values that look like the field ([locale.detect];
    a low share is a wrong column or a format the comparisons don't expect), and the share held by its most common
    value (a placeholder such as 0000 counts as an agreement between the records that hold it). O(N·F + sample·F)."""
    cols = run._columns()
    fs = [f for f in (run.fields if fields is None else fields) if f in cols]
    if not fs:
        return pd.DataFrame(columns=["field", "filled", "looks_right", "top_value", "flag"])
    filled = run.con.execute(f"SELECT {', '.join(f'avg(({q(f)} IS NOT NULL)::INT)' for f in fs)} FROM records").fetchall()[0]
    run.con.execute(f"CREATE OR REPLACE TEMP TABLE er_fill_sample AS SELECT {', '.join(f'{q(f)}::VARCHAR AS {q(f)}' for f in fs)} "
                    f"FROM records USING SAMPLE reservoir({sample} ROWS) REPEATABLE (0)")
    pattern = {f: run.settings.detect[f].replace("'", "''") for f in fs if f in run.settings.detect}
    looks = dict(zip(pattern, run.con.execute("SELECT " + ", ".join(f"avg(regexp_matches({q(f)}, '{p}')::INT)" for f, p in pattern.items())
                                              + " FROM er_fill_sample").fetchall()[0])) if pattern else {}
    top = dict(run.con.execute("""SELECT field, max(n) / sum(n) FROM (SELECT field, v, count(*) AS n FROM
        (UNPIVOT er_fill_sample ON COLUMNS(*) INTO NAME field VALUE v) GROUP BY ALL) GROUP BY field""").fetchall())
    return pd.DataFrame(dict(field=fs, filled=filled, looks_right=[looks.get(f) for f in fs], top_value=[top.get(f) for f in fs])).assign(
        flag=lambda d: np.where(d["filled"] < 0.05, "under 5%", ""))


def qa(run: "Run", fields: list[str] | None = None, review: int = 50, previous: Path | None = None) -> dict[str, pd.DataFrame]:
    """The label-free report of a run: a summary in words (records, entities, who joined them, the model's links and the
    false ones it expects among them, what to decide, what the loader fixed), fill rate per field (flagged under 5%)
    (of `fields`, by default every logical field) with the share that looks like the field and the share of its most common value, what was disabled, every step's cost,
    accepted pairs by weight band, cluster sizes, the largest clusters (the over-merge alarm), and the review sheet
    for people (review_sheet). Its rows are of two kinds. "decide": every pair of clusters whose best link scored in the
    threshold's safety margin [review_floor, min_match_weight), or above it with no name compared, not decided yet, best link first. "audit": accepted pairs
    up to 4 bits above the threshold, `review` of them, stratified by 1-bit band. `previous`, the run folder's sheet
    before an increment: its open rows stay (carry_over), since the scores behind them aren't kept."""
    con, u, t = run.con, q(run.uid), run.pipeline.fs.min_match_weight
    fill = fill_rates(run, fields)
    l, r, lo = q(run.l), q(run.r), review_floor(run.pipeline)
    bands = con.sql(f"""SELECT floor(s.match_weight / 2) * 2 AS weight_from, count(*) AS pairs, count(m.{l}) AS accepted
                        FROM scores s LEFT JOIN matches m USING ({l}, {r}) GROUP BY 1 ORDER BY 1""").df()
    sizes = con.sql("SELECT n AS cluster_size, count(*) AS clusters FROM (SELECT count(*) AS n FROM gold GROUP BY cluster_id) GROUP BY 1 ORDER BY 1").df()
    largest = con.sql("SELECT cluster_id, count(*) AS records FROM gold GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10").df()
    con.execute(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
    decide = con.sql(f"""SELECT * EXCLUDE (k1, k2) FROM (
            SELECT s.*, c.sources, least(ga.cluster_id, gb.cluster_id) AS k1, greatest(ga.cluster_id, gb.cluster_id) AS k2
            FROM scores s JOIN cands c USING ({l}, {r}) JOIN gold ga ON ga.{u} = s.{l} JOIN gold gb ON gb.{u} = s.{r}
            WHERE s.match_weight >= {lo} AND (s.match_weight < {t} OR NOT {named_sql(run.pipeline.fs)}) AND ga.cluster_id <> gb.cluster_id
              AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r}))
        QUALIFY row_number() OVER (PARTITION BY k1, k2 ORDER BY match_weight DESC, {l}, {r}) = 1
        ORDER BY match_weight DESC, {l}, {r}""").df().assign(why="decide")
    audit = con.sql(f"""SELECT * EXCLUDE (k) FROM (SELECT s.*, m.sources, row_number() OVER (PARTITION BY floor(s.match_weight) ORDER BY hash(s.{l}, s.{r})) AS k
                        FROM matches m JOIN scores s USING ({l}, {r}) WHERE s.match_weight < {t + 4})
                        WHERE k <= {max(1, review // 4)} ORDER BY match_weight, {l}, {r}""").df().assign(why="audit")
    steps = pd.DataFrame(run.steps)
    base = ["step", "big_o", "filled", "seconds", "peak_memory_gb"]
    steps = steps[base].assign(facts=steps.drop(columns=base).apply(lambda r: " · ".join(
        f"{k} {v:,.0f}" if float(v).is_integer() else f"{k} {v:,.2f}" for k, v in r.dropna().items()), axis=1))
    coverage = pattern_coverage(run.pipeline.fs, run.scoring, run.n)
    sheet = review_sheet(run, pd.concat([decide, audit], ignore_index=True))
    if previous is not None and previous.exists():
        sheet = carry_over(run, pd.read_parquet(previous), sheet, previous.parent)
    decide = sheet[sheet["why"] == "decide"]
    queue = pd.DataFrame(dict(why=["decide", "audit"], pairs=[len(decide), len(audit)], from_bits=[lo, t], below_bits=[t, t + 4]))
    fs, aside = run.pipeline.fs, run._count("set_aside")
    total, entities, biggest, by_rules, by_model, by_people = con.execute(f"""SELECT count(*), count(DISTINCT cluster_id), max(n),
        count(*) FILTER (WHERE resolved_stage = '{fs.previous_stage}'), count(*) FILTER (WHERE resolved_stage = '{fs.stage}'),
        count(*) FILTER (WHERE resolved_stage = 'review') FROM gold JOIN (SELECT cluster_id, count(*) AS n FROM gold GROUP BY 1) USING (cluster_id)""").fetchall()[0]
    linked = next(x for x in reversed(run.steps) if x["step"] == "cluster")
    kinds, mixed, kind_rows = pd.DataFrame(), pd.DataFrame(), []
    if "kind" in con.sql("DESCRIBE gold").df()["column_name"].tolist():
        kinds = con.sql("""SELECT 'records' AS of, kind, count(*) AS how_many FROM gold GROUP BY ALL
                           UNION ALL SELECT 'customers', customer_kind, count(DISTINCT cluster_id) FROM gold GROUP BY ALL ORDER BY ALL""").df()
        mixed = con.sql("""SELECT cluster_id, count(*) AS records, count(*) FILTER (WHERE kind = 2) AS companies,
                                  count(*) FILTER (WHERE kind = 1) AS persons FROM gold GROUP BY 1
                           HAVING companies > 0 AND persons > 0 ORDER BY records DESC, cluster_id""").df()
        n = {(x.of, x.kind): x.how_many for x in kinds.itertuples()}
        kind_rows = [("kinds", " · ".join(f"{n.get((of, k), 0):,} × {SAYS[k]}" for k in (COMPANY, PERSON, UNSURE)) + f" ({of})")
                     for of in ("records", "customers")]
        c = run.classifier
        if c is not None and c.spec.trust_flag:
            how = "the file's flag, as it is (trust_flag)"
        elif c is not None and c.combiner is not None:
            side = lambda line, at: at if line <= 1 else "never (no line holds its budget)"
            how = (f"{c.labels:,} answers ({c.measured:,} drawn to measure): company {side(c.line_company, f'at P ≥ {c.line_company:g}')}, "
                   f"person {side(c.line_person, f'at P ≤ {1 - c.line_person:.4g}, its labelled error {c.person_error:.2%}' if c.person_error is not None else '')}")
        else:  # no line placed: a written legal form decides
            how = ((f"{c.labels:,} answers, {c.measured:,} of them drawn to measure: a line needs 50 drawn to measure, of both kinds"
                    if c is not None and c.labels else "no answers yet")
                   + "; 2 company only where a legal form is written; answer kind_review.parquet, then run again with --kind-labels")
        if c is not None and c.decided:
            how += f"; people decided {len(c.decided):,} records"
        held, unknown = con.execute("SELECT count(*) FILTER (WHERE kind_held AND kind_by <> 'people'), count(*) FILTER (WHERE kind_held AND kind_by = 'people') FROM gold").fetchall()[0]
        if held:
            kind_rows.append(("held back", f"{held:,} records from matching: the engine and the flag disagree; decide them in kind_review.parquet"))
        if unknown:
            kind_rows.append(("held back", f"{unknown:,} records people can't tell: their names stay out of matching, and their pairs come to review.parquet"))
        if c is not None and c.flag_error is not None:
            how += f"; the flag wrong on {c.flag_error:.1%} of {c.flag_checked:,} answers drawn at random"
        kind_rows += [("kinds from", how)] if c is not None else []
        if c is not None and not c.spec.trust_flag and "kind_flag" in run._columns():  # the flag's likely errors, for its owners
            says = "x.kind_flag IN (" + ", ".join(f"'{v}'" for v in c.flag_company) + ")"
            a, b = con.execute(f"""SELECT count(*) FILTER (WHERE g.kind = 2 AND NOT {says}), count(*) FILTER (WHERE g.kind = 1 AND {says})
                                   FROM gold g JOIN records x USING ({u}) WHERE x.kind_flag IS NOT NULL""").fetchall()[0]
            kind_rows.append(("flag", f"a sure kind contradicts it on {a + b:,} records: {a:,} sure 2 company flagged 1, "
                                      f"{b:,} sure 1 person flagged 2 (sent to decide in kind_review.parquet)"))
        if len(mixed):
            kind_rows.append(("note", f"{len(mixed):,} cluster{'s hold' if len(mixed) > 1 else ' holds'} a sure person and a sure company: see qa.md, mixed kinds"))
    summary = pd.DataFrame([
        ("records", f"{total:,}" + (f", {run.added:,} of them new" if run.added is not None else "") + (f"; {aside:,} set aside (set_aside/)" if aside else "")),
        ("entities", f"{entities:,}; the largest holds {biggest:,} records"),
        ("joined by", f"the rules {by_rules:,} · the model {by_model:,} · people {by_people:,} records"),
        ("model links", f"{linked['accepted']:,}{' in this batch' if run.added is not None else ''}; about {linked['expected_false']:,.{1 if linked['expected_false'] >= 1 else 2}f} "
                        "of them false, as the model expects (the sum of 1 − match probability)"),
        ("to decide", f"{len(decide):,} pair{'' if len(decide) == 1 else 's'} in review.parquet (why = decide)"),
        *kind_rows,
        *(("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.loc[fill["flag"] != "", ["field", "filled"]].itertuples(index=False)),
        *(("note", f"turned off, a field it reads is missing: {d}") for d in run.disabled),
        *(("note", note) for note in run.notes),
        *(("example", x) for x in run.examples)], columns=["what", "value"])
    return dict(summary=summary, fill=fill, disabled=pd.DataFrame({"disabled": run.disabled}), steps=steps, weight_bands=bands,
                cluster_sizes=sizes, largest_clusters=largest, patterns_without_a_key=coverage.head(20), review=queue,
                kinds=kinds, mixed_kinds=mixed,
                oversized_blocks=run.gated,
                review_sheet=sheet)



def report_text(run: "Run", tables: dict[str, pd.DataFrame], pipeline: Path) -> str:
    """The run on a page of plain text that holds no record's value (no ID, name, phone or address: the notes that
    quote one are run.examples, in qa.md only), so it can leave the machine that holds the records. `tables` is qa()'s.
    It shows what ran (the code, the tracked files changed in this copy, the pipeline, the machine's limits), the
    summary, each field's fill and shape, scores and accepted links by weight with the false links the model expects,
    cluster sizes, each step's time and memory, the model (the prior, and m, u and bits per level), the costliest
    blocks, and the patterns no key pairs. O(C + E) over scores and matches."""
    con, fs = run.con, run.pipeline.fs
    t, lo = fs.min_match_weight, review_floor(run.pipeline)

    def table(df: pd.DataFrame) -> list[str]:  # numbers right-aligned, text left, so the page stays narrow
        if not len(df):
            return ["  none"]
        rows = [list(map(str, df.columns)), *([str(v) for v in r] for r in df.itertuples(index=False))]
        width = [max(len(r[i]) for r in rows) for i in range(len(df.columns))]
        number = [all(re.fullmatch(r"[-+]?[\d,.]+(%|e[-+]\d+)?|—", r[i]) for r in rows[1:]) for i in range(len(df.columns))]
        return ["  " + "  ".join(v.rjust(w) if n else v.ljust(w) for v, w, n in zip(r, width, number)).rstrip() for r in rows]

    def pct(x: object) -> str:
        return "—" if x is None or pd.isna(x) else f"{x:.1%}"

    code = code_version(run.settings.root)
    threads, memory = con.execute("SELECT current_setting('threads'), current_setting('memory_limit')").fetchall()[0]
    kind = "full run" if run.added is None else f"increment of {run.added:,} new records"
    out = [f"RUN REPORT · {datetime.now():%Y-%m-%d %H:%M} · {kind} · no record's value in it",
           f"code {code} · pipeline {pipeline.name}",
           f"python {platform.python_version()} · duckdb {duckdb.__version__} · splink {version('splink')} · {platform.system()} {platform.machine()}",
           f"{threads} threads · memory limit {memory} · spill room {run.spill_room() / 1e9:,.0f} GB · "
           f"took {sum(x['seconds'] for x in run.steps):,.1f} s · peak {max(x['peak_memory_gb'] for x in run.steps):.2f} GB", ""]

    summary = tables["summary"][tables["summary"]["what"] != "example"]
    out += ["SUMMARY", *(f"  {what:<12} {value}" for what, value in summary.itertuples(index=False)), ""]

    fill = tables["fill"]
    out += ["FIELDS  (looks right, top value: on a sample of 10,000 records)", *table(pd.DataFrame(dict(
        field=fill["field"], filled=fill["filled"].map(pct), looks_right=fill["looks_right"].map(pct), top_value=fill["top_value"].map(pct),
        columns=[sources_text(run.present.get(f)) for f in fill["field"]]))), ""]

    edges = sorted({-20, -10, 0, lo, t, t + 2, t + 4, t + 8, t + 12})
    band = "CASE " + " ".join(f"WHEN match_weight < {b} THEN {i}" for i, b in enumerate(edges)) + f" ELSE {len(edges)} END"
    scored = dict(con.execute(f"SELECT {band}, count(*) FROM scores GROUP BY 1").fetchall())
    accepted = {k: (n, x) for k, n, x in con.execute(f"SELECT {band}, count(*), sum(1 - match_probability) FROM matches GROUP BY 1").fetchall()}
    label = lambda i: f"below {edges[0]:g}" if i == 0 else f"{edges[-1]:g} and up" if i == len(edges) else f"{edges[i - 1]:g} to {edges[i]:g}"
    out += [f"SCORES  (bits; review from {lo:g}, accept from {t:g}; expected false = the sum of 1 − match probability)", *table(pd.DataFrame(
        [dict(bits=label(i), candidates=f"{scored[i]:,}", accepted=f"{accepted.get(i, (0, 0))[0]:,}", expected_false=f"{accepted.get(i, (0, 0))[1]:.2f}")
         for i in sorted(scored)])), ""]

    sizes = tables["cluster_sizes"]
    by = pd.cut(sizes["cluster_size"], [0, 1, 2, 3, 4, 9, 49, np.inf], labels=["1", "2", "3", "4", "5–9", "10–49", "50+"])
    out += ["CLUSTERS  (size: how many)", "  " + " · ".join(f"{k}: {v:,}" for k, v in sizes.groupby(by, observed=True)["clusters"].sum().items()), ""]

    steps = tables["steps"]
    out += ["STEPS", *table(steps[["step", "seconds", "peak_memory_gb", "facts"]].rename(columns={"peak_memory_gb": "peak_gb"})), ""]

    lam, m = scaled_prior(run.scoring, run.n), run.scoring["er"]
    params = parameters(run.scoring)
    out += [f"MODEL  (prior {math.log2(lam / (1 - lam)):.2f} bits at {run.n:,} records; fitted on {m['fit_rows']:,} records"
            + (f"; learned nothing about {', '.join(m['skipped'])}" if m.get("skipped") else "") + ")", *table(pd.DataFrame(dict(
                comparison=params["comparison"], level=params["level"], m=params["m"].map(lambda x: f"{x:.4f}" if x >= 1e-3 else f"{x:.2e}"),
                u=params["u"].map(lambda x: f"{x:.2e}"), bits=params["weight"].map(lambda x: f"{x:.2f}")))), ""]

    plan = getattr(run, "plan", None)  # the budget runs before a full run only
    if plan is not None:
        shown = plan[(plan["oversized_blocks"] > 0) | plan["name"].isin(plan.nlargest(6, "per_record")["name"])].sort_values("per_record", ascending=False)
        out += [f"BLOCKS  ({int(plan['est_pairs'].sum()):,} pairs before dedupe; room for {run.capacity():,})", *table(pd.DataFrame(dict(
            kind=shown["kind"], name=shown["name"], per_record=shown["per_record"].map(lambda x: f"{x:.2f}"),
            largest=shown["largest_block"].map(lambda x: f"{x:,}"), oversized=shown["oversized_blocks"].map(lambda x: f"{x:,}")))), ""]

    patterns = tables["patterns_without_a_key"].head(5)
    out += ["PATTERNS WITHOUT A KEY  (they reach the threshold, but no key is sure to pair them; share of matches, at most)",
            *table(patterns.assign(bits=patterns["bits"].map(lambda x: f"{x:.2f}"), share_of_matches=patterns["share_of_matches"].map(lambda x: f"{x:.3%}")))]
    return "\n".join(out) + "\n"

def carry_over(run: "Run", previous: pd.DataFrame, sheet: pd.DataFrame, out: Path) -> pd.DataFrame:
    """The open review queue across increments: the previous sheet's decide rows that nobody gave back yet (none in
    decisions/) and whose records are still in different clusters, or that hold a decision typed in but not given back,
    with this run's new rows; this run's audit rows only. O(previous rows)."""
    l, r, u = q(run.l), q(run.r), q(run.uid)
    prev = previous[previous["why"] == "decide"] if "why" in previous else previous.iloc[:0]  # a sheet from before the queue: nothing to keep
    if prev.empty:
        return sheet
    run.con.register("er_prev", prev[[run.l, run.r, "decision"]])
    stored = (f"SELECT {l}, {r} FROM read_parquet({lit(out / DECISIONS / 'part-*.parquet')})"
              if any((out / DECISIONS).glob("part-*.parquet")) else f"SELECT NULL AS {l}, NULL AS {r} WHERE FALSE")
    keep = run.con.execute(f"""SELECT p.{l}, p.{r} FROM er_prev p JOIN gold a ON a.{u} = p.{l} JOIN gold b ON b.{u} = p.{r}
        WHERE (p.decision IS NOT NULL OR a.cluster_id <> b.cluster_id)
          AND NOT EXISTS (SELECT 1 FROM ({stored}) d WHERE d.{l} = p.{l} AND d.{r} = p.{r})""").df()
    run.con.unregister("er_prev")
    kept = prev.merge(keep, on=[run.l, run.r])
    new = sheet[(sheet["why"] == "decide") & ~sheet.set_index([run.l, run.r]).index.isin(kept.set_index([run.l, run.r]).index)]
    decide = pd.concat([new, kept[sheet.columns]], ignore_index=True).sort_values("match_weight", ascending=False, ignore_index=True)
    return pd.concat([decide, sheet[sheet["why"] == "audit"]], ignore_index=True)


def review_sheet(run: "Run", pairs: pd.DataFrame) -> pd.DataFrame:
    """Scored pairs as people judge them, in the order given: both records' compared fields side by side, and per
    comparison the level the pair landed in and the bits it earned, which with the prior sum to its weight; whether the
    run accepted it (in matches); an empty `decision` for people to fill in (match or no_match) and give to Run.decide. O(pairs)."""
    comps, uid = run.pipeline.fs.model.comparisons, run.uid
    fields = [f for f in dict.fromkeys(col for c in comps for col in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of)))
              if f in run._columns()]
    run.con.register("er_review_ids", pd.DataFrame({uid: pd.concat([pairs[run.l], pairs[run.r]]).unique()}))
    records = run.con.sql(f"SELECT {', '.join(q(c) for c in [uid, *fields])} FROM records JOIN er_review_ids USING ({q(uid)})").df()
    run.con.unregister("er_review_ids")
    run.con.register("er_review_pairs", pairs[[run.l, run.r]])
    accepted = run.con.sql(f"SELECT p.*, m.{q(run.l)} IS NOT NULL AS accepted FROM er_review_pairs p LEFT JOIN matches m USING ({q(run.l)}, {q(run.r)})").df()
    run.con.unregister("er_review_pairs")
    out = pairs.merge(accepted, on=[run.l, run.r]).merge(records.add_suffix("_l"), on=run.l).merge(records.add_suffix("_r"), on=run.r)
    out["decision"] = pd.Series(pd.NA, index=out.index, dtype="string")
    by_gamma = levels(run.scoring)
    for c in comps:
        gamma = out.pop(f"gamma_{c.name}").astype(int)
        out[c.name] = gamma.map(lambda g: by_gamma[c.name][g][0])
        out[f"{c.name}_bits"] = gamma.map(lambda g: round(by_gamma[c.name][g][1], 2))
    return out[[*(["why"] if "why" in out else []), "decision", run.l, run.r, "match_weight", "match_probability", "accepted", "sources",
                *(f"{f}_{side}" for f in fields for side in ("l", "r")), *(x for c in comps for x in (c.name, f"{c.name}_bits"))]
               ].reset_index(drop=True)

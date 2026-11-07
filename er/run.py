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
one is complete. A workspace takes one writer at a time (run_lock): a full run, an increment or a set of decisions holds
it for as long as it writes.

N records, L characters per value, P pairs in a rule's or generator's key blocks, C candidates, K comparisons,
S sampled pairs for u, E accepted pairs, d cluster diameter (Splink's connected components take up to d rounds, over
the edges' records only: each existing cluster is one node, see er.cluster.merge).
"""
import functools
import json
import os
import re
import resource
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import pandas as pd

from er import folder
from er.candidates import candidates, estimate, q
from er.cluster import merge
from er.config import InputError, Pipeline
from er.io import code_version, config_hash, markdown
from er.kind import NAME_MODEL, classifier as kind_classifier, kind_review_sheet, merge_answers
from er.match import ELSE, named_sql, refreshed_u, review_floor, rule_edges, score_fs, scored_u, train_fs, u_basis
from er.report import applied, qa, report_text, review_sheet, scored_again
from er.settings import SPECIAL, Settings, fit_to_file, present_fields
from er.source import answers, decisions, file_facts, known, lit, open_source, suggest
from er.standardize import prepare
from er.strings import connect


def peak_gb() -> float:  # the process's peak resident memory so far (ru_maxrss: bytes on macOS, KB on Linux)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)


BYTES_PER_PAIR = 350  # shortcut: measured at 1M (candidate and score tables held together); measure again if those tables change


def locked(method: Callable) -> Callable:  # the workspace (the method's `out`) locked for the whole method
    @functools.wraps(method)
    def wrapper(self: "Run", path: str | Path, out: Path, *args: object, **kwargs: object) -> object:
        with folder.run_lock(Path(out)):
            return method(self, path, Path(out), *args, **kwargs)
    return wrapper


def size_bytes(text: str) -> int:  # one of DuckDB's sizes: "8.0 GiB", "512.0 MiB", "1.5 GB"
    num, unit = re.match(r"([\d.]+)\s*([A-Za-z]*)", text).groups()
    scale = {"": 1, "b": 1, "bytes": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40}
    return int(float(num) * scale[unit.lower()])


@dataclass
class Run:
    pipeline: Pipeline                        # the chosen pipeline; fitted to the file by load()
    settings: Settings
    model: dict | None = None                 # a fitted model (Splink JSON from train_fs); None: fit on this file
    chunk_rows: int = 200_000
    steps: list[dict] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    echo: Callable[[dict], None] | None = None  # called with each step as it finishes: progress for people (nayose)
    kind_labels: Path | None = None           # people's person/company labels (a filled-in kind_review.parquet); an increment keeps the run's

    def __post_init__(self) -> None:
        self.con, self.db = connect(self.settings.compute)
        self.uid = self.settings.data.unique_id
        self.l, self.r = f"{self.uid}_l", f"{self.uid}_r"
        self.notes: list[str] = []            # what the loader detected or fixed, for the run's summary; never a record's value
        self.examples: list[str] = []         # notes that quote a record's value: the summary and qa.md show them, report.txt doesn't
        self.added: int | None = None         # an increment's new records (0: nothing new)
        self.part = 0                         # the part an increment writes: one past the run's highest
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
        self.config = run_config(self.pipeline, self.settings)
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
        self.notes, self.inputs = list(src.notes), file_facts(src.files, "records")
        present = self.present = present_fields(self.settings, src.columns)
        hints = suggest(src, self.con, [f for f in self.settings.columns if f not in present and f != "entity"], self.settings.detect)
        try:
            self.pipeline, self.disabled = fit_to_file(self.pipeline, self.settings, src.columns)
        except InputError as e:
            raise InputError(f"{e}. The file's columns: {', '.join(src.columns)}", e.fix + (
                ". Suggested from the file's values, check them first:\n  [columns]" + "".join(
                    f"\n  {f} = \"{c}\"   # {why}" for f, (c, _, why) in hints.items()) if hints else ""),
                hints={f: c for f, (c, _, _) in hints.items()}) from None
        self.notes += [f"no column for {f}; {c} may be it ({why})" for f, (c, share, why) in hints.items() if share > 0.5]
        if self.model is not None:  # a given model must compare exactly what this file's fields let the pipeline compare
            fitted = {(c["output_column_name"], lv["label_for_charts"]) for c in self.model["comparisons"]
                      for lv in c["comparison_levels"] if not lv.get("is_null_level")}
            here = {(c.name, label) for c in self.pipeline.fs.model.comparisons for label in (*(lv.label for lv in c.levels), ELSE)}
            if fitted != here:
                raise InputError(f"{path}: the model was fitted on other comparison levels (only in the model: {sorted(fitted - here)}; "
                                 f"only here: {sorted(here - fitted)})", fix="run without --model: the run then fits its model on this file")
        rows = self._set_aside(src.sql, stored, src.ordered)
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
            if self.given is not None and len(self.given):  # each answer names a record of this file
                self.con.register("er_given_ids", self.given[[self.uid]])
                known(self.con, f"SELECT {q(self.uid)} AS id FROM er_given_ids", rows, self.uid, self.kind_labels, path)
                self.con.unregister("er_given_ids")
            self.inputs += file_facts([self.settings.root / NAME_MODEL], "name model") + file_facts([self.kind_labels] if self.kind_labels else [], "answers")
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

    def _set_aside(self, src: str, stored: str | None, ordered: bool = False) -> str:
        """The records a run can resolve. Rows identical in every column are kept once. Set aside, with the reason, in
        the table set_aside (written to set_aside/, to be fixed and added by an increment): a record without an ID;
        every record of an ID that holds different content; with `stored` (an increment), a record already in the run.
        `ordered` (files read in order, er_file: a rerun) sets aside as an increment would have: an ID's records stand
        from the first file that holds it once, earlier ones held different content, later ones were already in the
        run. O(N) to count; the rest only when something is off."""
        u = q(self.uid)
        blank, known = f"nullif(trim({u}), '') IS NULL", f"{u} IN (SELECT {u} FROM {stored})" if stored else "FALSE"
        if ordered:
            return self._set_aside_in_order(src, blank)
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

    def _set_aside_in_order(self, src: str, blank: str) -> str:
        """_set_aside on files read in order: per ID, the first file holding it exactly once (er_first); within a file,
        rows identical in every column are kept once. O(N)."""
        u = q(self.uid)
        n = self._count(src)
        if n and not self._count(f"{src} WHERE NOT ({blank})"):
            raise InputError(f"no record has an ID in column {self.uid}", fix="map id in config/settings.toml [columns] to the column holding each record's ID")
        self.con.execute(f"""CREATE OR REPLACE TABLE er_in AS WITH d AS (SELECT DISTINCT * FROM {src}),
            once AS (SELECT {u}, min(er_file) AS er_first FROM (SELECT {u}, er_file FROM d WHERE NOT ({blank}) GROUP BY ALL HAVING count(*) = 1) GROUP BY 1)
            SELECT d.*, once.er_first FROM d LEFT JOIN once USING ({u})""")
        if (kept := self._count("er_in")) < n:
            self.notes.append(f"{n - kept:,} rows identical to another in every column, kept once")
        keep = f"NOT ({blank}) AND coalesce(er_file = er_first, FALSE)"
        self.con.execute(f"""CREATE OR REPLACE TABLE set_aside AS SELECT * EXCLUDE (er_file, er_first), CASE WHEN {blank} THEN 'no ID'
            WHEN er_file > er_first THEN 'already in the run' ELSE 'the same ID with different content' END AS reason FROM er_in WHERE NOT ({keep})""")
        self.notes += [f"{k:,} records set aside: {reason}" for reason, k in
                       self.con.execute("SELECT reason, count(*) FROM set_aside GROUP BY 1 ORDER BY 1").fetchall()]
        return f"(SELECT * EXCLUDE (er_file, er_first) FROM er_in WHERE {keep})"

    def budget(self) -> pd.DataFrame:
        """Exact block sizes on this file, per rule and generator, by group-by, before any join: pairs, pairs per record,
        the largest block, and the oversized blocks (budget.min_oversized() records or more). Those are never joined
        blind: a generator checks each on a sample first (er.candidates), and a rule never trusts their values
        (_untrusted). The run stops only if the pairs of the normal blocks alone would not fit (capacity)."""
        t, rows = time.perf_counter(), []
        m = self.pipeline.fs.budget.min_oversized()
        rules = self.pipeline.rules.blockers()
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
            area = q("postal_code__first3") if "postal_code__first3" in self.columns() else None
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

    def columns(self) -> set[str]:  # the records table's columns
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
        for i, st, rule in rules.each():
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
                   oversized_skipped=int(self.gated.get("decision", pd.Series(dtype=str)).str.startswith("skipped").sum()),
                   generators=listed(report))
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
        reached: dict[str, dict[str, int]] = {}  # per comparison, the pairs at each level (gamma, as score_fs gives it): one scan
        for c, g, n in self.con.execute("SELECT c, g, count(*) FROM (UNPIVOT scores ON COLUMNS('^gamma_') INTO NAME c VALUE g) GROUP BY ALL").fetchall():
            reached.setdefault(c.removeprefix("gamma_"), {})[str(g)] = n
        self._done("score", "O(C·K·L²)", f"O({self._count('scores'):,}·{k}·L²)", t, reached=reached)

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
        loaded by full() from the workspace; empty otherwise)."""
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
        order = " ".join(f"WHEN '{rule.name}' THEN {i}" for i, _, rule in self.pipeline.rules.each())
        stage = f"CASE WHEN rz.n > 1 THEN '{fs.previous_stage}' WHEN m.id IS NOT NULL THEN '{fs.stage}' WHEN z.n > 1 THEN 'review' END"
        by = f"CASE WHEN rz.n > 1 THEN f.rule WHEN m.id IS NOT NULL THEN '{fs.model.name}' WHEN z.n > 1 THEN 'review' END"
        if old:
            stage, by = f"coalesce(o.resolved_stage, {stage})", f"coalesce(o.resolved_by, {by})"
        kinds = "kind" in self.columns()  # each record's kind, and its customer's (customer_kinds)
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
        sheets, n = [], folder.next_part(out / folder.KIND_ANSWERS)
        if n == 0 and (old := out / folder.OLD_ANSWERS).exists():  # a folder that keeps its answers in state/: its first sheet
            sheets, n = [(f"SELECT * FROM read_parquet({lit(old)})", out / folder.KIND_ANSWERS / "part-00000.parquet")], 1
        if self.given is not None and len(self.given):  # the sheet given, kept as it came: the next run reads it again
            self.con.register("er_given", self.given)
            sheets.append(("SELECT * FROM er_given", out / folder.KIND_ANSWERS / f"part-{n:05d}.parquet"))
        folder.stage(self.con, out, [("SELECT * FROM rule_kept", out / "rule_kept" / name), ("SELECT * FROM matches", out / "matches" / name),
                                     (f"SELECT * FROM gold ORDER BY {q(self.uid)}", out / "gold.parquet"),
                                     ("SELECT * FROM rule_clusters", state / "rule_clusters.parquet"),
                                     (f"SELECT * FROM {'records' if part == 0 else 'new_records'}", state / "records" / name), *aside, *sheets],
                     texts + people, replace, frames)
        self._done("write", "O(N + C)", f"O({self.n:,} + {self._count('matches'):,})", t)
        self._log(out, part > 0, part=part, disabled=self.disabled)
        if part == 0:  # the round this method is in, and how it did
            linked = next(x for x in reversed(self.steps) if x["step"] == "cluster")
            folder.round_ran(out, dict(config=self.config, method=folder.method(out), at=datetime.now().isoformat(timespec="seconds"),
                                       matched=linked["accepted"], expected_false=linked["expected_false"]))

    def _log(self, out: Path, append: bool, **entry: object) -> None:
        """This run's entry in steps.json (folder.log): when, the code and config that ran, the files read with their
        SHA-256, and each step."""
        folder.log(out, dict(at=datetime.now().isoformat(timespec="seconds"), code=code_version(self.settings.root), config=self.config,
                             inputs=self.inputs, **entry, steps=self.steps), append)

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
        if self._join(path, out):
            self.write(out, self.part, report=(path, pipeline_file) if pipeline_file else None)
        return self

    @locked
    def match(self, path: str | Path, out: Path) -> pd.DataFrame:
        """Which entity each record of `path` would join in the run in `out`, and by what, writing nothing: the
        increment's steps without its write. One row per record read: its ID; `entity`, the cluster_id it would have;
        `status` (joins an entity, a new entity, already in the run, or set aside and why); `by`, the rule or `fs` that
        linked it most strongly, and `weight`, its best model link in bits. O(an increment) less its write."""
        u = q(self.uid)
        if self._join(path, out):
            self.con.execute(f"""CREATE OR REPLACE TABLE er_match AS WITH
                ends AS (SELECT {q(self.l)} AS id, rule, NULL::DOUBLE AS w FROM rule_kept UNION ALL SELECT {q(self.r)}, rule, NULL FROM rule_kept
                         UNION ALL SELECT {q(self.l)}, 'fs', match_weight FROM matches UNION ALL SELECT {q(self.r)}, 'fs', match_weight FROM matches),
                best AS (SELECT id, arg_max(rule, coalesce(w, 1e9)) AS by, max(w) AS weight FROM ends GROUP BY 1),
                old AS (SELECT DISTINCT g.cluster_id FROM gold g JOIN gold_old o USING ({u}))
                SELECT n.{u}, g.cluster_id AS entity, CASE WHEN g.cluster_id IN (SELECT cluster_id FROM old) THEN 'joins an entity'
                       ELSE 'a new entity' END AS status, b.by, b.weight
                FROM new_ids n JOIN gold g USING ({u}) LEFT JOIN best b ON b.id = n.{u}""")
        else:
            self.con.execute(f"CREATE OR REPLACE TABLE er_match AS SELECT {u}, NULL::VARCHAR AS entity, '' AS status, NULL::VARCHAR AS by, NULL::DOUBLE AS weight WHERE FALSE")
        return self.con.execute(f"""SELECT * FROM er_match UNION ALL BY NAME
            SELECT s.{u}, g.cluster_id AS entity, CASE WHEN s.reason = 'already in the run' THEN s.reason ELSE 'set aside: ' || s.reason END AS status
            FROM set_aside s LEFT JOIN read_parquet({lit(out / 'gold.parquet')}) g ON g.{u} = s.{u} AND s.reason = 'already in the run'
            ORDER BY 1""").df()

    def _join(self, path: str | Path, out: Path) -> bool:
        """The increment's steps on the batch at `path` against the run in `out`, up to its clusters (gold), writing
        nothing; False if every record is already in the run."""
        state, u, l, r = out / "state", q(self.uid), q(self.l), q(self.r)
        folder.finish_writes(out)
        if not (state / "model.json").exists():
            raise InputError(f"no run in {out} to add records to", fix="resolve records into that folder first: nayose resolve records …")
        if (state / "config.txt").exists() and (state / "config.txt").read_text(encoding="utf-8") != self.config:
            raise InputError(f"the pipeline or the column mapping changed since the full run in {out}: an increment would resolve its batch otherwise",
                             fix="resolve all of them again (nayose rerun records), or add these with the pipeline and config/settings.toml that run used")
        self.model = json.loads((state / "model.json").read_text(encoding="utf-8"))
        self.part = folder.next_part(state / "records")
        parts = ", ".join(lit(x) for x in sorted((state / "records").glob("part-*.parquet")))  # not a glob: this run's own part comes later
        self.con.execute(f"CREATE OR REPLACE VIEW old_records AS SELECT * FROM read_parquet([{parts}], union_by_name = true)")
        self.labels = self._answers(out)  # the batch's kinds rest on the run's answers, and any given with it
        self.load(path, into="new_records", stored="old_records")  # a record already in the run is set aside: a retry adds nothing twice
        self.added = self.n
        if not self.added:
            other = self.con.execute("SELECT count(*) FROM set_aside WHERE reason <> 'already in the run'").fetchall()[0][0]
            if other:
                raise InputError(f"{path}: no new record to add ({'; '.join(self.notes)})", fix="give the records set aside IDs, one per record")
            return False  # every record is already in the run: nothing to do
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
        self._done("candidates", "O(|Δ|·Σ b + scan)", f"{self._count('cands'):,} pairs touching the batch", t, generators=listed(report))

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
        return True

    def _answers(self, out: Path) -> pd.DataFrame | None:
        """People's person/company answers: the sheets the folder `out` keeps, newest first, then the one given on top.
        O(answers)."""
        parts = folder.answer_parts(out)
        kept = pd.concat([pd.read_parquet(f).astype({self.uid: "string"}) for f in parts], ignore_index=True) if parts else None
        return merge_answers(kept, self._given(), self.uid)

    def _given(self) -> pd.DataFrame | None:
        """The answered sheet given (kind_labels), through the door every input takes (er.source.answers): its answered
        rows, read once."""
        if self.kind_labels is not None and self.given is None:
            self.given = answers(self.kind_labels, self.con, self.uid)
        return self.given

    # ---------- people's decisions ----------

    def _load_decisions(self, out: Path | None) -> None:
        """The decisions stored in this workspace (None: none), on records of this file, the latest per pair, for _accept."""
        u, l, r, parts = q(self.uid), q(self.l), q(self.r), out / folder.DECISIONS if out else None
        if parts and any(parts.glob("part-*.parquet")):
            self.con.execute(f"""CREATE OR REPLACE TABLE er_decisions AS SELECT {l}, {r}, arg_max(decision, filename) AS decision
                FROM read_parquet({lit(parts / 'part-*.parquet')}, filename = true)
                WHERE {l} IN (SELECT {u} FROM records) AND {r} IN (SELECT {u} FROM records) GROUP BY {l}, {r}""")

    @locked
    def decide(self, path: str | Path, out: Path) -> "Run":
        """Apply people's decisions on review pairs (a Parquet file: uid_l, uid_r, decision) to the run in `out`,
        scoring nothing. Each `match` pair merges its two clusters, each cluster one node, and a record joined only this
        way is resolved by `review`. A `no_match` pair splits nothing here; every decision is stored in decisions/, with
        its why and the round it was made in (rounds.json), and a full run on this folder applies them again, never
        accepting a `no_match` pair. Rows without a decision are skipped, and so is a decision the folder already holds
        as its pair's latest: a sheet given twice changes nothing. O(D + touched clusters) + O(N) to rewrite gold."""
        t, u, l, r = time.perf_counter(), q(self.uid), q(self.l), q(self.r)
        folder.finish_writes(out)
        if not (out / "gold.parquet").exists():
            raise InputError(f"no run in {out} to apply decisions to", fix="resolve the records into that folder first: nayose resolve records …")
        self.con.execute(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM read_parquet({lit(out / 'gold.parquet')})")
        self.inputs = file_facts(decisions(path, self.con, self.l, self.r, into="er_decisions"), "decisions")  # the door: er.source checks them
        known(self.con, f"SELECT {l} AS id FROM er_decisions UNION SELECT {r} FROM er_decisions", "gold_old", self.uid, path, f"the run in {out}")
        if any((parts := out / folder.DECISIONS).glob("part-*.parquet")):
            self.con.execute(f"""DELETE FROM er_decisions d USING (SELECT {l}, {r}, arg_max(decision, filename) AS decision
                FROM read_parquet({lit(parts / 'part-*.parquet')}, filename = true) GROUP BY ALL) p
                WHERE p.{l} = d.{l} AND p.{r} = d.{r} AND p.decision = d.decision""")
        if not self._count("er_decisions"):
            self._done("decide", "O(D)", "O(0 new decisions)", t, decisions=0, matches=0, clusters_joined=0)
            return self
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
        parts = out / folder.DECISIONS
        parts.mkdir(exist_ok=True)
        folder.stage(self.con, out, [(f"SELECT * FROM gold ORDER BY {u}", out / "gold.parquet"),
                                     (f"SELECT *, {len(folder.rounds(out)) or 'NULL'}::INTEGER AS round FROM er_decisions",
                                      parts / f"part-{folder.next_part(parts):05d}.parquet")])
        self._log(out, True, decisions=str(path))
        return self

    def draw(self, out: Path, count: int) -> "Run":
        """`count` more audit rows on the review sheet of the run in `out`: links, the model's and the rules', that
        people have not decided and the sheet does not hold, spread evenly over 1-bit weight bands, a rule's pairs
        scored as the model would score them. Audits of every kind of link say how few false ones are left. Under the
        lock, and staged. O(N + (R + count)·K + E) + O(sheet)."""
        t, l, r, sheet = time.perf_counter(), q(self.l), q(self.r), out / "review.parquet"
        read = lambda name: f"read_parquet({lit(out / name)}, union_by_name = true)"
        with folder.run_lock(out):
            folder.finish_writes(out)
            if not sheet.exists():
                raise InputError(f"no review sheet in {out}", fix="find matches first: nayose resolve records --workspace …")
            self.con.execute(f"CREATE OR REPLACE TABLE er_rule AS SELECT {l}, {r}, min(rule) AS rule FROM {read('rule_kept/*.parquet')} GROUP BY ALL")
            scored_again(self.con, self.db, out, self.uid, "er_rule", "er_rule_scores")
            self.con.execute(f"""CREATE OR REPLACE TABLE matches AS SELECT {l}, {r}, match_weight, match_probability, sources FROM {read('matches/*.parquet')}
                UNION ALL SELECT x.{l}, x.{r}, s.match_weight, s.match_probability, x.rule FROM er_rule x JOIN er_rule_scores s USING ({l}, {r})
                WHERE NOT EXISTS (SELECT 1 FROM {read('matches/*.parquet')} m WHERE m.{l} = x.{l} AND m.{r} = x.{r})""")
            self.con.register("er_sheet", pd.read_parquet(sheet, columns=[self.l, self.r]))
            asked = [f"SELECT {l}, {r} FROM er_sheet"] + ([f"SELECT {l}, {r} FROM {read(folder.DECISIONS + '/part-*.parquet')}"]
                                                         if any((out / folder.DECISIONS).glob("part-*.parquet")) else [])
            self.con.execute(f"""CREATE OR REPLACE TABLE er_drawn AS SELECT {l}, {r} FROM (
                SELECT {l}, {r}, floor(match_weight) AS band, row_number() OVER (PARTITION BY floor(match_weight) ORDER BY hash({l}, {r})) AS k
                FROM matches m WHERE NOT EXISTS (SELECT 1 FROM ({' UNION ALL '.join(asked)}) a WHERE a.{l} = m.{l} AND a.{r} = m.{r}))
                ORDER BY k, band LIMIT {int(count)}""")
            drawn = self._count("er_drawn")
            if drawn:
                self.scoring = scored_again(self.con, self.db, out, self.uid, "er_drawn", "er_drawn_scores")
                self.con.execute("CREATE OR REPLACE TABLE records AS SELECT * FROM er_touched")  # what review_sheet shows of each record
                names = {c["output_column_name"] for c in self.scoring["comparisons"]}  # the comparisons the run could make
                m = self.pipeline.fs.model
                self.pipeline = replace(self.pipeline, fs=replace(self.pipeline.fs, model=replace(m, comparisons=tuple(c for c in m.comparisons if c.name in names))))
                pairs = self.con.execute(f"SELECT s.*, m.sources, 'audit' AS why FROM er_drawn_scores s JOIN matches m USING ({l}, {r}) ORDER BY s.match_weight").df()
                folder.stage(self.con, out, [], frames=[(pd.concat([pd.read_parquet(sheet), review_sheet(self, pairs)], ignore_index=True), sheet)])
        self._done("draw", "O(N + (R + count)·K + E)", f"O({self._count('er_rule'):,} rule pairs + {self._count('matches'):,} links)", t, drawn=drawn)
        return self

    @locked
    def full(self, path: str | Path, out: Path, overwrite: bool = False, pipeline_file: Path | None = None) -> "Run":
        """Steps 1–8 on the file at `path` into the workspace `out`; with `pipeline_file` (named in the reports), step 8
        writes step 9's reports with the run's files."""
        folder.finish_writes(out)
        held = folder.held(out)
        if held and not overwrite:
            raise InputError(f"{out} already holds a run", fix="choose another folder, or replace the run: nayose resolve records … --overwrite")
        self.labels = self._answers(out)  # read before the folder's old state goes
        self.resolve(path, out)
        self.write(out, replace=held, report=(path, pipeline_file) if pipeline_file else None)  # the old run goes only once the new one is complete
        return self

    def resolve(self, path: str | Path | list[Path], decided: Path | None) -> "Run":
        """Steps 1–7 on the file at `path`, writing nothing: each record's cluster (gold), with the decisions the
        workspace `decided` keeps (None: none). A trial of a method runs these alone (er.run.trial)."""
        self.load(path)
        self.budget()
        self.fit()
        self.rules()
        self.candidates()
        self.score()
        self._load_decisions(decided)
        self.cluster()
        return self

    def rerun(self, out: Path, pipeline_file: Path | None = None) -> "Run":
        """A full run again, on the record files the run in `out` read (folder.inputs): the full run's, then each
        increment's, in order, an ID's records set aside as the increments set them aside (_set_aside, ordered).
        People's decisions and answers stand, as on any full run of the folder. O(a full run) + O(bytes) to check the
        files."""
        out = Path(out)
        with folder.run_lock(out):  # the files named inside the lock: no increment lands between
            return self.full(folder.inputs(out), out, overwrite=True, pipeline_file=pipeline_file)


def run_config(p: Pipeline, s: Settings) -> str:  # what decides the answer: the pipeline and the settings that shape the records
    return config_hash((p, s.columns, s.standardize, s.flag_company))  # an increment needs the full run's


def trial(ws: Path, base: Pipeline, variant: Pipeline, method: dict, s: Settings, echo: Callable[[dict], None] | None = None) -> dict:
    """The workspace's method (`base`) and a variant of it (`method`, as method.toml would say it), each run on the
    workspace's files without people's decisions, so neither is judged on pairs it was told; both keep the run's
    fitted model and people's person/company answers. Compared on the pairs people decided (fixes: pairs the variant
    sets right that the base got wrong; breaks: the other way round), and without labels: links, the false ones the
    model expects, entities, and the pairs of records the variant puts apart or together. The base's clusters are
    kept for the next trial of the same method on the same files (trials/base.parquet); each trial's result in
    trials/<n>.json. Two trials of one workspace take turns. O(two full runs without the fit) + O(N + D)."""
    trials, uid = ws / folder.TRIALS, s.data.unique_id
    trials.mkdir(exist_ok=True)
    model, files = json.loads((ws / "state" / "model.json").read_text(encoding="utf-8")), folder.inputs(ws)

    def resolved(p: Pipeline) -> tuple[pd.DataFrame, dict]:  # each record's cluster, and the numbers people compare
        run = Run(p, s, model=model, echo=echo)
        run.labels = run._answers(ws)
        run.resolve(files, None)
        gold = run.con.execute(f"SELECT {q(uid)}, cluster_id FROM gold").df()
        numbers = dict(matched=run._count("matches"), expected_false=run._expected_false(), rule_pairs=run._count("rule_kept"),
                       entities=int(gold["cluster_id"].nunique()))
        run.con.close()
        return gold, numbers

    with folder.run_lock(trials):
        key = dict(config=run_config(base, s), files=[str(f) for f in files])
        kept = json.loads((trials / "base.json").read_text(encoding="utf-8")) if (trials / "base.json").exists() else {}
        if kept.get("key") == key and (trials / "base.parquet").exists():
            old, before = pd.read_parquet(trials / "base.parquet"), kept["numbers"]
        else:
            old, before = resolved(base)
            old.to_parquet(trials / "base.parquet", index=False)
            (trials / "base.json").write_text(json.dumps(dict(key=key, numbers=before)), encoding="utf-8")
        new, after = resolved(variant)
        l, r = f"{uid}_l", f"{uid}_r"
        decided = applied(ws, uid)
        same = (decided["decision"] == "match").to_numpy()
        together = lambda gold: (decided[l].map(gold.set_index(uid)["cluster_id"]) == decided[r].map(gold.set_index(uid)["cluster_id"])).to_numpy()
        was, now = together(old) == same, together(new) == same
        pairs = lambda rows: decided.loc[rows, [l, r, "decision"]].head(50).rename(columns={l: "id_l", r: "id_r"}).to_dict("records")
        both = old.merge(new, on=uid, suffixes=("_base", "_variant"))
        c2 = lambda sizes: int((sizes * (sizes - 1) // 2).sum())  # pairs of records inside clusters of these sizes
        kept_together = c2(both.groupby(["cluster_id_base", "cluster_id_variant"]).size())
        n = max((int(f.stem) for f in trials.glob("*.json") if f.stem.isdigit()), default=0) + 1
        result = dict(trial=n, at=datetime.now().isoformat(timespec="seconds"), method=method, base=before, variant=after,
                      fixes=int((now & ~was).sum()), breaks=int((was & ~now).sum()), fixed=pairs(now & ~was), broken=pairs(was & ~now),
                      apart=c2(both["cluster_id_base"].value_counts()) - kept_together, together=c2(both["cluster_id_variant"].value_counts()) - kept_together)
        (trials / f"{n}.json.tmp").write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(trials / f"{n}.json.tmp", trials / f"{n}.json")
        for f in trials.glob("*.json"):  # bounded: the last 5 trials
            if f.stem.isdigit() and int(f.stem) <= n - 5:
                f.unlink()
    return result


def listed(report: pd.DataFrame) -> list[dict]:  # each generator's pairs and seconds, kept in steps.json (describe matching)
    return [dict(name=r.generator, pairs=int(r.pairs), seconds=float(r.seconds)) for r in report.itertuples()]


def customer_kinds(clusters: str, kinds: str, u: str) -> str:
    """Each cluster's customer_kind, from its records' kind and kind_p (`kinds`: a table holding both): 2 company if any
    record surely is one; 1 person if no record leans company and one surely is a person; else 0 not sure. O(N)."""
    return f"""SELECT k.cluster_id, CASE WHEN bool_or(x.kind = 2) THEN 2 WHEN coalesce(max(x.kind_p), 0) < 0.5 AND bool_or(x.kind = 1)
               THEN 1 ELSE 0 END::TINYINT AS customer_kind FROM {clusters} k JOIN {kinds} x USING ({u}) GROUP BY 1"""

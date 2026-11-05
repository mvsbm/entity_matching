"""The run on any file of records, without labels: a chosen pipeline (config/final.toml) end to end on DuckDB tables,
so memory stays bounded at any size (past config/settings.toml [compute] memory_limit, DuckDB spills to disk). Each
step is a method of Run, called in order by full(), or one at a time by the demo notebook. Each records its Big-O,
with the numbers filled in, and its time.

    load        O(N·L)                           read through er.source (Parquet), check the fields, set aside what can't be
                                                 resolved, standardize each chunk → table records
    budget      O(N)                             exact block sizes per rule and generator, before any join; blocks of
                                                 64+ records flagged (a rule doesn't trust them; candidates sample them)
    fit         O(n + S·K + P_em·K)              λ, u and m by EM on a fixed-size sample of n records (or a fitted model)
    rules       O(N + Σ P_r·L²) + O((N + E)·d)   one join per rule (the first rule wins), then the rules' cascade
    candidates  O(N·L + Σ P_g)                   every generator; pairs inside one rule cluster dropped; a flagged block
                                                 joined only if a sample of its pairs reaches the review floor
    score       O(N + S·K) + O(C·K·L²)           u on this file, then every candidate scored
    cluster     O(C + (N + E)·d)                 accept at the threshold, then cluster with the rules' pairs
    write       O(N + C)                         gold clusters and matches, as Parquet; the state for increments

increment() adds a batch Δ of new records to a written run: the batch is joined against all records, rule by rule and
generator by generator, scored, and merged into the existing clusters, each cluster one node. Its cost is
O(|Δ|·(L + Σ b) + C_Δ·K·L²) plus narrow O(N) scans (the stored key columns, the exact u counts, gold rewritten),
whatever N; b is a block's size, C_Δ the pairs touching the batch. It keeps the stored model, and samples u again
only for a comparison whose drift has outgrown its sampling error (er.match.refreshed_u). A full run re-fits and
re-scores everything.

decide() applies people's decisions on the review sheet (qa) without scoring anything: a `match` pair merges two
clusters. Decisions are kept in decisions/, which a full run on the same folder applies again.

Writes are staged: every file is written under a temporary name; once all are complete, the list of renames still owed
is saved (pending.json), then they are done. A write interrupted before that list exists left the run as it was: run the
batch again. One interrupted after it is finished by the next increment (finish_writes). A full run refuses a folder that
already holds a run unless told to overwrite it. A run folder takes one writer at a time (run_lock): a full run, an
increment or a set of decisions holds it for as long as it writes.

N records, L characters per value, P pairs in a rule's or generator's key blocks, C candidates, K comparisons,
S sampled pairs for u, E accepted pairs, d cluster diameter (Splink's connected components take up to d rounds).
"""
import fcntl
import functools
import json
import os
import re
import resource
import shutil
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd
from splink.clustering import cluster_pairwise_predictions_at_threshold

from er.candidates import candidates, estimate, q
from er.config import InputError, Key, KeyBlocker, Pipeline
from er.match import ELSE, assemble_u, exact_u, levels, refreshed_u, rule_edges_table, score_fs, scored_sample, train_fs, u_basis
from er.pipeline import pattern_coverage
from er.settings import Settings, fit_to_file, present_fields
from er.source import lit, open_source, suggest
from er.standardize import prepare
from er.strings import connect


def peak_gb() -> float:  # the process's peak resident memory so far (ru_maxrss: bytes on macOS, KB on Linux)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)


BYTES_PER_PAIR = 350  # shortcut: measured at 1M (candidate and score tables held together); measure again if those tables change
PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
RUN_FILES = ("gold.parquet", "steps.json", PENDING, "matches", "rule_kept", "state", "set_aside")  # what a run writes in its folder
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them


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
            raise InputError(f"another job is writing to {out}", fix="wait for it to finish: a run folder takes one writer at a time") from None
        yield


def locked(method: Callable) -> Callable:  # the run folder (the method's `out`) locked for the whole method
    @functools.wraps(method)
    def wrapper(self: "Run", path: str | Path, out: Path, *args: object, **kwargs: object) -> "Run":
        with run_lock(Path(out)):
            return method(self, path, Path(out), *args, **kwargs)
    return wrapper


def size_bytes(text: str) -> int:  # one of DuckDB's sizes: "8.0 GiB", "512.0 MiB", "1.5 GB"
    num, unit = re.match(r"([\d.]+)\s*([A-Za-z]*)", text).groups()
    scale = {"": 1, "b": 1, "bytes": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12, "kib": 2**10, "mib": 2**20, "gib": 2**30, "tib": 2**40}
    return int(float(num) * scale[unit.lower()])


def finish_writes(out: Path) -> None:
    """Complete the renames of a write that was interrupted after its new files were complete; nothing otherwise."""
    pending = out / PENDING
    if pending.exists():
        for tmp, dest in json.loads(pending.read_text(encoding="utf-8")):
            if os.path.exists(tmp):
                os.replace(tmp, dest)
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

    def __post_init__(self) -> None:
        self.con, self.db = connect(self.settings.compute)
        self.uid = self.settings.data.unique_id
        self.l, self.r = f"{self.uid}_l", f"{self.uid}_r"
        self.notes: list[str] = []            # what the loader detected or fixed, for the run's summary
        self.added: int | None = None         # an increment's new records (0: nothing new)
        self.gated = pd.DataFrame()           # the oversized blocks the candidates checked, and what was decided
        self.rule_names = [rule.name for st in self.pipeline.rules.stages for rule in st.rules]

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
        self.notes = list(src.notes)
        present = present_fields(self.settings, src.columns)
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
        fs, rules = self.pipeline.fs, self.pipeline.rules
        normalized, used = [*rules.normalized(), *fs.normalized()], rules.used() | fs.used()
        reader = self.con.cursor().sql(f"SELECT * FROM {rows}").to_arrow_reader(self.chunk_rows)  # its own cursor: inserts go on alongside
        for i, batch in enumerate(reader):
            chunk = prepare(fs.standardize, batch.to_pandas().astype("string"), normalized, used)
            self.con.register("er_chunk", chunk)
            self.con.execute(f"CREATE TABLE {into} AS SELECT * FROM er_chunk" if i == 0 else f"INSERT INTO {into} SELECT * FROM er_chunk")
            self.con.unregister("er_chunk")
        self.n = self._count(into)
        self._done("load", "O(N·L)", f"O({self.n:,}·L)", t, records=self.n, disabled=len(self.disabled), set_aside=self._count("set_aside"))

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
        """The pairs that fit in DuckDB's memory limit plus the free space of its temp directory, at BYTES_PER_PAIR."""
        limit, temp = self.con.execute("SELECT current_setting('memory_limit'), current_setting('temp_directory')").fetchall()[0]
        free = shutil.disk_usage(temp if temp and os.path.isdir(temp) else ".").free
        return int((size_bytes(limit) + free) / BYTES_PER_PAIR)

    def _untrusted(self, i: int, rule_keys: list[str], within: str | None = None) -> str | None:
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
        self.notes.append(f"rule {self.rule_names[i]} doesn't trust {n:,} value{'s' if n > 1 else ''} held by {m}+ records "
                          f"({int(records):,} records), e.g. {', '.join(f'{c} = {v}' for c, v in zip(rule_keys, top))} in {top[-1]:,}")
        return name

    def fit(self) -> dict:
        """λ from the near-certain rules, u by random sampling, m by EM, on a fixed-size sample of whole postal areas
        (households stay together, and the cost doesn't grow with the file). Skipped when a fitted model was given."""
        t = time.perf_counter()
        if self.model is None:
            n = self.pipeline.fit_rows
            area = q("postal_code__first3") if "postal_code__first3" in self._columns() else None
            order = f"hash({area}), hash({q(self.uid)})" if area else f"hash({q(self.uid)})"
            sample = self.con.execute(f"SELECT * FROM records ORDER BY {order} LIMIT {n}").df().astype("string")
            self.model = train_fs(self.pipeline.fs.model, sample, self.db, self.uid)
            self.notes += [f"the fit found no two records sharing {f} in its sample of {len(sample):,}, so it learned nothing from them"
                           for f in self.model["er"].get("skipped", [])]
        self._done("fit", "O(n + S·K + P_em·K)", f"n = {self.model['er']['fit_rows']:,}", t)
        return self.model

    def _columns(self) -> set[str]:
        return {c[0] for c in self.con.execute("DESCRIBE records").fetchall()}

    def _cluster(self, edges: str, into: str) -> None:
        """Connected components (Splink, in SQL) over these edges; every record is a node."""
        u = q(self.uid)
        self.con.execute(f"DROP TABLE IF EXISTS {into}")
        if not self._count(edges):
            self.con.execute(f"CREATE TABLE {into} AS SELECT {u}, {u} AS cluster_id FROM records")
            return
        out = cluster_pairwise_predictions_at_threshold(
            nodes=self.db.register(self.con.sql(f"SELECT {u} FROM records")),
            edges=self.db.register(self.con.sql(f"SELECT {q(self.l)}, {q(self.r)} FROM {edges}")), db_api=self.db, node_id_column_name=self.uid)
        out.as_duckdbpyrelation().project(f"{u}, cluster_id::VARCHAR AS cluster_id").to_table(into)
        out.drop_table_from_database_and_remove_from_cache()

    def _resolved(self, clusters: str) -> str:  # the records in a cluster of two or more
        return f"(SELECT {q(self.uid)} FROM {clusters} WHERE cluster_id IN (SELECT cluster_id FROM {clusters} GROUP BY 1 HAVING count(*) > 1))"

    def rules(self) -> None:
        """One join per rule (the first rule wins a pair), then the cascade: a later stage adds a pair only if it
        touches a record still unresolved; clusters are recomputed after each stage."""
        t, l, r = time.perf_counter(), q(self.l), q(self.r)
        rules = self.pipeline.rules
        inputs = {}
        for i, (st, rule) in enumerate((st, rule) for st in rules.stages for rule in st.rules):
            if (untrusted := self._untrusted(i, st.keys(rule))):
                keys = " AND ".join(f"z.{q(c)} = x.{q(c)}" for c in st.keys(rule))
                self.con.execute(f"CREATE OR REPLACE VIEW er_rule_in_{i} AS SELECT * FROM records x WHERE NOT EXISTS (SELECT 1 FROM {untrusted} z WHERE {keys})")
                inputs[rule.name] = f"er_rule_in_{i}"
        rule_edges_table(rules, "records", self.db, self.uid, "rule_edges", inputs)
        self.con.execute(f"CREATE OR REPLACE TABLE rule_kept AS SELECT * FROM rule_edges WHERE FALSE")
        self.con.execute(f"CREATE OR REPLACE TABLE rule_clusters AS SELECT {q(self.uid)}, {q(self.uid)} AS cluster_id FROM records")
        for st in rules.stages:
            done = self._resolved("rule_clusters")
            self.con.execute(f"INSERT INTO rule_kept SELECT * FROM rule_edges WHERE stage = '{st.name}' AND NOT ({l} IN {done} AND {r} IN {done})")
            self._cluster("rule_kept", "rule_clusters")
        p = self._count("rule_edges")
        self._done("rules", "O(N + Σ P_r·L²) + O((N + E)·d)", f"O({self.n:,} + {p:,} pairs)", t, pairs=p, kept=self._count("rule_kept"))

    def candidates(self) -> pd.DataFrame:
        t, fs = time.perf_counter(), self.pipeline.fs
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

    def _gate(self, pairs: pd.DataFrame) -> pd.DataFrame:  # an oversized block's sampled pairs, scored with the fitted model
        return score_fs(self.model, "records", pairs, self.db, self.uid, n_records=self.n)

    def _gated(self, records: list[dict]) -> None:  # the oversized blocks' decisions, kept for qa and named in the summary
        self.gated = gated = pd.DataFrame(records)
        if gated.empty:
            return
        floor = review_floor(self.pipeline)
        for x in gated.sort_values("pairs", ascending=False).head(5).itertuples():
            self.notes.append(f"{x.generator}: {x.value} holds {x.records:,} records ({x.pairs:,} pairs); {int(x.hits)} of {int(x.sampled)} "
                              f"sampled pairs reach {floor:g} bits: {x.decision}")
        if len(gated) > 5:
            kept = (gated["decision"] == "kept").sum()
            self.notes.append(f"{len(gated):,} oversized blocks in all: {kept:,} kept, {len(gated) - kept:,} skipped (qa.md lists them)")

    def _singletons(self, clusters: str) -> str:
        return f"(SELECT {q(self.uid)} FROM {clusters} WHERE cluster_id IN (SELECT cluster_id FROM {clusters} GROUP BY 1 HAVING count(*) = 1))"

    def score(self) -> None:
        """u measured on this file (the model's choice), then every candidate scored by Splink. Keeps the basis an
        increment needs to judge whether these u have gone stale (er.match.u_basis)."""
        t, fs = time.perf_counter(), self.pipeline.fs
        self.scoring, self.basis = self.model, {}
        if fs.model.u_from_scored:
            exact, sampled = exact_u(fs.model, "records", self.db), scored_sample(fs.model, "records", self.db, self.uid)
            self.scoring = assemble_u(fs.model, self.model, sampled, exact, "records", self.db)
            self.basis = u_basis(fs.model, sampled, exact, "records", self.db)
        score_fs(self.scoring, "records", "cands", self.db, self.uid, into="scores")
        c = self._count("scores")
        self._done("score", "O(N + S·K) + O(C·K·L²)", f"O({self.n:,} + {fs.model.u_max_pairs:,.0f}·{len(fs.model.comparisons)}) + O({c:,}·{len(fs.model.comparisons)}·L²)", t)

    def _accept(self) -> None:
        """matches: the scored pairs at the threshold or above that join two rule clusters (bridge) or touch a record the
        rules left alone, less those people decided are no match; kept: those, the rules' pairs, and the pairs people
        decided are a match (er_decisions, loaded by full() from the run folder; empty otherwise)."""
        fs, l, r, u = self.pipeline.fs, q(self.l), q(self.r), q(self.uid)
        done = self._resolved("rule_clusters")
        keep = "a.cluster_id <> b.cluster_id" if fs.bridge else f"NOT (s.{l} IN {done} AND s.{r} IN {done})"
        self.con.execute(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
        self.con.execute(f"""CREATE OR REPLACE TABLE matches AS
            SELECT s.{l}, s.{r}, s.match_weight, s.match_probability, c.sources FROM scores s JOIN cands c USING ({l}, {r})
                   JOIN rule_clusters a ON a.{u} = s.{l} JOIN rule_clusters b ON b.{u} = s.{r}
            WHERE s.match_weight >= {fs.min_match_weight} AND {keep}
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
        self.con.execute(f"""CREATE OR REPLACE TABLE gold AS
            WITH touch AS (SELECT {l} AS id, rule FROM rule_kept UNION ALL SELECT {r}, rule FROM rule_kept),
                 first AS (SELECT id, arg_min(rule, CASE rule {order} END) AS rule FROM touch GROUP BY id),
                 rsize AS (SELECT cluster_id, count(*) AS n FROM rule_clusters GROUP BY 1),
                 size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1),
                 matched AS (SELECT {l} AS id FROM matches UNION SELECT {r} FROM matches)
            SELECT k.{u}, k.cluster_id, {stage} AS resolved_stage, {by} AS resolved_by
            FROM clusters k JOIN size z USING (cluster_id) JOIN rule_clusters rc USING ({u}) JOIN rsize rz ON rz.cluster_id = rc.cluster_id
                 LEFT JOIN first f ON f.id = k.{u} LEFT JOIN matched m ON m.id = k.{u} {f"LEFT JOIN {old} o USING ({u})" if old else ""}
            ORDER BY k.{u}""")

    def cluster(self) -> None:
        """Accept at min_match_weight, then cluster every kept pair, the rules' and these; then gold."""
        t = time.perf_counter()
        self._accept()
        self._cluster("kept", "clusters")
        self._gold()
        e = self._count("matches")
        self._done("cluster", "O(C + (N + E)·d)", f"O({self._count('scores'):,} + ({self.n:,} + {e:,})·d)", t, accepted=e)

    def write(self, out: Path, part: int = 0) -> None:
        """Gold (each record's cluster, and the stage and rule that resolved it), the accepted pairs with their weights,
        the rules' pairs, as Parquet; and the state an increment needs: the standardized records and the rules'
        clusters. Records, rules' pairs and matches are folders that increments append to. Staged: see the module."""
        t, state, name = time.perf_counter(), out / "state", f"part-{part:05d}.parquet"
        for folder in (state / "records", out / "rule_kept", out / "matches"):
            folder.mkdir(parents=True, exist_ok=True)
        aside = [("SELECT * FROM set_aside", out / "set_aside" / name)] if self._count("set_aside") else []
        if aside:
            (out / "set_aside").mkdir(exist_ok=True)
        texts = [(json.dumps(self.model, ensure_ascii=False), state / "model.json")] if part == 0 else []
        if self.basis:  # the u this run scored with, and what an increment needs to tell when they go stale
            texts.append((json.dumps(dict(model=self.scoring, basis=self.basis), ensure_ascii=False), state / "scoring.json"))
        self._stage(out, [("SELECT * FROM rule_kept", out / "rule_kept" / name), ("SELECT * FROM matches", out / "matches" / name),
                          (f"SELECT * FROM gold ORDER BY {q(self.uid)}", out / "gold.parquet"),
                          ("SELECT * FROM rule_clusters", state / "rule_clusters.parquet"),
                          (f"SELECT * FROM {'records' if part == 0 else 'new_records'}", state / "records" / name), *aside], texts)
        self._done("write", "O(N + C)", f"O({self.n:,} + {self._count('matches'):,})", t)
        self._log(out, part > 0, part=part, disabled=self.disabled)

    def _stage(self, out: Path, tables: list[tuple[str, Path]], texts: list[tuple[str, Path]] = ()) -> None:
        """Write every file under a temporary name; once all are complete, save the renames still owed (pending.json),
        then do them. An interruption before that leaves the folder as it was; one after it, finish_writes completes."""
        staged = []
        for sql, dest in tables:
            tmp = dest.with_name(dest.name + ".tmp")
            self.con.execute(f"COPY ({sql}) TO {lit(tmp)} (FORMAT parquet)")
            staged.append([str(tmp), str(dest)])
        for text, dest in texts:
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            staged.append([str(tmp), str(dest)])
        (out / (PENDING + ".tmp")).write_text(json.dumps(staged), encoding="utf-8")
        os.replace(out / (PENDING + ".tmp"), out / PENDING)  # from here on the write is done, whatever happens next
        finish_writes(out)

    def _log(self, out: Path, append: bool, **entry: object) -> None:  # steps.json: one entry per run, increment or set of decisions
        log = out / "steps.json"
        runs = json.loads(log.read_text())["runs"] if append and log.exists() else []
        log.write_text(json.dumps(dict(runs=[*runs, dict(**entry, steps=self.steps)]), indent=1, default=str))

    # ---------- increments ----------

    def _merge(self, base: str, edges: str, into: str) -> None:
        """`base` (uid → cluster_id, every record) with these edges added. Each existing cluster is one node, so the
        work grows with the edges, not with the file; a merged cluster takes the smallest id, as a full rebuild does
        (Splink names a cluster after its smallest uid)."""
        u, l, r = q(self.uid), q(self.l), q(self.r)
        self.con.execute(f"""CREATE OR REPLACE TABLE er_e AS SELECT DISTINCT least(a.cluster_id, b.cluster_id) AS {l},
            greatest(a.cluster_id, b.cluster_id) AS {r} FROM {edges} e JOIN {base} a ON a.{u} = e.{l} JOIN {base} b ON b.{u} = e.{r}
            WHERE a.cluster_id <> b.cluster_id""")
        if not self._count("er_e"):
            self.con.execute(f"CREATE OR REPLACE TABLE {into} AS SELECT * FROM {base}")
            return
        comp = cluster_pairwise_predictions_at_threshold(
            nodes=self.db.register(self.con.sql(f"SELECT {l} AS {u} FROM er_e UNION SELECT {r} FROM er_e")),
            edges=self.db.register(self.con.sql("SELECT * FROM er_e")), db_api=self.db, node_id_column_name=self.uid)
        self.con.execute("DROP TABLE IF EXISTS er_comp")
        comp.as_duckdbpyrelation().project(f"{u} AS node, cluster_id::VARCHAR AS cluster_id").to_table("er_comp")
        comp.drop_table_from_database_and_remove_from_cache()
        self.con.execute(f"""CREATE OR REPLACE TABLE {into} AS SELECT b.{u}, coalesce(c.cluster_id, b.cluster_id) AS cluster_id
            FROM {base} b LEFT JOIN er_comp c ON c.node = b.cluster_id""")

    @locked
    def increment(self, path: str | Path, out: Path) -> "Run":
        """Add a batch of new records to the run written in `out`. See the module docstring for the cost."""
        state, u, l, r = out / "state", q(self.uid), q(self.l), q(self.r)
        finish_writes(out)
        self.model = json.loads((state / "model.json").read_text(encoding="utf-8"))
        part = len(list((state / "records").glob("part-*.parquet")))
        parts = ", ".join(lit(x) for x in sorted((state / "records").glob("part-*.parquet")))  # not a glob: this run's own part comes later
        self.con.execute(f"CREATE OR REPLACE VIEW old_records AS SELECT * FROM read_parquet([{parts}])")
        self.load(path, into="new_records", stored="old_records")  # a record already in the run is set aside: a retry adds nothing twice
        self.added = self.n
        if not self.added:
            other = self.con.execute("SELECT count(*) FROM set_aside WHERE reason <> 'already in the run'").fetchall()[0][0]
            if other:
                raise InputError(f"{path}: no new record to add ({'; '.join(self.notes)})", fix="give the records set aside IDs, one per record")
            return self  # every record is already in the run: nothing to do
        self.con.execute("CREATE OR REPLACE VIEW records AS SELECT * FROM old_records UNION ALL BY NAME SELECT * FROM new_records")
        self.con.execute(f"CREATE OR REPLACE TABLE new_ids AS SELECT {u} FROM new_records")
        self.n = self._count("records")

        t = time.perf_counter()  # the rules: each against the batch only, then the cascade on the merged clusters
        rules = self.pipeline.rules
        parts = []
        for i, (st, rule) in enumerate((st, rule) for st in rules.stages for rule in st.rules):
            untrusted = self._untrusted(i, st.keys(rule), within="new_records")
            trust = (f" AND NOT EXISTS (SELECT 1 FROM {untrusted} z WHERE {' AND '.join(f'z.{q(c)} = l.{q(c)}' for c in st.keys(rule))})"
                     if untrusted else "")
            parts.append(f"SELECT least(l.{u}, r.{u}) AS {l}, greatest(l.{u}, r.{u}) AS {r}, '{rule.name}' AS rule, '{st.name}' AS stage, "
                         f"{i} AS i FROM new_records l JOIN records r ON {st.sql(rule)} AND l.{u} <> r.{u}{trust}")
        self.con.execute(f"""CREATE OR REPLACE TABLE rule_edges AS SELECT DISTINCT ON ({l}, {r}) {l}, {r}, rule, stage, 1.0 AS score
            FROM ({' UNION ALL '.join(parts)}) ORDER BY {l}, {r}, i""")
        self.con.execute(f"""CREATE OR REPLACE TABLE rule_clusters AS SELECT * FROM read_parquet({lit(state / 'rule_clusters.parquet')})
            UNION ALL SELECT {u}, {u} AS cluster_id FROM new_ids""")
        self.con.execute("CREATE OR REPLACE TABLE rule_kept AS SELECT * FROM rule_edges WHERE FALSE")
        for st in rules.stages:
            done = self._resolved("rule_clusters")
            self.con.execute(f"""CREATE OR REPLACE TABLE er_stage AS SELECT * FROM rule_edges WHERE stage = '{st.name}'
                AND NOT ({l} IN {done} AND {r} IN {done})""")
            self.con.execute("INSERT INTO rule_kept SELECT * FROM er_stage")
            self._merge("rule_clusters", "er_stage", "rule_clusters")
        self._done("rules", "O(|Δ|·Σ b + scan)", f"O({self._count('new_ids'):,} new records)", t, kept=self._count("rule_kept"))

        t, fs = time.perf_counter(), self.pipeline.fs
        _, report = candidates(fs.blockers, "records", self.uid, "new_ids", fs.budget,
                               clusters="rule_clusters" if fs.bridge else None, con=self.con, into="cands", touching=True,
                               gate=self._gate, floor=review_floor(self.pipeline), capacity=self.capacity())
        self._gated(report.attrs["gated"])
        self._done("candidates", "O(|Δ|·Σ b + scan)", f"{self._count('cands'):,} pairs touching the batch", t)

        t, again = time.perf_counter(), []
        self.scoring, self.basis = self.model, {}
        if fs.model.u_from_scored:  # exact levels counted again; a comparison sampled again only once it is stale
            stored = state / "scoring.json"
            basis = json.loads(stored.read_text(encoding="utf-8"))["basis"] if stored.exists() else {}
            self.scoring, self.basis, again = refreshed_u(fs.model, self.model, basis, "records", self.db, self.uid)
            self.notes += [f"u of {c} measured again: it drifted {self.basis[c]['last_check']['drift_bits']:.3f} bits, more than "
                           f"its sampling error ({self.basis[c]['last_check']['se_bits']:.3f})" for c in again if self.basis[c]['last_check']['drift_bits'] is not None]
        self.con.execute(f"""CREATE OR REPLACE TABLE touched AS SELECT * FROM records WHERE {u} IN
            (SELECT {l} FROM cands UNION SELECT {r} FROM cands)""")
        score_fs(self.scoring, "touched", "cands", self.db, self.uid, into="scores", n_records=self.n)
        self._done("score", "O(N + S·K_stale) + O(C_Δ·K·L²)", f"O({self.n:,} + {fs.model.u_max_pairs:,.0f}·{len(again)}) + "
                   f"O({self._count('cands'):,}·{len(fs.model.comparisons)}·L²)", t, sampled_again=len(again))

        t = time.perf_counter()
        self._accept()
        self.con.execute(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM read_parquet({lit(out / 'gold.parquet')})")
        self.con.execute(f"CREATE OR REPLACE TABLE er_base AS SELECT {u}, cluster_id FROM gold_old UNION ALL SELECT {u}, {u} FROM new_ids")
        self._merge("er_base", "kept", "clusters")
        self._gold("gold_old")
        self._done("cluster", "O(C_Δ + touched clusters)", f"{self._count('matches'):,} accepted", t, accepted=self._count("matches"))
        self.write(out, part)
        return self

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
        src, cols = source.sql, set(source.columns)
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
        self._merge("er_base", "er_review", "clusters")
        self.con.execute(f"""CREATE OR REPLACE TABLE gold AS WITH size AS (SELECT cluster_id, count(*) AS n FROM clusters GROUP BY 1)
            SELECT c.{u}, c.cluster_id, coalesce(o.resolved_stage, CASE WHEN z.n > 1 THEN 'review' END) AS resolved_stage,
                   coalesce(o.resolved_by, CASE WHEN z.n > 1 THEN 'review' END) AS resolved_by
            FROM clusters c JOIN size z USING (cluster_id) JOIN gold_old o USING ({u}) ORDER BY c.{u}""")
        d, m = self._count("er_decisions"), self._count("er_review")
        before, after = (self.con.execute(f"SELECT count(DISTINCT cluster_id) FROM {x}").fetchall()[0][0] for x in ("gold_old", "gold"))
        self._done("decide", "O(D + touched clusters) + O(N)", f"O({d:,} decisions + {self.n:,})", t,
                   decisions=d, matches=m, clusters_joined=before - after)
        parts = out / DECISIONS
        parts.mkdir(exist_ok=True)
        self._stage(out, [(f"SELECT * FROM gold ORDER BY {u}", out / "gold.parquet"),
                          ("SELECT * FROM er_decisions", parts / f"part-{len(list(parts.glob('part-*.parquet'))):05d}.parquet")])
        self._log(out, True, decisions=str(path))
        return self

    @locked
    def full(self, path: str | Path, out: Path, overwrite: bool = False) -> "Run":
        held = [out / f for f in RUN_FILES if (out / f).exists()]
        if held and not overwrite:
            raise FileExistsError(f"{out} already holds a run: choose another folder, or overwrite it (scripts/resolve.py --overwrite)")
        self.load(path)
        self.budget()
        self.fit()
        self.rules()
        self.candidates()
        self.score()
        self._load_decisions(out)
        self.cluster()
        for f in held:  # removed only now: a run that fails before this keeps the old one
            shutil.rmtree(f) if f.is_dir() else f.unlink()
        self.write(out)
        return self


def review_floor(p: Pipeline) -> float:
    """The lowest weight people are asked to decide: the threshold rule's safety margin below min_match_weight, i.e. the
    [threshold] grid point margin_steps below it. Pairs there were clean on cross-validated train, but held back."""
    below = sorted(g for g in p.threshold.grid if g < p.fs.min_match_weight)
    if not p.threshold.margin_steps or not below:
        return p.fs.min_match_weight
    return below[-min(p.threshold.margin_steps, len(below))]


def fill_rates(run: "Run", fields: list[str]) -> pd.DataFrame:
    """Each field's share of filled records, flagged under 5%: a field almost never filled is often a mapping mistake."""
    cols = run._columns()
    return pd.DataFrame([dict(field=f, filled=run.con.execute(f"SELECT avg(({q(f)} IS NOT NULL)::INT) FROM records").fetchall()[0][0])
                         for f in fields if f in cols], columns=["field", "filled"]).assign(flag=lambda d: np.where(d["filled"] < 0.05, "under 5%", ""))


def qa(run: "Run", fields: list[str], review: int = 50, previous: Path | None = None) -> dict[str, pd.DataFrame]:
    """The label-free report of a run: a summary in words (records, entities, who joined them, what to decide, what the
    loader fixed), fill rate per field (flagged under 5%), what was disabled, every step's cost,
    accepted pairs by weight band, cluster sizes, the largest clusters (the over-merge alarm), and the review sheet
    for people (review_sheet). Its rows are of two kinds. "decide": every pair of clusters whose best link scored in the
    threshold's safety margin [review_floor, min_match_weight), not decided yet, best link first. "audit": accepted pairs
    up to 4 bits above the threshold, `review` of them, stratified by 1-bit band. `previous`, the run folder's sheet
    before an increment: its open rows stay (carry_over), since the scores behind them aren't kept."""
    con, u, t = run.con, q(run.uid), run.pipeline.fs.min_match_weight
    fill = fill_rates(run, fields)
    bands = con.sql(f"""SELECT floor(match_weight / 2) * 2 AS weight_from, count(*) AS pairs,
                               count(*) FILTER (WHERE match_weight >= {t}) AS accepted FROM scores GROUP BY 1 ORDER BY 1""").df()
    sizes = con.sql("SELECT n AS cluster_size, count(*) AS clusters FROM (SELECT count(*) AS n FROM gold GROUP BY cluster_id) GROUP BY 1 ORDER BY 1").df()
    largest = con.sql("SELECT cluster_id, count(*) AS records FROM gold GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10").df()
    l, r, lo = q(run.l), q(run.r), review_floor(run.pipeline)
    con.execute(f"CREATE TABLE IF NOT EXISTS er_decisions ({l} VARCHAR, {r} VARCHAR, decision VARCHAR)")
    decide = con.sql(f"""SELECT * EXCLUDE (k1, k2) FROM (
            SELECT s.*, c.sources, least(ga.cluster_id, gb.cluster_id) AS k1, greatest(ga.cluster_id, gb.cluster_id) AS k2
            FROM scores s JOIN cands c USING ({l}, {r}) JOIN gold ga ON ga.{u} = s.{l} JOIN gold gb ON gb.{u} = s.{r}
            WHERE s.match_weight >= {lo} AND s.match_weight < {t} AND ga.cluster_id <> gb.cluster_id
              AND NOT EXISTS (SELECT 1 FROM er_decisions d WHERE d.{l} = s.{l} AND d.{r} = s.{r}))
        QUALIFY row_number() OVER (PARTITION BY k1, k2 ORDER BY match_weight DESC, {l}, {r}) = 1
        ORDER BY match_weight DESC, {l}, {r}""").df().assign(why="decide")
    audit = con.sql(f"""SELECT * EXCLUDE (k) FROM (SELECT s.*, c.sources, row_number() OVER (PARTITION BY floor(s.match_weight) ORDER BY hash(s.{l}, s.{r})) AS k
                        FROM scores s JOIN cands c USING ({l}, {r}) WHERE s.match_weight >= {t} AND s.match_weight < {t + 4})
                        WHERE k <= {max(1, review // 4)} ORDER BY match_weight, {l}, {r}""").df().assign(why="audit")
    steps = pd.DataFrame(run.steps)
    base = ["step", "big_o", "filled", "seconds", "peak_memory_gb"]
    steps = steps[base].assign(facts=steps.drop(columns=base).apply(lambda r: " · ".join(f"{k} {v:,.0f}" for k, v in r.dropna().items()), axis=1))
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
    summary = pd.DataFrame([
        ("records", f"{total:,}" + (f", {run.added:,} of them new" if run.added is not None else "") + (f"; {aside:,} set aside (set_aside/)" if aside else "")),
        ("entities", f"{entities:,}; the largest holds {biggest:,} records"),
        ("joined by", f"the rules {by_rules:,} · the model {by_model:,} · people {by_people:,} records"),
        ("to decide", f"{len(decide):,} pair{'' if len(decide) == 1 else 's'} in review.parquet (why = decide)"),
        *(("note", f"{f} only {x:.1%} filled: check its mapping") for f, x in fill.loc[fill["flag"] != "", ["field", "filled"]].itertuples(index=False)),
        *(("note", f"turned off, a field it reads is missing: {d}") for d in run.disabled),
        *(("note", note) for note in run.notes)], columns=["what", "value"])
    return dict(summary=summary, fill=fill, disabled=pd.DataFrame({"disabled": run.disabled}), steps=steps, weight_bands=bands,
                cluster_sizes=sizes, largest_clusters=largest, patterns_without_a_key=coverage.head(20), review=queue,
                oversized_blocks=run.gated,
                review_sheet=sheet)


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
    comparison the level the pair landed in and the bits it earned, which with the prior sum to its weight; an empty
    `decision` for people to fill in (match or no_match) and give to Run.decide. O(pairs)."""
    comps, uid = run.pipeline.fs.model.comparisons, run.uid
    fields = [f for f in dict.fromkeys(col for c in comps for col in (*c.null_if_missing, *(x for lv in c.levels for x, _ in lv.any_of)))
              if f in run._columns()]
    run.con.register("er_review_ids", pd.DataFrame({uid: pd.concat([pairs[run.l], pairs[run.r]]).unique()}))
    records = run.con.sql(f"SELECT {', '.join(q(c) for c in [uid, *fields])} FROM records JOIN er_review_ids USING ({q(uid)})").df()
    run.con.unregister("er_review_ids")
    out = pairs.merge(records.add_suffix("_l"), on=run.l).merge(records.add_suffix("_r"), on=run.r)
    out["accepted"] = out["match_weight"] >= run.pipeline.fs.min_match_weight
    out["decision"] = pd.Series(pd.NA, index=out.index, dtype="string")
    by_gamma = levels(run.scoring)
    for c in comps:
        gamma = out.pop(f"gamma_{c.name}").astype(int)
        out[c.name] = gamma.map(lambda g: by_gamma[c.name][g][0])
        out[f"{c.name}_bits"] = gamma.map(lambda g: round(by_gamma[c.name][g][1], 2))
    return out[[*(["why"] if "why" in out else []), "decision", run.l, run.r, "match_weight", "match_probability", "accepted", "sources",
                *(f"{f}_{side}" for f in fields for side in ("l", "r")), *(x for c in comps for x in (c.name, f"{c.name}_bits"))]
               ].reset_index(drop=True)

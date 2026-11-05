"""The run on any file of records, without labels: a chosen pipeline (config/final.toml) end to end on DuckDB tables,
so memory stays bounded at any size (past config/settings.toml [compute] memory_limit, DuckDB spills to disk). Each
step is a method of Run, called in order by full(), or one at a time by the demo notebook. Each records its Big-O,
with the numbers filled in, and its time.

    load        O(N·L)                           read in chunks, check the fields, standardize each chunk → table records
    budget      O(N)                             exact block sizes per rule and generator, before any join
    fit         O(n + S·K + P_em·K)              λ, u and m by EM on a fixed-size sample of n records (or a fitted model)
    rules       O(N + Σ P_r·L²) + O((N + E)·d)   one join per rule (the first rule wins), then the rules' cascade
    candidates  O(N·L + Σ P_g)                   every generator; pairs inside one rule cluster dropped
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
already holds a run unless told to overwrite it.

N records, L characters per value, P pairs in a rule's or generator's key blocks, C candidates, K comparisons,
S sampled pairs for u, E accepted pairs, d cluster diameter (Splink's connected components take up to d rounds).
"""
import json
import os
import resource
import shutil
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd
from splink.clustering import cluster_pairwise_predictions_at_threshold

from er.candidates import candidates, estimate, q
from er.config import Key, KeyBlocker, OverBudget, Pipeline
from er.match import ELSE, assemble_u, exact_u, levels, refreshed_u, rule_edges_table, score_fs, scored_sample, train_fs, u_basis
from er.pipeline import pattern_coverage
from er.settings import Settings, fit_to_file
from er.standardize import prepare
from er.strings import connect


def peak_gb() -> float:  # the process's peak resident memory so far (ru_maxrss: bytes on macOS, KB on Linux)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)


PENDING = "pending.json"  # the renames a write still owes, saved once every new file is complete
RUN_FILES = ("gold.parquet", "steps.json", PENDING, "matches", "rule_kept", "state")  # what a run writes in its folder
DECISIONS = "decisions"  # people's decisions: not a run file, so a full run with overwrite keeps and applies them


def lit(path: str | Path) -> str:  # a path as an SQL string literal
    return "'" + str(path).replace("'", "''") + "'"


def finish_writes(out: Path) -> None:
    """Complete the renames of a write that was interrupted after its new files were complete; nothing otherwise."""
    pending = out / PENDING
    if pending.exists():
        for tmp, dest in json.loads(pending.read_text(encoding="utf-8")):
            if os.path.exists(tmp):
                os.replace(tmp, dest)
        pending.unlink()


def source_sql(path: str | Path) -> str:
    """A file (or a glob) as a relation of strings: CSV or Parquet."""
    if str(path).endswith(".parquet"):
        return f"(SELECT * FROM read_parquet({lit(path)}))"
    return f"(SELECT * FROM read_csv({lit(path)}, all_varchar = true, header = true))"


@dataclass
class Run:
    pipeline: Pipeline                        # the chosen pipeline; fitted to the file by load()
    settings: Settings
    model: dict | None = None                 # a fitted model (Splink JSON from train_fs); None: fit on this file
    chunk_rows: int = 200_000
    steps: list[dict] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.con, self.db = connect(self.settings.compute)
        self.uid = self.settings.data.unique_id
        self.l, self.r = f"{self.uid}_l", f"{self.uid}_r"

    def _done(self, name: str, big_o: str, filled: str, t: float, **facts: object) -> None:
        self.steps.append(dict(step=name, big_o=big_o, filled=filled, seconds=round(time.perf_counter() - t, 2),
                               peak_memory_gb=round(peak_gb(), 2), **facts))

    def _count(self, sql: str) -> int:
        return self.con.execute(f"SELECT count(*) FROM {sql}").fetchall()[0][0]

    # ---------- the steps ----------

    def load(self, path: str | Path, into: str = "records") -> None:
        """Read the file in chunks; check its fields against config/pipeline.toml [fields]; standardize each chunk with
        er.standardize.prepare (each record on its own, so chunking changes nothing) into the table `records`."""
        t, src = time.perf_counter(), source_sql(path)
        columns = [c[0] for c in self.con.execute(f"DESCRIBE {src}").fetchall()]
        self.pipeline, self.disabled = fit_to_file(self.pipeline, self.settings, columns)
        if self.model is not None:  # a given model must compare exactly what this file's fields let the pipeline compare
            fitted = {(c["output_column_name"], lv["label_for_charts"]) for c in self.model["comparisons"]
                      for lv in c["comparison_levels"] if not lv.get("is_null_level")}
            here = {(c.name, label) for c in self.pipeline.fs.model.comparisons for label in (*(lv.label for lv in c.levels), ELSE)}
            if fitted != here:
                raise ValueError(f"{path}: the model was fitted on other comparison levels (only in the model: {sorted(fitted - here)}; "
                                 f"only here: {sorted(here - fitted)}); fit on this file instead (scripts/resolve.py without --model)")
        n, ids, empty = self.con.execute(f"SELECT count(*), count(DISTINCT {q(self.uid)}), count(*) - count({q(self.uid)}) FROM {src}").fetchall()[0]
        if empty or ids != n:
            raise ValueError(f"{path}: {self.uid} must be filled and unique ({empty} empty, {n - ids} repeated)")
        fs, rules = self.pipeline.fs, self.pipeline.rules
        normalized, used = [*rules.normalized(), *fs.normalized()], rules.used() | fs.used()
        reader = self.con.cursor().sql(f"SELECT * FROM {src}").to_arrow_reader(self.chunk_rows)  # its own cursor: inserts go on alongside
        self.con.execute(f"DROP TABLE IF EXISTS {into}")
        for i, batch in enumerate(reader):
            chunk = prepare(fs.standardize, batch.to_pandas().astype("string"), normalized, used)
            self.con.register("er_chunk", chunk)
            self.con.execute(f"CREATE TABLE {into} AS SELECT * FROM er_chunk" if i == 0 else f"INSERT INTO {into} SELECT * FROM er_chunk")
            self.con.unregister("er_chunk")
        self.n = self._count(into)
        self._done("load", "O(N·L)", f"O({self.n:,}·L)", t, records=self.n, disabled=len(self.disabled))

    def budget(self) -> pd.DataFrame:
        """Exact block sizes on this file, per rule and per generator, by group-by: the run stops here, before any join,
        if one would exceed the budget."""
        t, rows = time.perf_counter(), []
        b = self.pipeline.fs.budget
        for st in self.pipeline.rules.stages:
            for rule in st.rules:
                rows.append(dict(kind="rule", name=rule.name, **estimate(KeyBlocker(name=rule.name, keys=tuple(map(Key, st.keys(rule)))), "records", 0, self.con)))
        for g in self.pipeline.fs.blockers:
            rows.append(dict(kind="generator", name=g.name, **estimate(g, "records", self.n, self.con)))
        plan = pd.DataFrame(rows)
        self._done("budget", "O(N)", f"O({self.n:,}) per rule and generator", t, pairs=int(plan["est_pairs"].sum()))
        over = plan[(plan["est_pairs"] > b.max_pairs(self.n)) | (plan["largest_block"] > b.max_block_size)]
        if len(over):
            raise OverBudget(f"over budget on this file: {over[['kind', 'name', 'est_pairs', 'largest_block']].to_dict('records')}")
        return plan

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
        rule_edges_table(rules, "records", self.db, self.uid, "rule_edges")
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
                               clusters="rule_clusters" if fs.bridge else None, con=self.con, into="cands")
        c = self._count("cands")
        self._done("candidates", "O(N·L + Σ P_g)", f"O({self.n:,}·L + {int(report['pairs'].sum()):,})", t, candidates=c)
        return report

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
        texts = [(json.dumps(self.model, ensure_ascii=False), state / "model.json")] if part == 0 else []
        if self.basis:  # the u this run scored with, and what an increment needs to tell when they go stale
            texts.append((json.dumps(dict(model=self.scoring, basis=self.basis), ensure_ascii=False), state / "scoring.json"))
        self._stage(out, [("SELECT * FROM rule_kept", out / "rule_kept" / name), ("SELECT * FROM matches", out / "matches" / name),
                          (f"SELECT * FROM gold ORDER BY {q(self.uid)}", out / "gold.parquet"),
                          ("SELECT * FROM rule_clusters", state / "rule_clusters.parquet"),
                          (f"SELECT * FROM {'records' if part == 0 else 'new_records'}", state / "records" / name)], texts)
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

    def increment(self, path: str | Path, out: Path) -> "Run":
        """Add a batch of new records to the run written in `out`. See the module docstring for the cost."""
        state, u, l, r = out / "state", q(self.uid), q(self.l), q(self.r)
        finish_writes(out)
        self.model = json.loads((state / "model.json").read_text(encoding="utf-8"))
        part = len(list((state / "records").glob("part-*.parquet")))
        self.load(path, into="new_records")
        parts = ", ".join(lit(x) for x in sorted((state / "records").glob("part-*.parquet")))  # not a glob: this run's own part comes later
        self.con.execute(f"CREATE OR REPLACE VIEW old_records AS SELECT * FROM read_parquet([{parts}])")
        clash = self.con.execute(f"SELECT count(*) FROM new_records JOIN old_records USING ({u})").fetchall()[0][0]
        if clash:
            raise ValueError(f"{clash} records of {path} are already in the run: an increment adds new records only")
        self.con.execute("CREATE OR REPLACE VIEW records AS SELECT * FROM old_records UNION ALL BY NAME SELECT * FROM new_records")
        self.con.execute(f"CREATE OR REPLACE TABLE new_ids AS SELECT {u} FROM new_records")
        self.n = self._count("records")

        t = time.perf_counter()  # the rules: each against the batch only, then the cascade on the merged clusters
        rules = self.pipeline.rules
        parts = []
        for i, (st, rule) in enumerate((st, rule) for st in rules.stages for rule in st.rules):
            parts.append(f"SELECT least(l.{u}, r.{u}) AS {l}, greatest(l.{u}, r.{u}) AS {r}, '{rule.name}' AS rule, '{st.name}' AS stage, "
                         f"{i} AS i FROM new_records l JOIN records r ON {st.sql(rule)} AND l.{u} <> r.{u}")
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
                               clusters="rule_clusters" if fs.bridge else None, con=self.con, into="cands", touching=True)
        self._done("candidates", "O(|Δ|·Σ b + scan)", f"{self._count('cands'):,} pairs touching the batch", t)

        t, again = time.perf_counter(), []
        self.scoring, self.basis = self.model, {}
        if fs.model.u_from_scored:  # exact levels counted again; a comparison sampled again only once it is stale
            stored = state / "scoring.json"
            basis = json.loads(stored.read_text(encoding="utf-8"))["basis"] if stored.exists() else {}
            self.scoring, self.basis, again = refreshed_u(fs.model, self.model, basis, "records", self.db, self.uid)
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

    def decide(self, path: str | Path, out: Path) -> "Run":
        """Apply people's decisions on review pairs (a CSV or Parquet file: uid_l, uid_r, decision) to the run in `out`,
        scoring nothing. Each `match` pair merges its two clusters, each cluster one node, and a record joined only this
        way is resolved by `review`. A `no_match` pair splits nothing here; every decision is stored in decisions/, and a
        full run on this folder applies them again, never accepting a `no_match` pair. Rows without a decision are
        skipped. O(D + touched clusters) + O(N) to rewrite gold."""
        t, u, l, r = time.perf_counter(), q(self.uid), q(self.l), q(self.r)
        finish_writes(out)
        self.con.execute(f"CREATE OR REPLACE TABLE gold_old AS SELECT * FROM read_parquet({lit(out / 'gold.parquet')})")
        src = source_sql(path)
        cols = {c[0] for c in self.con.execute(f"DESCRIBE {src}").fetchall()}
        if {self.l, self.r, "decision"} - cols:  # the trust boundary: say what is wrong, row by row where it can
            raise ValueError(f"{path}: needs the columns {self.l}, {self.r} and decision; it has {sorted(cols)}")
        self.con.execute(f"""CREATE OR REPLACE TABLE er_decisions AS SELECT DISTINCT least({l}::VARCHAR, {r}::VARCHAR) AS {l},
            greatest({l}::VARCHAR, {r}::VARCHAR) AS {r}, lower(trim(decision::VARCHAR)) AS decision FROM {src}
            WHERE nullif(trim(decision::VARCHAR), '') IS NOT NULL""")
        bad = self.con.execute("SELECT DISTINCT decision FROM er_decisions WHERE decision NOT IN ('match', 'no_match')").fetchall()
        if bad:
            raise ValueError(f"{path}: a decision is match or no_match, not {sorted(x for x, in bad)}")
        both = self.con.execute(f"SELECT {l}, {r} FROM er_decisions GROUP BY ALL HAVING count(*) > 1 LIMIT 5").fetchall()
        if both:
            raise ValueError(f"{path}: pairs decided both ways: {both}")
        unknown = self.con.execute(f"""SELECT id FROM (SELECT {l} AS id FROM er_decisions UNION SELECT {r} FROM er_decisions)
            WHERE id NOT IN (SELECT {u} FROM gold_old) ORDER BY id LIMIT 5""").fetchall()
        if unknown:
            raise ValueError(f"{path}: records not in the run in {out}: {[x for x, in unknown]}")
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


def qa(run: "Run", fields: list[str], review: int = 50) -> dict[str, pd.DataFrame]:
    """The label-free report of a run: fill rate per field (flagged under 5%), what was disabled, every step's cost,
    accepted pairs by weight band, cluster sizes, the largest clusters (the over-merge alarm), and the review sheet
    for people (review_sheet). Its rows are of two kinds. "decide": every pair of clusters whose best link scored in the
    threshold's safety margin [review_floor, min_match_weight), not decided yet, best link first. "audit": accepted pairs
    up to 4 bits above the threshold, `review` of them, stratified by 1-bit band."""
    con, u, t = run.con, q(run.uid), run.pipeline.fs.min_match_weight
    cols = run._columns()
    fill = pd.DataFrame([dict(field=f, filled=con.execute(f"SELECT avg(({q(f)} IS NOT NULL)::INT) FROM records").fetchall()[0][0])
                         for f in fields if f in cols]).assign(flag=lambda d: np.where(d["filled"] < 0.05, "under 5%", ""))
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
    queue = pd.DataFrame(dict(why=["decide", "audit"], pairs=[len(decide), len(audit)], from_bits=[lo, t], below_bits=[t, t + 4]))
    return dict(fill=fill, disabled=pd.DataFrame({"disabled": run.disabled}), steps=steps, weight_bands=bands,
                cluster_sizes=sizes, largest_clusters=largest, patterns_without_a_key=coverage.head(20), review=queue,
                review_sheet=review_sheet(run, pd.concat([decide, audit], ignore_index=True)))


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

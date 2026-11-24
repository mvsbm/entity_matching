"""The jobs, as a machine runs them: here on DuckDB, on Cloud Run the same words (deploy/jobs/*.yaml).

    python -m er build records.parquet --out runs/main            a full run, then its lookup index
    python -m er update batch.parquet --out runs/main             a batch added to the run, the index kept up to date
    python -m er decide decisions.parquet --out runs/main         people's decisions applied (none named: review.parquet)
    python -m er lookup --out runs/main --record 1234             one record looked up in the index, as if it were new
    python -m er lookup --out runs/main FULL_NAME_KANA=ヤマダタロウ PHONE_NUM_4=1234
    python -m er lookup --out runs/main --file people.parquet    which entity each record of a file would join

Each prints one JSON object on stdout: what the job did. Each step, as it ends, is one JSON line on stderr. Exit
codes: 0; 2, a mistake people fix (the JSON says what is wrong, and the fix); 75, another job is writing the run: try
again later. The method is config/pipeline.toml (--pipeline another); the column mapping and the compute limits,
config/settings.toml (--compute KEY=VALUE for one run).
"""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from er.config import InputError, load_pipeline
from er.folder import Busy
from er.jobs import index
from er.jobs.build import build, out_of_memory
from er.jobs.decide import decide
from er.jobs.update import update, would_join
from er.settings import load_settings
from er.steps.job import Ran


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m er", description="Entity resolution jobs: build, update, decide, lookup.")
    jobs = p.add_subparsers(dest="job", required=True)
    for name, about, given in (("build", "a full run, then its lookup index", "the records: a Parquet file, a quoted glob or a folder of them"),
                               ("update", "a batch added to the run", "the batch, as build reads records"),
                               ("decide", "people's decisions applied to the run", "Parquet: id_l, id_r, decision (default: the run's review.parquet)"),
                               ("lookup", "records looked up in the run's index", "COLUMN=VALUE of one record, by the file's column names")):
        j = jobs.add_parser(name, help=about, description=about)
        j.add_argument("given", nargs="*" if name in ("decide", "lookup") else None, help=given)
        j.add_argument("--out", required=True, type=Path, help="the run's folder")
        j.add_argument("--pipeline", type=Path, help="the method (default: config/pipeline.toml)")
        j.add_argument("--compute", nargs="*", default=[], metavar="KEY=VALUE", help="DuckDB's limits for this run: memory_limit=8GB threads=4")
        if name == "build":
            j.add_argument("--overwrite", action="store_true", help="replace the run the folder holds, keeping people's decisions")
        if name == "lookup":
            j.add_argument("--record", help="a stored record's ID, looked up as if it were new")
            j.add_argument("--file", help="a file of records: which entity each would join, writing nothing")
            j.add_argument("--from", dest="at_least", type=float, help="the fewest points an entity shown has (default: the review floor)")
            j.add_argument("--count", type=int, default=20, help="the most entities shown")
    return p


def run(a: argparse.Namespace) -> dict:
    s = load_settings()
    if bad := [kv for kv in a.compute if "=" not in kv]:
        raise InputError(f"--compute {' '.join(bad)}: each limit is KEY=VALUE", fix="for example --compute memory_limit=8GB threads=4")
    s = replace(s, compute={**s.compute, **dict(kv.split("=", 1) for kv in a.compute)})
    pipeline = a.pipeline or s.root / "config" / "pipeline.toml"
    p = load_pipeline(pipeline, s.standardize, s.chains, s.columns)
    echo = lambda step: print(json.dumps(step, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
    if a.job != "build" and not a.out.is_dir():
        raise InputError(f"no run at {a.out}", fix=f"check the path, or build one: python -m er build FILE --out {a.out}")
    match a.job:
        case "build":
            return done(build(a.given, a.out, s, p, overwrite=a.overwrite, pipeline_file=pipeline, echo=echo))
        case "update":
            return done(update(a.given, a.out, s, p, pipeline_file=pipeline, echo=echo))
        case "decide":
            if len(a.given) > 1:
                raise InputError("one decisions file at a time", fix="give one Parquet file, or none for the run's review.parquet")
            ran = decide(a.given[0] if a.given else None, a.out, s, p, echo=echo)
            return {**done(ran), **{k: ran.steps[-1][k] for k in ("decisions", "matches", "clusters_joined")}}
    values = dict(typed(x) for x in a.given)
    if sum(map(bool, (values, a.record, a.file))) != 1:
        raise InputError("give one of: a record's COLUMN=VALUE words, --record ID, --file FILE", fix="for example: python -m er lookup --out runs/main --record 1234")
    if a.file:
        found = would_join(a.file, a.out, s, p, echo=echo)
        return dict(counts={k: int(v) for k, v in found["status"].value_counts().items()},
                    records=json.loads(found.to_json(orient="records", force_ascii=False)))
    return index.look_up(a.out, s, p, values=values or None, record=a.record, at_least=a.at_least, most=a.count)


def typed(item: str) -> tuple[str, str]:  # a COLUMN=VALUE word, by the file's column names
    column, sep, value = item.partition("=")
    if not sep or not column:
        raise InputError(f"{item}: write COLUMN=VALUE", fix='for example FULL_NAME_KANA="ヤマダ タロウ" PHONE_NUM_4=1234, by the file\'s column names')
    return column, value


def done(ran: Ran) -> dict:  # what a job did, in short: the full facts are in the run's steps.json
    return dict(records=ran.n, added=ran.added, seconds=round(sum(x["seconds"] for x in ran.steps), 1),
                steps={x["step"]: x["seconds"] for x in ran.steps}, notes=ran.notes,
                index={k: v for k, v in ran.index.items() if k in ("index", "records", "seconds", "rebuilt", "error", "fix")})


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # UTF-8 wherever it goes: a pipe or a file on Windows would take the locale's code page
        if hasattr(stream, "reconfigure") and stream.encoding.replace("-", "").lower() != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = parser().parse_args(argv)
    try:
        result = run(a)
    except InputError as e:
        print(json.dumps(dict(error=str(e), fix=e.fix), ensure_ascii=False))
        return 75 if isinstance(e, Busy) else 2
    except Exception as e:
        if not (oom := out_of_memory(e)):
            raise
        print(json.dumps(dict(error=str(oom), fix=oom.fix), ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A change to a workspace's method tried before it is adopted: the method and the variant, each run on the
workspace's files, compared on the pairs people decided and without labels (trial)."""
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

from er import folder, intake
from er.config import Pipeline, lit, q
from er.io import code_version, config_hash, replace_text
from er.review_state import applied
from er.run import Run, run_config
from er.settings import Settings
from er.strings import connect


def trial(ws: Path, base: Pipeline, variant: Pipeline, method: dict, s: Settings, echo: Callable[[dict], None] | None = None) -> dict:
    """The workspace's method (`base`) and a variant of it (`method`, as method.toml would say it), each run on the
    workspace's files without people's decisions, so neither is judged on pairs it was told, and at its own line, the
    trust line set aside, so a change shows what the method does rather than what merges yet; both keep the run's
    fitted model and people's person/company answers. Compared on the pairs people decided, each method's two kinds of
    mistake (different_joined: pairs people said are different, in one customer: a false merge; same_apart: pairs
    they said are the same, apart), with the pairs the variant sets right and wrong; and without labels: links, the
    false ones the model expects, entities, and the pairs of records the variant puts apart or together. The base's clusters are
    kept for the next trial of the same method on the same files (trials/base.parquet); each trial's result in
    trials/<n>.json. Two trials of one workspace take turns. O(two full runs without the fit) + O(N + D)."""
    trials, uid = ws / folder.TRIALS, s.data.unique_id
    base, variant = (replace(x, trust=replace(x.trust, line=None)) for x in (base, variant))  # a trust line would hide what each does
    trials.mkdir(exist_ok=True)
    model, files = json.loads((ws / "state" / "model.json").read_text(encoding="utf-8")), folder.inputs(ws, s.input, s.paths["reference"])

    def resolved(p: Pipeline, into: Path) -> dict:  # each record's cluster, written to `into`; and the numbers people compare
        run = Run(p, s, model=model, echo=echo)
        run.labels, run.keep = run._answers(ws), ws
        run.resolve(files, None)
        run.con.execute(f"COPY (SELECT {q(uid)}, cluster_id FROM gold) TO {lit(into)} (FORMAT parquet)")
        probed = next((x["strata"] for x in run.steps if x["step"] == "probe"), [])  # the matches no key lists, as its probe estimates them
        numbers = dict(matched=run._count("matches"), expected_false=run._expected_false(), rule_pairs=run._count("rule_kept WHERE merged"),
                       entities=run._count("(SELECT DISTINCT cluster_id FROM gold)"), missed={x["stratum"]: x["keys_missed"] for x in probed})
        run.con.close()
        return numbers

    with folder.run_lock(trials):
        key = dict(config=run_config(base, s), files=[intake.sha256(f) for f in files], model=config_hash(model), code=code_version(s.root),  # all the base's clusters rest on
                   answers=[intake.sha256(f) for f in folder.answer_parts(ws)])
        kept = json.loads((trials / "base.json").read_text(encoding="utf-8")) if (trials / "base.json").exists() else {}
        if kept.get("key") == key and (trials / "base.parquet").exists():
            before = kept["numbers"]
        else:
            before = resolved(base, trials / "base.parquet")
            replace_text(trials / "base.json", json.dumps(dict(key=key, numbers=before)))
        after = resolved(variant, trials / "variant.parquet")
        l, r, u = f"{uid}_l", f"{uid}_r", q(uid)
        decided = applied(ws, uid)[[l, r, "decision"]].reset_index(drop=True)
        con = connect(s.compute)[0]  # the two runs' clusters compared in SQL: O(N) rows never reach pandas
        con.execute(f"""CREATE TABLE o AS SELECT * FROM read_parquet({lit(trials / 'base.parquet')});
                        CREATE TABLE v AS SELECT * FROM read_parquet({lit(trials / 'variant.parquet')})""")
        con.register("er_decided", decided.assign(k=range(len(decided))))
        joined_before, joined_after = (np.array(x, dtype=bool) for x in zip(*con.execute(f"""SELECT coalesce(ol.cluster_id = orr.cluster_id, false),
            coalesce(vl.cluster_id = vr.cluster_id, false) FROM er_decided d LEFT JOIN o ol ON ol.{u} = d.{q(l)} LEFT JOIN o orr ON orr.{u} = d.{q(r)}
            LEFT JOIN v vl ON vl.{u} = d.{q(l)} LEFT JOIN v vr ON vr.{u} = d.{q(r)} ORDER BY d.k""").fetchall())) if len(decided) else (np.zeros(0, bool),) * 2
        same = (decided["decision"] == "match").to_numpy()
        was, now = joined_before == same, joined_after == same
        pairs = lambda rows: decided.loc[rows, [l, r, "decision"]].head(50).rename(columns={l: "id_l", r: "id_r"}).to_dict("records")
        c2 = lambda by: con.execute(f"SELECT coalesce(sum(c * (c - 1) // 2), 0) FROM (SELECT count(*) AS c FROM o JOIN v USING ({u}) GROUP BY {by})").fetchall()[0][0]  # pairs inside groups
        kept_together, base_pairs, variant_pairs = int(c2("o.cluster_id, v.cluster_id")), int(c2("o.cluster_id")), int(c2("v.cluster_id"))
        con.close()
        (trials / "variant.parquet").unlink()
        n = max((int(f.stem) for f in trials.glob("*.json") if f.stem.isdigit()), default=0) + 1
        result = dict(trial=n, at=datetime.now().isoformat(timespec="seconds"), method=method, base=before, variant=after,
                      different_joined=dict(base=int((joined_before & ~same).sum()), variant=int((joined_after & ~same).sum())),
                      same_apart=dict(base=int((~joined_before & same).sum()), variant=int((~joined_after & same).sum())),
                      fixed=pairs(now & ~was), broken=pairs(was & ~now),
                      apart=base_pairs - kept_together, together=variant_pairs - kept_together)
        replace_text(trials / f"{n}.json", json.dumps(result, ensure_ascii=False, default=str))
        for f in trials.glob("*.json"):  # bounded: the last 5 trials
            if f.stem.isdigit() and int(f.stem) <= n - 5:
                f.unlink()
    return result

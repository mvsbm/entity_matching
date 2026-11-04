"""Datasets and the standard stage files (dataset ∈ train, val, test).

data/medallion/silver/<dataset>.csv                      input records
data/labels/<dataset>.csv                                truth, read only to evaluate
data/artifacts/matched/<dataset>/<stage>_pairs.csv       entity matching: accepted pairs
data/artifacts/resolved/<dataset>/<stage>_resolved.csv   entity resolution: uid, cluster_id, resolved_stage, resolved_by
data/artifacts/resolved/<dataset>/<stage>_provenance.json  which input and configuration produced the stage files
data/artifacts/unresolved/<dataset>/<stage>_unresolved.csv  records still in a singleton cluster: the hand-off
data/medallion/gold/<dataset>.csv                        resolved entities after the last stage
data/artifacts/models/<name>.json                        a final configuration (and model) as it was run
data/artifacts/experiments/leaderboard.csv               one row per (experiment, dataset)
"""
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from er.config import Data

KINDS = {"matched": "pairs", "resolved": "resolved", "unresolved": "unresolved"}


def config_hash(config: object) -> str:
    return hashlib.sha1(repr(config).encode()).hexdigest()[:10]


def fingerprint(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def load(data: Data, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Records and truth, validated: this is where outside data enters every stage."""
    records = pd.read_csv(data.silver_dir / f"{dataset}.csv", dtype="string")
    truth = pd.read_csv(data.labels_dir / f"{dataset}.csv", dtype="string")
    uid = data.unique_id
    for name, frame in (("records", records), ("labels", truth)):
        if uid not in frame:
            raise ValueError(f"{dataset} {name}: no {uid} column")
        if frame[uid].isna().any():
            raise ValueError(f"{dataset} {name}: {int(frame[uid].isna().sum())} records without a {uid}")
        if frame[uid].duplicated().any():
            raise ValueError(f"{dataset} {name}: {uid} {frame[uid][frame[uid].duplicated()].iloc[0]} appears more than once")
    if data.entity_id not in truth or truth[data.entity_id].isna().any():
        raise ValueError(f"{dataset} labels: {data.entity_id} missing for some records")
    if set(records[uid]) != set(truth[uid]):
        raise ValueError(f"{dataset}: records and labels hold different {uid}s")
    return records, truth


def stage_path(data: Data, kind: str, dataset: str, stage: str) -> Path:
    return data.artifacts_dir / kind / dataset / f"{stage}_{KINDS[kind]}.csv"


def provenance_path(data: Data, dataset: str, stage: str) -> Path:
    return data.artifacts_dir / "resolved" / dataset / f"{stage}_provenance.json"


def write_stage(data: Data, dataset: str, stage: str, pairs: pd.DataFrame, resolved: pd.DataFrame,
                unresolved: pd.DataFrame, config: object) -> None:
    l, r = f"{data.unique_id}_l", f"{data.unique_id}_r"
    # DuckDB's parallel joins emit rows in varying order, and its parallel sums move weights by ~1e-14
    pairs = pairs.sort_values([l, r], kind="stable").round(10)
    for kind, frame in (("matched", pairs), ("resolved", resolved), ("unresolved", unresolved)):
        path = stage_path(data, kind, dataset, stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.astype("string").to_csv(path, index=False)
    provenance_path(data, dataset, stage).write_text(json.dumps(dict(
        stage=stage, dataset=dataset, input=fingerprint(data.silver_dir / f"{dataset}.csv"), config_hash=config_hash(config))))


def read_stage(data: Data, dataset: str, stage: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A stage's pairs and clusters, refused if they were made from a different version of the input."""
    path = provenance_path(data, dataset, stage)
    if not path.exists():
        raise FileNotFoundError(f"no provenance for the {stage} stage on {dataset}: run that notebook first")
    if json.loads(path.read_text())["input"] != fingerprint(data.silver_dir / f"{dataset}.csv"):
        raise ValueError(f"the {stage} stage on {dataset} is stale: {dataset}.csv changed after it ran; run it again")
    return (pd.read_csv(stage_path(data, "matched", dataset, stage), dtype="string"),
            pd.read_csv(stage_path(data, "resolved", dataset, stage), dtype="string"))


def write_gold(data: Data, dataset: str, resolved: pd.DataFrame) -> None:
    data.gold_dir.mkdir(parents=True, exist_ok=True)
    resolved.astype("string").to_csv(data.gold_dir / f"{dataset}.csv", index=False)


def write_final(data: Data, name: str, config: object, model: dict | None = None, **facts: object) -> Path:
    """The configuration a notebook ended with (and its fitted model, if any), plus facts such as the adopted
    changes, so a result can be traced and the configuration rebuilt."""
    data.models_dir.mkdir(parents=True, exist_ok=True)
    path = data.models_dir / f"{name}.json"
    path.write_text(json.dumps(dict(config=repr(config), config_hash=config_hash(config), model=model, **facts),
                               ensure_ascii=False, indent=1))
    return path


def append_leaderboard(data: Data, experiment: str, config: object, dataset: str, metrics: dict) -> None:
    """Append one row; the config hash tells identical configurations apart from same-named ones."""
    path = data.experiments_dir / "leaderboard.csv"
    data.experiments_dir.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), experiment=experiment, dataset=dataset,
                             config_hash=config_hash(config), **metrics)])
    board = pd.concat([pd.read_csv(path), row], ignore_index=True) if path.exists() else row
    board.to_csv(path, index=False)


def test_evaluations(data: Data) -> pd.DataFrame:
    """Distinct configurations scored on test, per experiment family (the part before ':'). More than one per family
    means test influenced a choice and its numbers are no longer unbiased."""
    path = data.experiments_dir / "leaderboard.csv"
    if not path.exists():
        return pd.DataFrame(columns=["family", "configs_on_test"])
    board = pd.read_csv(path)
    test = board[board["dataset"] == "test"].assign(family=lambda b: b["experiment"].str.split(":").str[0])
    return test.groupby("family")["config_hash"].nunique().rename("configs_on_test").reset_index()


def assert_test_scored_once(data: Data) -> None:
    """Fail loudly when a family has been scored on test with more than one configuration. Archive the leaderboard
    (data/artifacts/experiments/archive/) to start a clean pass after a deliberate change."""
    over = test_evaluations(data).query("configs_on_test > 1")
    if len(over):
        raise AssertionError(f"test was scored with several configurations: {over.to_dict('records')}")

"""Datasets and the standard stage files (dataset ∈ train, val, test).

data/medallion/silver/<dataset>.csv                      input records
data/labels/<dataset>.csv                                truth, read only to evaluate
data/artifacts/matched/<dataset>/<stage>_pairs.csv       entity matching: accepted pairs
data/artifacts/resolved/<dataset>/<stage>_resolved.csv   entity resolution: uid, cluster_id, resolved_stage, resolved_by
data/artifacts/unresolved/<dataset>/<stage>_unresolved.csv  records still in a singleton cluster: the hand-off
data/medallion/gold/<dataset>.csv                        resolved entities after the last stage
data/artifacts/experiments/leaderboard.csv               one row per (experiment, dataset)
"""
import hashlib
import time
from pathlib import Path

import pandas as pd

from er.config import Data

KINDS = {"matched": "pairs", "resolved": "resolved", "unresolved": "unresolved"}


def load(data: Data, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (pd.read_csv(data.silver_dir / f"{dataset}.csv", dtype="string"),
            pd.read_csv(data.labels_dir / f"{dataset}.csv", dtype="string"))


def stage_path(data: Data, kind: str, dataset: str, stage: str) -> Path:
    return data.artifacts_dir / kind / dataset / f"{stage}_{KINDS[kind]}.csv"


def write_stage(data: Data, dataset: str, stage: str, pairs: pd.DataFrame, resolved: pd.DataFrame,
                unresolved: pd.DataFrame) -> None:
    l, r = f"{data.unique_id}_l", f"{data.unique_id}_r"
    pairs = pairs.sort_values([l, r], kind="stable")  # DuckDB's parallel joins emit rows in varying order
    for kind, frame in (("matched", pairs), ("resolved", resolved), ("unresolved", unresolved)):
        path = stage_path(data, kind, dataset, stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.astype("string").to_csv(path, index=False)


def read_stage(data: Data, dataset: str, stage: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (pd.read_csv(stage_path(data, "matched", dataset, stage), dtype="string"),
            pd.read_csv(stage_path(data, "resolved", dataset, stage), dtype="string"))


def write_gold(data: Data, dataset: str, resolved: pd.DataFrame) -> None:
    data.gold_dir.mkdir(parents=True, exist_ok=True)
    resolved.astype("string").to_csv(data.gold_dir / f"{dataset}.csv", index=False)


def append_leaderboard(data: Data, experiment: str, config: object, dataset: str, metrics: dict) -> None:
    """Append one row; the config hash tells identical configurations apart from same-named ones."""
    path = data.experiments_dir / "leaderboard.csv"
    data.experiments_dir.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), experiment=experiment, dataset=dataset,
                             config_hash=hashlib.sha1(repr(config).encode()).hexdigest()[:10], **metrics)])
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

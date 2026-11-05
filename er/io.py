"""Datasets, the chosen configurations and the experiment log (dataset ∈ train, val, test).

data/medallion/silver/<dataset>.parquet          input records
data/labels/<dataset>.parquet                    truth, read only to choose and evaluate
data/medallion/gold/<dataset>/                   each dataset resolved: a run folder, as er.run writes it
data/artifacts/models/<name>.json                a final configuration (and model) as it was run
data/artifacts/experiments/leaderboard.parquet   one row per (experiment, dataset)
"""
import hashlib
import json
import time
from itertools import takewhile
from pathlib import Path

import pandas as pd

from er.config import Data

def config_hash(config: object) -> str:
    return hashlib.sha1(repr(config).encode()).hexdigest()[:10]


def load(data: Data, dataset: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Records and truth, validated: this is where outside data enters every stage."""
    records = pd.read_parquet(data.silver_dir / f"{dataset}.parquet").astype("string")
    truth = pd.read_parquet(data.labels_dir / f"{dataset}.parquet").astype("string")
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


def write_final(data: Data, name: str, config: object, model: dict | None = None, **facts: object) -> Path:
    """The configuration a stage ended with (and its fitted model, if any), plus facts such as the adopted
    changes, so a result can be traced and the configuration rebuilt."""
    data.models_dir.mkdir(parents=True, exist_ok=True)
    path = data.models_dir / f"{name}.json"
    path.write_text(json.dumps(dict(config=repr(config), config_hash=config_hash(config), model=model, **facts),
                               ensure_ascii=False, indent=1))
    return path


def append_leaderboard(data: Data, experiment: str, config: object, dataset: str, metrics: dict) -> None:
    """Append one row; the config hash tells identical configurations apart from same-named ones."""
    path = data.experiments_dir / "leaderboard.parquet"
    data.experiments_dir.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([dict(time=time.strftime("%Y-%m-%d %H:%M:%S"), experiment=experiment, dataset=dataset,
                             config_hash=config_hash(config), **metrics)])
    board = pd.concat([pd.read_parquet(path), row], ignore_index=True) if path.exists() else row
    board.to_parquet(path, index=False)


def test_evaluations(data: Data) -> pd.DataFrame:
    """Distinct configurations scored on test, per experiment family (the part before ':'). More than one per family
    means test influenced a choice and its numbers are no longer unbiased."""
    path = data.experiments_dir / "leaderboard.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["family", "configs_on_test"])
    board = pd.read_parquet(path)
    test = board[board["dataset"] == "test"].assign(family=lambda b: b["experiment"].str.split(":").str[0])
    return test.groupby("family")["config_hash"].nunique().rename("configs_on_test").reset_index()


def assert_test_scored_once(data: Data) -> None:
    """Fail loudly when a family has been scored on test with more than one configuration. Archive the leaderboard
    (data/artifacts/experiments/archive/) to start a clean pass after a deliberate change."""
    over = test_evaluations(data).query("configs_on_test > 1")
    if len(over):
        raise AssertionError(f"test was scored with several configurations: {over.to_dict('records')}")


def markdown(df: pd.DataFrame) -> str:
    """A table as GitHub markdown, for the reports."""
    rows = [list(df.columns)] + df.astype(str).to_numpy().tolist()
    return "\n".join("| " + " | ".join(map(str, r)) + " |" for r in rows[:1] + [["---"] * len(df.columns)] + rows[1:])


def table_after(text: str, heading: str) -> pd.DataFrame:
    """The first markdown table after this heading in a report (the reverse of markdown()), as strings."""
    lines = text.split(heading, 1)[1].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in takewhile(lambda x: x.startswith("|"), lines[start:])]
    return pd.DataFrame(rows[2:], columns=rows[0])

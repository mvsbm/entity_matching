"""Optuna helpers: comparator search space, SQLite storage and the optuna-dashboard web UI."""
import socket
import threading
import time
import warnings

import optuna
import optuna_dashboard
import pandas as pd

from er.config import Candidate, Comparator, ProbTune, Tune
from er.strings import FUNCTIONS

optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)  # set_metric_names


def suggest_comparators(trial: optuna.Trial | optuna.trial.FixedTrial,
                        space: dict[str, tuple[Candidate, ...]]) -> dict[str, Comparator]:
    """Per column: pick a candidate (normalization → function), then its threshold (conditional on the candidate)."""
    out = {}
    for col, candidates in space.items():
        labels = [c.label for c in candidates]
        cand = candidates[labels.index(trial.suggest_categorical(col, labels))]
        if cand.function == "exact":
            out[col] = Comparator("exact", normalize=cand.normalize)
        elif FUNCTIONS[cand.function].similarity:
            out[col] = Comparator(cand.function, trial.suggest_float(f"{col}|{cand.label}", cand.low, cand.high, step=cand.step), cand.normalize)
        else:
            out[col] = Comparator(cand.function, trial.suggest_int(f"{col}|{cand.label}", int(cand.low), int(cand.high), step=int(cand.step)), cand.normalize)
    return out


def start_dashboard(tune: Tune | ProbTune) -> optuna.storages.RDBStorage:
    """SQLite storage + optuna-dashboard in a background thread (reused if something already listens on the port)."""
    tune.storage_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{tune.storage_path}"
    storage = optuna.storages.RDBStorage(url)  # one object for study and dashboard: creating the schema twice at once fails
    with socket.socket() as probe:
        up = probe.connect_ex((tune.dashboard_host, tune.dashboard_port)) == 0
    if not up:
        threading.Thread(target=optuna_dashboard.run_server, args=(storage,), daemon=True,
                         kwargs=dict(host=tune.dashboard_host, port=tune.dashboard_port)).start()
    print(f"Optuna dashboard: http://{tune.dashboard_host}:{tune.dashboard_port}  (storage {url})")
    return storage


def new_study(tune: Tune | ProbTune, storage: optuna.storages.RDBStorage, metric_names: list[str],
              directions: list[str]) -> optuna.Study:
    study = optuna.create_study(directions=directions, sampler=optuna.samplers.TPESampler(seed=tune.seed),
                                storage=storage, study_name=f"{tune.study_prefix}_{time.strftime('%Y%m%d_%H%M%S')}")
    study.set_metric_names(metric_names)
    print(f"study {study.study_name!r} → watch it live in the dashboard")
    return study


def plain(v: object) -> object:  # SQLite storage needs plain Python numbers in user attrs
    return v.item() if hasattr(v, "item") else v


def pick_within_noise(front: pd.DataFrame, recall: str, recall_lo: str, recall_hi: str, fp_ok: str, cost: str) -> int | None:
    """The one-standard-error idea for a Pareto front: among rows that meet the FP target (`fp_ok`), take every row
    whose recall is within the best row's interval half-width of it, then the cheapest of those. Prefers a simpler
    configuration when the 'better' one is better only by noise. Returns the row's index label, or None when no row
    meets the FP target."""
    ok = front[front[fp_ok]]
    if ok.empty:
        return None
    best = ok.loc[ok[recall].idxmax()]
    near = ok[ok[recall] >= best[recall] - (best[recall_hi] - best[recall_lo]) / 2]
    return near[cost].idxmin()

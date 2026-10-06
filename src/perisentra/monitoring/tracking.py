"""MLflow helpers: local SQLite tracking store, experiment setup, model registry aliases."""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from contextlib import contextmanager

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
import mlflow
from mlflow.tracking import MlflowClient

from perisentra.config import PATHS, mlflow_uri


def _is_nan(v) -> bool:
    return isinstance(v, float) and math.isnan(v)


DEMAND_MODEL = "perisentra-demand-forecaster"
ELASTICITY_MODEL = "perisentra-price-elasticity"


def setup() -> None:
    PATHS.mlflow.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(mlflow_uri())


def experiment(name: str) -> str:
    setup()
    exp = mlflow.get_experiment_by_name(name)
    if exp is None:
        return mlflow.create_experiment(name, artifact_location=(PATHS.mlflow / "artifacts" / name).as_uri())
    return exp.experiment_id


@contextmanager
def run(experiment_name: str, run_name: str, tags: dict | None = None) -> Iterator[mlflow.ActiveRun]:
    exp_id = experiment(experiment_name)
    with mlflow.start_run(experiment_id=exp_id, run_name=run_name, tags=tags or {}) as r:
        yield r


def promote(model_name: str, run_id: str, artifact_path: str, alias: str = "champion",
            description: str = "") -> str:
    client = MlflowClient()
    try:
        client.get_registered_model(model_name)
    except Exception:  # noqa: BLE001 - registry raises a generic RESOURCE_DOES_NOT_EXIST
        client.create_registered_model(model_name, description=description)
    mv = client.create_model_version(model_name, source=f"runs:/{run_id}/{artifact_path}", run_id=run_id)
    client.set_registered_model_alias(model_name, alias, mv.version)
    return str(mv.version)


def list_runs(experiment_name: str, max_results: int = 20) -> list[dict]:
    setup()
    exp = mlflow.get_experiment_by_name(experiment_name)
    if exp is None:
        return []
    df = mlflow.search_runs([exp.experiment_id], max_results=max_results, order_by=["start_time DESC"])
    out = []
    for _, r in df.iterrows():
        out.append({
            "run_id": r["run_id"], "run_name": r.get("tags.mlflow.runName"), "status": r["status"],
            "start_time": r["start_time"], "end_time": r.get("end_time"),
            "metrics": {k[8:]: v for k, v in r.items() if k.startswith("metrics.") and not _is_nan(v)},
            "params": {k[7:]: v for k, v in r.items() if k.startswith("params.") and v is not None},
            "tags": {k[5:]: v for k, v in r.items() if k.startswith("tags.") and not k.startswith("tags.mlflow")
                     and v is not None},
        })
    return out


def registry_versions(model_name: str) -> list[dict]:
    setup()
    client = MlflowClient()
    try:
        rm = client.get_registered_model(model_name)
    except Exception:  # noqa: BLE001
        return []
    aliases = {v: a for a, v in (rm.aliases or {}).items()}
    versions = client.search_model_versions(f"name='{model_name}'")
    return sorted([{"version": v.version, "run_id": v.run_id, "created": v.creation_timestamp,
                    "alias": aliases.get(v.version), "status": v.status} for v in versions],
                  key=lambda d: int(d["version"]), reverse=True)

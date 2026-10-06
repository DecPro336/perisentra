"""Training pipeline: demand model + price elasticity, tracked in MLflow and promoted to champion."""

from __future__ import annotations

from datetime import date, timedelta

from perisentra import warehouse as wh
from perisentra.config import PATHS
from perisentra.features.build import training_frame
from perisentra.forecasting import model as demand
from perisentra.utils import get_logger, timed, write_json

log = get_logger(__name__)


def train_demand(trained_until: date | None = None, ablation: bool = True) -> demand.DemandModel:
    data_start, data_end = wh.bounds()
    trained_until = trained_until or data_end
    ctx = wh.feature_context()
    with timed(log, "Loading panel and building training features"):
        panel = wh.panel(end=trained_until)
        df = training_frame(panel, ctx, data_start + timedelta(days=28), trained_until)
    log.info("Training rows: %s (censored %.1f%%)", f"{len(df):,}", 100 * df["is_censored"].mean())
    model, report = demand.train(df, ctx, trained_until, run_ablation=ablation)
    with timed(log, "Logging to MLflow and promoting champion"):
        demand.log_to_mlflow(model, report)
    write_json(PATHS.reports / "training" / f"{model.version}.json", report)
    return model


def train_elasticity(trained_until: date | None = None):
    from perisentra.elasticity.model import fit_and_log

    return fit_and_log(trained_until)


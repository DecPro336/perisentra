"""Monitoring: feature/prediction drift (Evidently) and live forecast accuracy from the decision log."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from perisentra import warehouse as wh
from perisentra.config import PATHS, model_config
from perisentra.features.build import training_frame
from perisentra.forecasting.model import DemandModel
from perisentra.monitoring import feedback
from perisentra.utils import get_logger, timed, write_json

log = get_logger(__name__)
DRIFT_DIR = PATHS.reports / "drift"
COLUMNS = ["sig_ma28", "sig_ma7", "dow_ma4", "lag7", "temp_max", "temp_anomaly", "precipitation", "promo_pct",
           "sibling_promo_share", "censored_share28", "markdown_share28", "footfall_ma7", "footfall_trend",
           "zero_share28", "prediction", "units_sold"]


def drift_report(sample: int = 40_000, seed: int = 1) -> dict:
    from evidently import Report
    from evidently.presets import DataDriftPreset

    cfg = model_config()["monitoring"]
    _, data_end = wh.bounds()
    cur_start = data_end - timedelta(weeks=cfg["current_weeks"]) + timedelta(days=1)
    ref_start = cur_start - timedelta(weeks=cfg["reference_weeks"])
    model = DemandModel.load()
    ctx = wh.feature_context(model.weather_mask, model.categories)
    with timed(log, "Building reference/current windows for drift"):
        panel = wh.panel(start=ref_start - timedelta(days=100))
        df = training_frame(panel, ctx, ref_start, data_end, seed=seed)
        df["prediction"] = model.predict(df)
    ref = df[df["date"] < pd.Timestamp(cur_start)]
    cur = df[df["date"] >= pd.Timestamp(cur_start)]
    ref = ref.sample(min(sample, len(ref)), random_state=seed)[COLUMNS].astype(float)
    cur = cur.sample(min(sample, len(cur)), random_state=seed)[COLUMNS].astype(float)
    with timed(log, "Evidently data drift report"):
        snap = Report([DataDriftPreset()]).run(cur, ref)
        DRIFT_DIR.mkdir(parents=True, exist_ok=True)
        snap.save_html(str(DRIFT_DIR / "drift_report.html"))
        d = snap.dict()
    columns, share = [], None
    for m in d["metrics"]:
        name = m["metric_name"]
        if name.startswith("DriftedColumnsCount"):
            share = float(m["value"]["share"])
        elif name.startswith("ValueDrift"):
            col = m["config"]["column"]
            method = m["config"].get("method", "")
            thr = float(m["config"].get("threshold", 0.1))
            val = float(m["value"])
            drifted = (val < thr) if "p_value" in method else (val >= thr)
            columns.append({"column": col, "method": method, "score": val, "threshold": thr, "drifted": bool(drifted),
                            "ref_mean": float(ref[col].mean()), "cur_mean": float(cur[col].mean())})
    summary = {"reference": [ref_start, cur_start - timedelta(days=1)], "current": [cur_start, data_end],
               "drift_share": share, "drifted_columns": [c["column"] for c in columns if c["drifted"]],
               "columns": columns, "model_version": model.version, "rows": {"reference": len(ref), "current": len(cur)}}
    write_json(DRIFT_DIR / "summary.json", summary)
    return summary


def live_performance() -> dict:
    """Forecast accuracy and decision activity from the logged recommendations (engine stores)."""
    log_df = feedback.recommendation_log()
    if log_df.empty:
        return {}
    log_df["as_of_date"] = pd.to_datetime(log_df["as_of_date"].astype(str).str[:10])
    actual = wh.query("""select store_id, sku_id, date, units_sold, is_censored, is_markdown
                         from marts.fct_store_sku_daily where is_open and is_in_season""")
    actual["date"] = pd.to_datetime(actual["date"])
    m = log_df.merge(actual, left_on=["store_id", "sku_id", "as_of_date"], right_on=["store_id", "sku_id", "date"])
    m = m[~m["is_censored"] & ~m["is_markdown"]]          # the logged forecast is the no-markdown baseline
    m["week"] = m["as_of_date"].dt.to_period("W").dt.start_time
    weekly = []
    for (src, wk), g in m.groupby(["source", "week"]):
        y, p = g["units_sold"].to_numpy(float), g["forecast_today"].astype(float).to_numpy()
        weekly.append({"source": src, "week": wk, "wape": float(np.abs(y - p).sum() / max(y.sum(), 1)),
                       "bias": float((p - y).sum() / max(y.sum(), 1)), "rows": len(g),
                       "markdowns": int((g["action"] == "MARKDOWN").sum()),
                       "explored": int(g["explored"].astype(str).isin(["1", "True", "true"]).sum())})
    dec = feedback.decisions(limit=1_000_000)
    compliance = float((dec["decision"] == "ACCEPTED").mean()) if not dec.empty else None
    out = {"weekly": weekly, "compliance": compliance, "logged": len(log_df)}
    write_json(PATHS.reports / "monitoring_performance.json", out)
    return out

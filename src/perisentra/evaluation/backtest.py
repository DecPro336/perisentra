"""Rolling-origin backtest of the demand model against the store's current process and simple baselines.

For each origin o: train on data < o (same pipeline as production, one EM pass), then forecast every day
of [o, o + horizon) at every lead time 1..7 from origins inside the window. Metrics:

    WAPE / bias by lead time and family, against observed sales on uncensored days
    empirical coverage of the 80% / 95% conformal intervals

Baselines: the stores' current rule (client.yaml: a recent-sales average times the chain's weekday pattern,
blended with the same weekday over the last 3 weeks, all from capped sales), seasonal naive (same day last week)
and a 28-day moving average. Every prediction is kept in reports/backtest_predictions.parquet for audit.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import polars as pl

from perisentra import warehouse as wh
from perisentra.config import PATHS, client_config, model_config
from perisentra.features.build import KEYS, build_targets, demand_signal, history_stats, training_frame
from perisentra.forecasting import conformal
from perisentra.forecasting import model as demand
from perisentra.utils import get_logger, timed, write_json

log = get_logger(__name__)


def _eval_frame(panel: pl.DataFrame, ctx, start: date, end: date) -> pd.DataFrame:
    """All (target day, lead time) pairs in [start, end] with features as of the origin."""
    p = demand_signal(panel)
    stats = history_stats(p)
    live = pl.col("is_open") & pl.col("is_in_season")
    tgt = p.filter(live & (pl.col("date") >= start) & (pl.col("date") <= end))
    frames = []
    keep = ["store_id", "sku_id", "date", "units_sold", "is_censored", "promo_pct", "in_flyer", "sibling_promo_share",
            "temp_max", "precipitation", "is_markdown", "family"]
    for h in range(1, 8):
        frames.append(tgt.select(keep).with_columns(horizon=pl.lit(h, pl.Int32)))
    return build_targets(p, pl.concat(frames), ctx, stats)


def _legacy_forecast(panel: pl.DataFrame, X: pd.DataFrame) -> np.ndarray:
    """The stores' current rule, computed from raw (censored) sales as of the origin."""
    rule = client_config()["current_rule"]["ordering_forecast"]
    window, weight = int(rule["window_days"]), float(rule["same_weekday_weight"])
    weekday = np.array(rule["weekday_factors"], dtype=float)
    p = panel.sort(KEYS + ["date"]).with_columns(
        s=pl.when(pl.col("is_open") & pl.col("is_in_season")).then(pl.col("units_sold").cast(pl.Float64)))
    p = p.with_columns(
        m14=pl.col("s").fill_null(0).rolling_sum(window, min_samples=1).over(KEYS)
        / pl.col("s").is_not_null().cast(pl.Float64).rolling_sum(window, min_samples=1).over(KEYS))
    lag = {}
    for k in (7, 14, 21):
        lag[k] = p.select(KEYS + ["date", "s"]).with_columns(date=pl.col("date") + pl.duration(days=k)).rename({"s": f"r{k}"})
    m = pl.from_pandas(X[["store_id", "sku_id", "date", "horizon"]].astype({"store_id": int}))
    m = m.with_columns(pl.col("store_id").cast(pl.Int32), pl.col("sku_id").cast(pl.Int32), pl.col("date").cast(pl.Date))
    m = m.with_columns(origin=pl.col("date") - pl.duration(days=pl.col("horizon")))
    m = m.join(p.select(KEYS + ["date", "m14"]).rename({"date": "origin"}), on=KEYS + ["origin"], how="left")
    for k in (7, 14, 21):
        m = m.join(lag[k], on=KEYS + ["date"], how="left")
    df = m.to_pandas()
    same = df[["r7", "r14", "r21"]].mean(axis=1)
    generic = df["m14"] * weekday[pd.to_datetime(df["date"]).dt.weekday.to_numpy()]
    return np.where(same.isna(), generic, weight * same + (1 - weight) * generic)


def run(origins: list[str] | None = None, horizon_days: int | None = None) -> dict:
    cfg = model_config()
    bt = cfg["backtest"]
    origins = origins or bt["origins"]
    horizon_days = horizon_days or bt["horizon_days"]
    data_start, data_end = wh.bounds()
    fcfg = dict(cfg["forecast"])
    ctx = wh.feature_context()
    rows = []
    for o in origins:
        origin = date.fromisoformat(o)
        end = min(origin + timedelta(days=horizon_days - 1), data_end)
        with timed(log, f"Backtest origin {origin}"):
            panel = wh.panel(end=end)
            train_df = training_frame(panel.filter(pl.col("date") < origin), ctx, data_start + timedelta(days=28),
                                      origin - timedelta(days=1))
            for c, cats in ctx.categories.items():
                train_df[c] = pd.Categorical(train_df[c].astype(object) if c != "store_id" else train_df[c],
                                             categories=cats)
            cal_start = origin - timedelta(weeks=fcfg["calibration_weeks"])
            cs = pd.Timestamp(cal_start)
            pre, cal = train_df[train_df["date"] < cs], train_df[train_df["date"] >= cs]
            booster, _, _ = demand.em_fit(pre, fcfg, demand.FEATURES, iterations=1)
            pc = np.clip(booster.predict(cal[demand.FEATURES]), 0, None)
            unc = ~cal["is_censored"].to_numpy(bool)
            table = conformal.fit(cal["family"].astype(str).to_numpy()[unc], pc[unc],
                                  cal["units_sold"].to_numpy(float)[unc], fcfg["interval_levels"],
                                  fcfg["tweedie_variance_power"])
            X = _eval_frame(panel.filter(pl.col("date") <= end).filter(pl.col("date") >= origin - timedelta(days=120)),
                            ctx, origin, end)
            X = X[~X["is_markdown"].fillna(False).astype(bool)].reset_index(drop=True)
            pred = np.clip(booster.predict(X[demand.FEATURES]), 0, None)
            fam = X["family"].astype(str).to_numpy()
            lo80, hi80 = conformal.apply(table, fam, pred, 0.80, fcfg["tweedie_variance_power"])
            lo95, hi95 = conformal.apply(table, fam, pred, 0.95, fcfg["tweedie_variance_power"])
            res = pd.DataFrame({"origin": o, "store_id": X["store_id"].astype(int), "sku_id": X["sku_id"],
                                "date": pd.to_datetime(X["date"]), "horizon": X["horizon"], "family": fam,
                                "y": X["units_sold"].to_numpy(float), "censored": X["is_censored"].to_numpy(bool),
                                "model": pred, "legacy": _legacy_forecast(panel, X),
                                "seasonal_naive": X["lag7"].to_numpy(float), "ma28": X["sig_ma28"].to_numpy(float),
                                "censored_share28": X["censored_share28"].to_numpy(float),
                                "lo80": lo80, "hi80": hi80, "lo95": lo95, "hi95": hi95})
            rows.append(res)
    df = pd.concat(rows, ignore_index=True)
    report = summarise(df)
    write_json(PATHS.reports / "backtest.json", report)
    df.to_parquet(PATHS.reports / "backtest_predictions.parquet", index=False)
    return report


def summarise(df: pd.DataFrame) -> dict:
    methods = ["model", "legacy", "seasonal_naive", "ma28"]
    unc = df[~df["censored"]]
    for m in methods:
        df[m] = df[m].fillna(df["ma28"]).fillna(0)
        unc = df[~df["censored"]]

    def block(d: pd.DataFrame, target: str) -> dict:
        y = d[target].to_numpy(float)
        return {m: {"wape": demand.wape(y, d[m].to_numpy(float)), "bias": demand.bias(y, d[m].to_numpy(float))}
                for m in methods}

    out: dict = {"rows": len(df), "origins": sorted(df["origin"].unique().tolist()),
                 "observed_uncensored": block(unc, "y")}
    # on stock-out days sales are a lower bound on demand: how far above the capped sales each method forecasts
    cens = df[df["censored"]]
    out["stockout_days"] = {**block(cens, "y"), "share_of_rows": float(len(cens) / max(len(df), 1))}
    out["by_horizon"] = [{"horizon": int(h), **{m: demand.wape(g["y"].to_numpy(float), g[m].to_numpy(float))
                                                for m in methods}} for h, g in unc.groupby("horizon")]
    out["by_family"] = [{"family": f, **{m: demand.wape(g["y"].to_numpy(float), g[m].to_numpy(float)) for m in methods},
                         "units": float(g["y"].sum())} for f, g in unc.groupby("family")]
    out["by_origin"] = [{"origin": o, **{m: demand.wape(g["y"].to_numpy(float), g[m].to_numpy(float)) for m in methods}}
                        for o, g in unc.groupby("origin")]
    y = unc["y"].to_numpy(float)
    out["coverage"] = {"80": float(np.mean((y >= unc["lo80"]) & (y <= unc["hi80"]))),
                       "95": float(np.mean((y >= unc["lo95"]) & (y <= unc["hi95"])))}
    out["coverage_by_family"] = [{"family": f, "80": float(np.mean((g["y"] >= g["lo80"]) & (g["y"] <= g["hi80"]))),
                                  "95": float(np.mean((g["y"] >= g["lo95"]) & (g["y"] <= g["hi95"])))}
                                 for f, g in unc.groupby("family")]
    return out

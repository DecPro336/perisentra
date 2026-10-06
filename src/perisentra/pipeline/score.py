"""Daily scoring: forecasts -> risk -> decisions -> serving tables, recommendation log and the stores' task list."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

from perisentra import warehouse as wh
from perisentra.config import PATHS, model_config
from perisentra.decision.engine import decide
from perisentra.decision.inputs import (
    LOOKAHEAD_DAYS,
    build_engine_input,
    candidates_json,
    reference_orders_from_deliveries,
)
from perisentra.decision.rules import Rules, current_rules
from perisentra.elasticity.model import ElasticityModel
from perisentra.evaluation.pilot import live_stores
from perisentra.features.build import demand_signal, scoring_frame
from perisentra.forecasting.model import DemandModel, forecast_frame
from perisentra.monitoring import feedback
from perisentra.utils import get_logger, timed, write_json, write_parquet

log = get_logger(__name__)
SERVING = PATHS.serving
ENGINE_FEATURES = ["store_id", "sku_id", "horizon", "date", "family", "promo_pct", "is_in_season", "is_holiday", "is_pre_holiday",
                   "rain_flag", "temp_anomaly", "sig_ma28", "dow_ma4", "sibling_promo_share", "footfall_trend",
                   "temp_max", "precipitation"]


def _names() -> tuple[pd.DataFrame, pd.DataFrame]:
    return wh.products(), wh.stores()


TASK_COLUMNS = ["task_date", "run_id", "store_id", "sku_id", "product_name", "action", "discount_pct",
                "markdown_window_days", "new_price", "order_qty", "donate_units", "confidence_tier"]


def store_calendar(as_of: date) -> pd.DataFrame:
    """Which stores open on the days the engine looks ahead (holiday closures, Sunday closing)."""
    return wh.query(f"""select store_id, date_day, is_open from intermediate.int_store_calendar
                        where date_day > DATE '{as_of}' and date_day <= DATE '{as_of + timedelta(days=LOOKAHEAD_DAYS)}'""")


def score(n_paths: int | None = None, seed: int | None = None) -> dict:
    started = datetime.now()
    run_id = f"run-{started:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    n_paths = n_paths or model_config()["risk"]["n_paths"]
    data_start, data_end = wh.bounds()
    as_of = data_end + timedelta(days=1)          # this morning: the day after the last delivered business day
    seed = seed if seed is not None else int(f"{as_of:%Y%m%d}")
    dm, em, rules = DemandModel.load(), ElasticityModel.load(), current_rules()
    ctx = wh.feature_context(dm.weather_mask, dm.categories)
    products, stores = _names()

    with timed(log, f"Forecasting {as_of} .. {as_of + timedelta(days=6)}"):
        panel = wh.panel(start=data_end - timedelta(days=120))
        X = scoring_frame(panel, wh.future(), ctx, origin=data_end, horizon=7)
        fc = forecast_frame(dm, X)
    with timed(log, "Building engine inputs"):
        deliveries = wh.query(f"""select store_id, sku_id, delivery_date, qty_ordered from staging.stg_deliveries
                                  where delivery_date >= DATE '{data_end - timedelta(days=35)}'""")
        lots = wh.lots_snapshot()
        on_order = wh.query(f"""select store_id, sku_id, delivery_date, qty_ordered from staging.stg_open_orders
                                where delivery_date > DATE '{as_of}'""")
        stickers = shelf_stickers(data_end)
        calendar = store_calendar(as_of)
        inp = build_engine_input(as_of, fc, X, lots, products, calendar, dm, em,
                                 reference_orders_from_deliveries(deliveries, as_of), stickers_to_dict(stickers),
                                 on_order=on_order)
    with timed(log, f"Monte Carlo + decisions for {len(inp.meta):,} store-SKUs ({n_paths} paths)"):
        out = decide(inp, rules, n_paths=n_paths, seed=seed, run_id=run_id)

    recs = enrich(out.recommendations, products, stores)
    write_parquet(recs, SERVING / "recommendations.parquet")
    write_parquet(candidates_json(out.candidates), SERVING / "candidates.parquet")
    write_parquet(fc.assign(date=pd.to_datetime(fc["date"])), SERVING / "forecasts.parquet")
    feats = X[[c for c in ENGINE_FEATURES if c in X.columns]].copy()
    feats["store_id"] = feats["store_id"].astype(int)
    feats["family"] = feats["family"].astype(str)
    write_parquet(feats, SERVING / "engine_features.parquet")
    write_parquet(lots, SERVING / "lots.parquet")
    write_parquet(on_order, SERVING / "on_order.parquet")
    write_parquet(stickers, SERVING / "stickers.parquet")
    write_parquet(calendar, SERVING / "store_calendar.parquet")
    write_history(panel, data_end)
    meta = {"run_id": run_id, "as_of_date": as_of, "data_start": data_start, "data_end": data_end,
            "demand_model": dm.version, "elasticity_model": em.version, "rules_version": rules.version,
            "n_series": len(recs), "n_markdowns": int((recs["action"] == "MARKDOWN").sum()),
            "n_order_changes": int((recs["order_action"] != "KEEP").sum()), "n_paths": n_paths,
            "seconds": (datetime.now() - started).total_seconds(), "generated_at": datetime.now()}
    write_json(SERVING / "run_meta.json", meta)
    feedback.log_recommendations(recs, str(as_of), "daily_run", dm.version, em.version, rules.version)
    tasks = publish_task_list(recs, as_of)
    log.info("Scored %d store-SKUs for %s: %d markdowns, %d order changes, expected waste avoided %.0f; "
             "task list: %d items for %d live stores", len(recs), as_of, meta["n_markdowns"], meta["n_order_changes"],
             recs["waste_avoided_value"].sum(), tasks, len(live_stores()))
    return {**meta, "task_items": tasks}


def task_list_path(as_of: date) -> Path:
    return PATHS.outbound / "store_tasks" / f"tasks_{as_of.isoformat()}.csv"


def publish_task_list(recs: pd.DataFrame, as_of: date, stores: list[int] | None = None) -> int:
    """The morning task list for the live stores (stickers, tonight's order, donations), in the outbound exchange.
    With `stores`, only those stores' items are replaced (a re-run from the rules page)."""
    live = set(live_stores())
    scope = live if stores is None else live & set(stores)
    if not scope:
        return 0
    rows = recs[recs["store_id"].isin(scope)].assign(task_date=as_of.isoformat(), order_qty=lambda d: d["order_model"])
    rows = rows[TASK_COLUMNS].sort_values(["store_id", "sku_id"])
    path = task_list_path(as_of)
    if stores is not None and path.exists():
        kept = pd.read_csv(path)
        rows = pd.concat([kept[~kept["store_id"].isin(scope)], rows], ignore_index=True).sort_values(["store_id", "sku_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    rows.to_csv(tmp, index=False)
    tmp.replace(path)                                   # stores never see a half-written list
    return len(rows)


def shelf_stickers(data_end: date) -> pd.DataFrame:
    """Markdown stickers still on the shelf this morning: units labelled yesterday that have not expired
    (labels go on units sold by today or tomorrow, so this morning they are the units expiring tonight)."""
    return wh.query(f"""select store_id, sku_id, max(markdown_pct) as markdown_pct
                        from staging.stg_markdown_labels
                        where label_date = DATE '{data_end}' and label_source <> 'PRICE_TEST'
                        group by 1, 2""")


def stickers_to_dict(df: pd.DataFrame) -> dict:
    return {(int(r.store_id), int(r.sku_id)): np.array([r.markdown_pct], dtype=np.float32) for r in df.itertuples()}


def serving_inputs(store_id: int, sku_id: int | None = None) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """On-order quantities, shelf stickers and the store calendar saved by the last scoring run (recompute /
    what-if)."""
    def load(name: str) -> pd.DataFrame:
        path = SERVING / name
        if not path.exists():
            return pd.DataFrame(columns=["store_id", "sku_id"])
        df = pd.read_parquet(path)
        m = df["store_id"] == store_id
        if sku_id is not None:
            m &= df["sku_id"] == sku_id
        return df[m]

    calendar = pd.read_parquet(SERVING / "store_calendar.parquet")
    return load("on_order.parquet"), stickers_to_dict(load("stickers.parquet")), calendar[calendar["store_id"] == store_id]


def enrich(recs: pd.DataFrame, products: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    p = products[["sku_id", "product_name", "subfamily", "upc"]]
    s = stores[["store_id", "store_name", "city", "region", "store_format"]]
    return recs.merge(p, on="sku_id", how="left").merge(s, on="store_id", how="left")


def write_history(panel: pl.DataFrame, data_end: date, days: int = 63) -> None:
    p = demand_signal(panel.filter(pl.col("date") > data_end - timedelta(days=days)))
    cols = ["store_id", "sku_id", "date", "is_open", "is_in_season", "units_sold", "signal", "is_censored",
            "is_markdown", "markdown_pct", "promo_pct", "opening_stock", "receipts", "footfall"]
    df = p.select(cols).to_pandas()
    extra = wh.query(f"""select store_id, sku_id, date, closing_stock, waste_expired + waste_damaged as waste_units,
                                donated, units_markdown, net_sales
                         from marts.fct_store_sku_daily where date > DATE '{data_end - timedelta(days=days)}'""")
    df["date"] = pd.to_datetime(df["date"])
    extra["date"] = pd.to_datetime(extra["date"])
    df = df.merge(extra, on=["store_id", "sku_id", "date"], how="left")
    write_parquet(df, SERVING / "history.parquet")


def recompute_store(store_id: int, rules: Rules | None = None, n_paths: int = 500) -> pd.DataFrame:
    """Re-run only the decision engine for one store with the current rules (no retraining)."""
    meta = json.loads((SERVING / "run_meta.json").read_text())
    as_of = date.fromisoformat(meta["as_of_date"])
    dm, em = DemandModel.load(meta["demand_model"]), ElasticityModel.load(meta["elasticity_model"])
    rules = rules or current_rules()
    fc = pd.read_parquet(SERVING / "forecasts.parquet")
    fc = fc[fc["store_id"] == store_id].copy()
    if fc.empty:
        raise KeyError(f"unknown store {store_id}")
    fc["date"] = fc["date"].dt.date
    X = pd.read_parquet(SERVING / "engine_features.parquet")
    X = X[X["store_id"] == store_id]
    lots = pd.read_parquet(SERVING / "lots.parquet")
    lots = lots[lots["store_id"] == store_id]
    products, stores = _names()
    old = pd.read_parquet(SERVING / "recommendations.parquet")
    ref = old.loc[old["store_id"] == store_id, ["store_id", "sku_id", "order_reference"]].rename(
        columns={"order_reference": "reference_order"})
    on_order, stickers, calendar = serving_inputs(store_id)
    inp = build_engine_input(as_of, fc, X, lots, products, calendar, dm, em, ref, stickers, on_order=on_order)
    out = decide(inp, rules, n_paths=n_paths, seed=7 + store_id, run_id=meta["run_id"] + f"-r{rules.version}")
    recs = enrich(out.recommendations, products, stores)
    allrecs = pd.concat([old[old["store_id"] != store_id], recs], ignore_index=True)
    write_parquet(allrecs, SERVING / "recommendations.parquet")
    cands = pd.read_parquet(SERVING / "candidates.parquet")
    cands = pd.concat([cands[cands["store_id"] != store_id], candidates_json(out.candidates)], ignore_index=True)
    write_parquet(cands, SERVING / "candidates.parquet")
    feedback.log_recommendations(recs, str(as_of), "daily_run", dm.version, em.version, rules.version)
    publish_task_list(recs, as_of, stores=[store_id])
    return recs

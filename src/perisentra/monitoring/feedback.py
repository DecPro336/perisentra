"""Operational log (SQLite app DB): every recommendation, store decision and outcome.

The log is copied into the warehouse at each ingestion (raw.app_*), so outcomes of past decisions feed
retraining, and the logged propensities make exploration data usable for unbiased price learning.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from perisentra.config import PATHS

REC_COLUMNS = ["run_id", "as_of_date", "source", "store_id", "sku_id", "action", "discount_pct", "markdown_window_days",
               "units_to_label", "new_price", "order_recommended", "order_reference", "order_action", "donate_units",
               "expected_waste_value", "baseline_waste_value", "expected_margin", "p_waste", "p_stockout",
               "confidence_tier", "confidence_score", "explored", "propensity", "forecast_today", "demand_model",
               "elasticity_model",
               "rules_version", "created_at"]


def _con() -> sqlite3.Connection:
    PATHS.app_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PATHS.app_db, timeout=30)
    con.execute(f"create table if not exists recommendation_log ({', '.join(REC_COLUMNS)})")
    con.execute("create index if not exists ix_rec on recommendation_log (as_of_date, store_id, sku_id)")
    con.execute("""create table if not exists store_decisions (
        run_id, as_of_date, store_id, sku_id, decision, applied_action, applied_discount_pct, note, user, created_at)""")
    con.execute("create table if not exists pipeline_runs (run_id, step, status, started_at, finished_at, detail)")
    return con


def log_recommendations(recs: pd.DataFrame, as_of: str, source: str, demand_model: str, elasticity_model: str,
                        rules_version: int) -> int:
    df = recs.copy()
    df["as_of_date"] = as_of
    df["source"] = source
    df["demand_model"] = demand_model
    df["elasticity_model"] = elasticity_model
    df["rules_version"] = rules_version
    df["created_at"] = datetime.now().isoformat(timespec="seconds")
    df = df.reindex(columns=REC_COLUMNS)
    with _con() as con:
        stores = [int(s) for s in df["store_id"].unique()]
        con.execute("delete from recommendation_log where as_of_date = ? and source = ? "
                    f"and store_id in ({','.join('?' * len(stores))})", (as_of, source, *stores))
        df.to_sql("recommendation_log", con, if_exists="append", index=False)
    return len(df)


def log_decision(run_id: str, as_of: str, store_id: int, sku_id: int, decision: str, applied_action: str,
                 applied_discount_pct: float | None, note: str = "", user: str = "store") -> None:
    with _con() as con:
        con.execute("insert into store_decisions values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, as_of, store_id, sku_id, decision, applied_action, applied_discount_pct, note, user,
                     datetime.now().isoformat(timespec="seconds")))


DECISION_COLUMNS = ["run_id", "as_of_date", "store_id", "sku_id", "decision", "applied_action",
                    "applied_discount_pct", "note", "user", "created_at"]


def import_store_app(files: list[Path]) -> int:
    """Add the store app's daily decision exports (what stores did with each task-list item) to the decision log.
    Each file is imported once."""
    with _con() as con:
        con.execute("create table if not exists imported_feeds (file text primary key, rows integer, imported_at text)")
        done = {r[0] for r in con.execute("select file from imported_feeds")}
        total = 0
        for f in files:
            if f.name in done:
                continue
            df = pd.read_csv(f)
            df = df.rename(columns={"recorded_at": "created_at"}).reindex(columns=DECISION_COLUMNS)
            df.to_sql("store_decisions", con, if_exists="append", index=False)
            con.execute("insert into imported_feeds values (?, ?, ?)",
                        (f.name, len(df), datetime.now().isoformat(timespec="seconds")))
            total += len(df)
    return total


def decisions(as_of: str | None = None, store_id: int | None = None, limit: int = 500) -> pd.DataFrame:
    q, params = "select * from store_decisions where 1=1", []
    if as_of:
        q += " and as_of_date = ?"
        params.append(as_of)
    if store_id:
        q += " and store_id = ?"
        params.append(store_id)
    q += " order by created_at desc limit ?"
    params.append(limit)
    with _con() as con:
        return pd.read_sql(q, con, params=params)


def task_list_compliance(stores: list[int], start: str, end: str) -> float | None:
    """Share of task-list items the given stores reported as carried out (store app) between two dates."""
    marks = ",".join("?" * len(stores))
    with _con() as con:
        row = con.execute(f"""select avg(case when decision = 'ACCEPTED' then 1.0 else 0.0 end), count(*)
                              from store_decisions where user = 'store-app' and store_id in ({marks})
                              and substr(as_of_date, 1, 10) between ? and ?""",
                          (*[int(s) for s in stores], str(start)[:10], str(end)[:10])).fetchone()
    return float(row[0]) if row and row[1] else None


def recommendation_log(source: str | None = None) -> pd.DataFrame:
    with _con() as con:
        q = "select * from recommendation_log" + (" where source = ?" if source else "")
        return pd.read_sql(q, con, params=[source] if source else [])


def pipeline_run(run_id: str, step: str, status: str, started: datetime, detail: str = "") -> None:
    with _con() as con:
        con.execute("insert into pipeline_runs values (?, ?, ?, ?, ?, ?)",
                    (run_id, step, status, started.isoformat(timespec="seconds"),
                     datetime.now().isoformat(timespec="seconds"), detail))


def pipeline_runs(limit: int = 50) -> pd.DataFrame:
    with _con() as con:
        return pd.read_sql("select * from pipeline_runs order by started_at desc limit ?", con, params=[limit])


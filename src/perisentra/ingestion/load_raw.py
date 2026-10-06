"""Land source-system extracts into the warehouse `raw` schema (one table per source feed).

Files are read as-is, nothing is cleaned here, and every row carries `_source_file` + `_loaded_at` so dbt
staging models can dedupe and trace lineage. In Snowflake each table is staged as Parquet and loaded with
`COPY INTO raw.<table>`; the offline DuckDB copy (PERISENTRA_DBT_TARGET=duckdb) gets the same rows.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa

from perisentra.config import PATHS, client_config, warehouse_target
from perisentra.utils import get_logger, timed

log = get_logger(__name__)

# table -> (reader, glob) for the retailer's extracts, relative to the inbound exchange folder
SOURCES: dict[str, tuple[str, str]] = {
    "erp_stores": ("csv", "erp/stores.csv"),
    "erp_products": ("csv", "erp/products.csv"),
    "erp_assortment": ("csv", "erp/assortment.csv"),
    "erp_price_history": ("csv", "erp/price_history.csv"),
    "erp_store_closures": ("csv", "erp/store_closures.csv"),
    "erp_deliveries": ("parquet", "erp/deliveries/*.parquet"),
    "erp_open_orders": ("csv", "erp/open_orders.csv"),
    "pos_daily_sales": ("parquet", "pos/*.parquet"),
    "wms_stock_movements": ("parquet", "wms/movements/*.parquet"),
    "wms_cycle_counts": ("csv", "wms/cycle_counts_*.csv"),
    "quality_waste_log": ("csv", "quality/waste_log_*.csv"),
    "marketing_promo_calendar": ("csv", "marketing/promo_calendar.csv"),
    "footfall_counts": ("json", "footfall/*.jsonl"),
    "pricing_markdown_labels": ("parquet", "pricing/markdown_labels_*.parquet"),
    "pricing_price_tests": ("csv", "pricing/price_test_assignments_*.csv"),
}
# public data Perisentra fetches itself (perisentra fetch-external), relative to data/external
EXTERNAL: dict[str, tuple[str, str]] = {
    "ext_weather": ("parquet", "weather/weather.parquet"),
    "ext_holidays": ("parquet", "holidays/{country}_*.parquet"),
}


def _reader(kind: str, files: list[Path]) -> str:
    paths = "[" + ", ".join("'" + str(f).replace("'", "''") + "'" for f in files) + "]"
    if kind == "csv":
        return f"read_csv({paths}, header=true, filename=true, union_by_name=true, sample_size=-1)"
    if kind == "parquet":
        return f"read_parquet({paths}, filename=true, union_by_name=true)"
    if kind == "json":
        return f"read_json_auto({paths}, format='newline_delimited', filename=true)"
    raise ValueError(kind)


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    PATHS.warehouse.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(PATHS.warehouse), read_only=read_only)


def last_delivery() -> date | None:
    """Business date of the latest complete delivery (its manifest is written last)."""
    manifests = sorted((PATHS.inbound / "_manifests").glob("*.json"))
    return date.fromisoformat(manifests[-1].stem) if manifests else None


def delivered_files() -> set[Path]:
    """Every file listed in a delivery manifest. Files of a delivery still in progress have no manifest yet and
    are left for the next run."""
    files: set[Path] = set()
    for manifest in (PATHS.inbound / "_manifests").glob("*.json"):
        files.update(PATHS.inbound / rel for rel in json.loads(manifest.read_text())["files"])
    return files


def _source_files():
    """(table, select statement, files) for every feed that has delivered files."""
    delivered = delivered_files()
    feeds = [(t, k, PATHS.inbound, rel) for t, (k, rel) in SOURCES.items()]
    country = client_config()["client"]["country"]
    feeds += [(t, k, PATHS.external, rel.format(country=country)) for t, (k, rel) in EXTERNAL.items()]
    for table, kind, base, rel in feeds:
        files = sorted(f for f in base.glob(rel) if base != PATHS.inbound or f in delivered)
        if not files:
            log.warning("No files for %s (%s)", table, rel)
            continue
        select = (f"select * exclude (filename), filename as _source_file, current_localtimestamp() as _loaded_at "
                  f"from {_reader(kind, files)}")
        yield table, select, files


def _feedback_frames():
    """The operational recommendation / decision log (SQLite app DB), copied into raw for retraining. The store
    app's decision exports are added to the log first."""
    from perisentra.monitoring import feedback

    delivered = delivered_files()
    imported = feedback.import_store_app(sorted(f for f in PATHS.inbound.glob("storeapp/decisions_*.csv")
                                                if f in delivered))
    if imported:
        log.info("Store app: %d task-list decisions imported into the decision log", imported)
    with sqlite3.connect(PATHS.app_db) as sq:
        tables = {r[0] for r in sq.execute("select name from sqlite_master where type='table'")}
        for name in ("recommendation_log", "store_decisions"):
            if name in tables:
                df = pd.read_sql(f"select * from {name}", sq)
                df = df.astype({c: "string" for c in df.columns if df[c].dtype == object})
                df["_loaded_at"] = pd.Timestamp.now().floor("us")
                yield name, df


def _ingest_duckdb() -> list[dict]:
    audit = []
    with connect() as con:
        con.execute("create schema if not exists raw")
        for table, select, files in _source_files():
            con.execute(f"create or replace table raw.{table} as {select}")
            rows = con.execute(f"select count(*) from raw.{table}").fetchone()[0]
            audit.append({"source_table": f"raw.{table}", "files": len(files), "row_count": rows,
                          "loaded_at": datetime.now()})
        fb = 0
        for name, df in _feedback_frames():
            con.register("_fb", df)
            con.execute(f"create or replace table raw.app_{name} as select * from _fb")
            con.unregister("_fb")
            fb += len(df)
        audit.append({"source_table": "raw.app_* (feedback)", "files": 1 if fb else 0, "row_count": fb,
                      "loaded_at": datetime.now()})
        log_df = pd.DataFrame(audit)
        cols = {r[0] for r in con.execute("select column_name from information_schema.columns "
                                          "where table_schema = 'raw' and table_name = '_ingestion_log'").fetchall()}
        for old, new in (("table", "source_table"), ("rows", "row_count")):   # names reserved in Snowflake
            if old in cols:
                con.execute(f'alter table raw._ingestion_log rename column "{old}" to {new}')
        con.register("_audit", log_df)
        con.execute("create table if not exists raw._ingestion_log as select * from _audit where false")
        con.execute("insert into raw._ingestion_log by name select * from _audit")
        con.unregister("_audit")
    return audit


def _ingest_snowflake() -> list[dict]:
    from perisentra import snowflake_io

    audit = []
    with duckdb.connect() as reader:            # files are parsed exactly as in the local path, then COPY INTO
        for table, select, files in _source_files():
            rows = snowflake_io.load_table(reader.execute(select).to_arrow_table(), "raw", table)
            audit.append({"source_table": f"raw.{table}", "files": len(files), "row_count": rows,
                          "loaded_at": datetime.now()})
            log.info("  COPY INTO raw.%-28s rows=%s", table, f"{rows:,}")
    fb = 0
    for name, df in _feedback_frames():
        fb += snowflake_io.load_table(pa.Table.from_pandas(df, preserve_index=False), "raw", f"app_{name}")
    audit.append({"source_table": "raw.app_* (feedback)", "files": 1 if fb else 0, "row_count": fb,
                  "loaded_at": datetime.now()})
    snowflake_io.load_table(pa.Table.from_pandas(pd.DataFrame(audit), preserve_index=False), "raw",
                            "_ingestion_log", replace=False)
    return audit


def ingest_all() -> pd.DataFrame:
    if last_delivery() is None:
        raise FileNotFoundError(f"no complete delivery in {PATHS.inbound} (each business day ends with a manifest)")
    target = warehouse_target()
    with timed(log, f"Ingesting source extracts into raw schema ({target})"):
        audit = _ingest_snowflake() if target == "snowflake" else _ingest_duckdb()
    for r in audit:
        log.info("  %-34s files=%-3d rows=%s", r["source_table"], r["files"], f"{r['row_count']:,}")
    return pd.DataFrame(audit)

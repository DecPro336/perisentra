"""Read-only access to the dbt marts: Snowflake, or the offline DuckDB copy when PERISENTRA_DBT_TARGET=duckdb."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import duckdb
import pandas as pd
import polars as pl

from perisentra.config import PATHS, warehouse_target
from perisentra.features.build import FUTURE_COLUMNS, PANEL_COLUMNS, FeatureContext, climate_normals


@contextmanager
def connection(retries: int = 20) -> Iterator[duckdb.DuckDBPyConnection]:
    """Read-only connection; waits briefly if a pipeline step currently holds the write lock."""
    for attempt in range(retries):
        try:
            con = duckdb.connect(str(PATHS.warehouse), read_only=True)
            break
        except duckdb.IOException:
            if attempt == retries - 1:
                raise
            time.sleep(0.5)
    try:
        yield con
    finally:
        con.close()


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    if warehouse_target() == "snowflake":
        from perisentra import snowflake_io

        return snowflake_io.query(sql, params)
    with connection() as con:
        return con.execute(sql, params or []).df()


def _polars(sql: str) -> pl.DataFrame:
    if warehouse_target() == "snowflake":
        from perisentra import snowflake_io

        return pl.from_arrow(snowflake_io.query_arrow(sql))
    with connection() as con:
        return con.execute(sql).pl()


def bounds() -> tuple[date, date]:
    df = query("select data_start, data_end from intermediate.int_bounds")
    return pd.Timestamp(df.iloc[0, 0]).date(), pd.Timestamp(df.iloc[0, 1]).date()


def panel(start: date | None = None, end: date | None = None, stores: list[int] | None = None) -> pl.DataFrame:
    cols = ", ".join(PANEL_COLUMNS + ["family"])
    where = ["1=1"]
    if start:
        where.append(f"date >= DATE '{start}'")
    if end:
        where.append(f"date <= DATE '{end}'")
    if stores:
        where.append(f"store_id in ({','.join(map(str, stores))})")
    df = _polars(f"select {cols} from marts.fct_store_sku_daily where {' and '.join(where)}")
    df = df.with_columns(pl.col(pl.Decimal).cast(pl.Float64))
    return df.with_columns(pl.col("date").cast(pl.Date), pl.col("store_id").cast(pl.Int32),
                           pl.col("sku_id").cast(pl.Int32))


def future() -> pl.DataFrame:
    df = _polars(f"select {', '.join(FUTURE_COLUMNS)} from marts.fct_store_sku_future")
    return df.with_columns(pl.col("date").cast(pl.Date), pl.col("store_id").cast(pl.Int32),
                           pl.col("sku_id").cast(pl.Int32))


def products() -> pd.DataFrame:
    return query("select * from marts.dim_product")


def stores() -> pd.DataFrame:
    return query("select * from marts.dim_store")


def calendar() -> pd.DataFrame:
    df = query("select * from intermediate.int_calendar")
    df["date_day"] = pd.to_datetime(df["date_day"]).dt.date
    return df


def weather() -> pd.DataFrame:
    return query("select * from staging.stg_weather")


def lots_snapshot() -> pd.DataFrame:
    return query("select * from marts.fct_lot_snapshot")


def feature_context(weather_mask: list[str] | None = None, categories: dict | None = None) -> FeatureContext:
    prods = products().rename(columns={"regular_price": "regular_price"})
    return FeatureContext(products=prods, stores=stores(), calendar=calendar(), climate=climate_normals(weather()),
                          weather_mask=weather_mask or [], categories=categories or {})

"""Snowflake access: the project's warehouse (unless PERISENTRA_DBT_TARGET=duckdb selects the offline copy).

Authentication is key-pair only (service user, no password): the private key file stays on the machine and its
path is read from SNOWFLAKE_PRIVATE_KEY_PATH. Reads go through Arrow; loads stage Parquet files in the table
stage and run `COPY INTO`, the same path a production ingestion job would take.
"""

from __future__ import annotations

import atexit
import logging
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from perisentra import config  # noqa: F401  (loads .env: account, user, key path)
from perisentra.utils import get_logger

log = get_logger(__name__)
logging.getLogger("snowflake.connector").setLevel(logging.WARNING)   # one INFO banner per connection otherwise

ROWS_PER_FILE = 1_000_000          # several files per table so COPY INTO loads them in parallel
SESSION_GONE = {390111, 390112, 390114}   # session / master token expired: reconnect and retry the read

_session = None
_session_lock = threading.RLock()


def settings() -> dict:
    missing = [v for v in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH") if not os.environ.get(v)]
    if missing:
        raise RuntimeError(f"Snowflake target selected but {', '.join(missing)} not set (see .env.example)")
    return {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "private_key_file": str(Path(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]).expanduser()),
        "role": os.environ.get("SNOWFLAKE_ROLE", "TRANSFORMER"),
        "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "TRANSFORM_WH"),
        "database": os.environ.get("SNOWFLAKE_DATABASE", "PERISENTRA"),
    }


def _open():
    import snowflake.connector

    return snowflake.connector.connect(**settings(), paramstyle="qmark", client_session_keep_alive=True,
                                       session_parameters={"QUERY_TAG": "perisentra",
                                                           "TIMEZONE": "America/New_York", "WEEK_START": 1})


@contextmanager
def connection() -> Iterator:
    """The process's Snowflake session, opened on first use and then reused: a key-pair login takes about a
    second, which would otherwise be paid by every API request. Calls are serialised on the session."""
    global _session
    with _session_lock:
        if _session is None or _session.is_closed():
            _session = _open()
        yield _session


@atexit.register
def reset() -> None:
    """Close the shared session (at exit, or to force a fresh login)."""
    from snowflake.connector.errors import Error

    global _session
    with _session_lock:
        if _session is not None:
            with suppress(Error):                     # already closed server-side
                _session.close()
        _session = None


def _arrow(cur) -> pa.Table:
    """Result set as Arrow with lower-case column names (Snowflake folds unquoted identifiers to upper case).
    Integers come back in the narrowest type that fits (int8, int16, ...): widen them so later arithmetic
    cannot overflow, and turn NUMBER(p, s) into int64 / float64 like DuckDB returns."""
    tbl = cur.fetch_arrow_all()
    if tbl is None:                                   # empty result: build the schema from the cursor description
        return pa.table({d.name.lower(): pa.array([], pa.string()) for d in cur.description})
    cols = []
    for col in tbl.columns:
        t = col.type
        if pa.types.is_integer(t):
            col = col.cast(pa.int64())
        elif pa.types.is_decimal(t):
            col = col.cast(pa.int64() if t.scale == 0 else pa.float64())
        cols.append(col)
    return pa.table(cols, names=[c.lower() for c in tbl.column_names])


def query_arrow(sql: str, params: list | None = None) -> pa.Table:
    from snowflake.connector.errors import Error

    for attempt in (1, 2):
        try:
            with connection() as con:
                cur = con.cursor()
                cur.execute(sql, params or [])
                return _arrow(cur)
        except Error as exc:                          # reads are idempotent: retry once on an expired session
            if attempt == 2 or getattr(exc, "errno", None) not in SESSION_GONE:
                raise
            reset()
    raise AssertionError("unreachable")


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    # dates as datetime64 (like DuckDB's .df()), not Python date objects
    return query_arrow(sql, params).to_pandas(date_as_object=False)


def _sf_type(t: pa.DataType) -> str:
    if pa.types.is_boolean(t):
        return "BOOLEAN"
    if pa.types.is_integer(t):
        return "NUMBER(38,0)"
    if pa.types.is_floating(t):
        return "FLOAT"
    if pa.types.is_decimal(t):
        return f"NUMBER({t.precision},{t.scale})"
    if pa.types.is_date(t):
        return "DATE"
    if pa.types.is_timestamp(t):
        return "TIMESTAMP_TZ" if t.tz else "TIMESTAMP_NTZ"
    return "VARCHAR"


def _loadable(tbl: pa.Table) -> pa.Table:
    """Types Parquet → COPY INTO maps cleanly: microsecond timestamps, everything exotic as text."""
    cols = []
    for name, col in zip(tbl.column_names, tbl.columns):
        t = col.type
        if pa.types.is_timestamp(t):
            col = col.cast(pa.timestamp("us", tz=t.tz))
        elif not (pa.types.is_boolean(t) or pa.types.is_integer(t) or pa.types.is_floating(t)
                  or pa.types.is_decimal(t) or pa.types.is_date(t) or pa.types.is_string(t)):
            col = col.cast(pa.string())               # dictionary, large/view strings, nested types
        cols.append(col)
    return pa.table(cols, names=[n.lower() for n in tbl.column_names])


def load_table(tbl: pa.Table, schema: str, table: str, replace: bool = True) -> int:
    """Create (or append to) `schema.table` from an Arrow table via PUT to the table stage + COPY INTO."""
    tbl = _loadable(tbl)
    ddl = ", ".join(f"{name} {_sf_type(t)}" for name, t in zip(tbl.column_names, tbl.schema.types))
    with connection() as con, tempfile.TemporaryDirectory() as tmp:
        cur = con.cursor()
        cur.execute(f"create schema if not exists {schema}")
        cur.execute(f"create {'or replace ' if replace else ''}table {'' if replace else 'if not exists '}"
                    f"{schema}.{table} ({ddl})")
        stage = f"@{schema}.%{table}"
        cur.execute(f"remove {stage}")
        for i, start in enumerate(range(0, max(tbl.num_rows, 1), ROWS_PER_FILE)):
            path = Path(tmp) / f"{table}_{i:03d}.parquet"
            pq.write_table(tbl.slice(start, ROWS_PER_FILE), path)
        cur.execute(f"put 'file://{tmp}/{table}_*.parquet' {stage} auto_compress = false overwrite = true parallel = 8")
        cur.execute(f"""copy into {schema}.{table} from {stage}
                        file_format = (type = parquet use_logical_type = true binary_as_text = false)
                        match_by_column_name = case_insensitive purge = true""")
        loaded = sum(int(r[3] or 0) for r in cur.fetchall() if len(r) > 3 and str(r[1]).upper() == "LOADED")
    return loaded

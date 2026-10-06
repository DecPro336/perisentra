"""Snowflake I/O without an account: the SQL sent and the type handling, against a fake connection."""

from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from perisentra import snowflake_io


class FakeCursor:
    def __init__(self, log, result=None):
        self.log, self.result, self.description = log, result, []
        self.staged_rows = 0

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.log.append(sql)
        if sql.startswith("put "):                      # count rows in the files that would be uploaded
            pattern = sql.split("'file://")[1].split("'")[0]
            self.staged_rows = sum(pq.read_metadata(f).num_rows for f in Path(pattern).parent.glob(Path(pattern).name))
        return self

    def fetchall(self):
        last = self.log[-1]
        if last.startswith("copy into"):
            return [("file_000.parquet", "LOADED", self.staged_rows, self.staged_rows, 1, 0, None, None, None, None)]
        return []

    def fetch_arrow_all(self):
        return self.result


class FakeConnection:
    def __init__(self, log, result=None):
        self.log, self.result = log, result

    def cursor(self):
        return FakeCursor(self.log, self.result)


def _fake(monkeypatch, result=None):
    log = []

    @contextmanager
    def connection():
        yield FakeConnection(log, result)

    monkeypatch.setattr(snowflake_io, "connection", connection)
    monkeypatch.setattr(snowflake_io, "ROWS_PER_FILE", 2)
    return log


def test_load_table_stages_parquet_and_copies_into(monkeypatch):
    log = _fake(monkeypatch)
    tbl = pa.table({"Store_ID": [1, 2, 3], "sale_date": [date(2026, 1, 1)] * 3, "net_amount": [1.5, 2.0, 0.0],
                    "_loaded_at": pa.array([datetime(2026, 1, 1, 5)] * 3, pa.timestamp("ns")),
                    "label": pa.array(["a", "b", "a"]).dictionary_encode()})
    loaded = snowflake_io.load_table(tbl, "raw", "pos_daily_sales")
    assert loaded == 3                                                           # 2 files of <= 2 rows
    ddl = next(s for s in log if s.startswith("create or replace table raw.pos_daily_sales"))
    assert "store_id NUMBER(38,0)" in ddl and "sale_date DATE" in ddl and "net_amount FLOAT" in ddl
    assert "_loaded_at TIMESTAMP_NTZ" in ddl and "label VARCHAR" in ddl
    assert any(s.startswith("put 'file://") and "@raw.%pos_daily_sales" in s for s in log)
    copy = next(s for s in log if s.startswith("copy into raw.pos_daily_sales"))
    assert "match_by_column_name = case_insensitive" in copy and "use_logical_type = true" in copy


def test_append_mode_keeps_the_table(monkeypatch):
    log = _fake(monkeypatch)
    snowflake_io.load_table(pa.table({"source_table": ["raw.x"], "row_count": [5]}), "raw", "_ingestion_log",
                            replace=False)
    assert any(s.startswith("create table if not exists raw._ingestion_log") for s in log)
    assert not any("create or replace" in s for s in log)


def test_query_results_are_widened_and_lower_cased(monkeypatch):
    result = pa.table({"STORE_ID": pa.array([1, 2], pa.int8()), "UNITS": pa.array([120, 7], pa.int16()),
                       "PRICE": pa.array([1, 2], pa.decimal128(10, 2)), "DAY": pa.array([date(2026, 1, 1)] * 2)})
    _fake(monkeypatch, result)
    tbl = snowflake_io.query_arrow("select 1")
    assert tbl.column_names == ["store_id", "units", "price", "day"]
    assert tbl.schema.field("store_id").type == pa.int64() and tbl.schema.field("price").type == pa.float64()
    df = snowflake_io.query("select 1")
    assert str(df["day"].dtype).startswith("datetime64")                  # like DuckDB's .df()


def test_missing_settings_fail_with_a_clear_message(monkeypatch):
    for v in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(RuntimeError, match="SNOWFLAKE_ACCOUNT"):
        snowflake_io.settings()


def test_snowflake_is_the_default_warehouse(monkeypatch):
    from perisentra.config import warehouse_target

    monkeypatch.delenv("PERISENTRA_DBT_TARGET", raising=False)
    assert warehouse_target() == "snowflake"
    monkeypatch.setenv("PERISENTRA_DBT_TARGET", "DuckDB")
    assert warehouse_target() == "duckdb"
    monkeypatch.setenv("PERISENTRA_DBT_TARGET", "postgres")
    with pytest.raises(ValueError, match="PERISENTRA_DBT_TARGET"):
        warehouse_target()

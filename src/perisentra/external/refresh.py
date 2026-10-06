"""Public data Perisentra fetches itself: weather at every store and the public-holiday calendar.

Store locations come from the retailer's store master (exchange/inbound/erp/stores.csv) and the weather history
starts five weeks before the first POS day, so features have their look-back from day one.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd

from perisentra.config import PATHS, client_config
from perisentra.external.holidays_api import load_or_fetch_holidays
from perisentra.external.open_meteo import FORECAST_DAYS, update_weather
from perisentra.utils import get_logger

log = get_logger(__name__)
LOOKBACK_DAYS = 35


def store_locations() -> list[dict]:
    stores = pd.read_csv(PATHS.inbound / "erp" / "stores.csv")
    return [{"location_id": int(r.store_id), "lat": float(r.lat), "lon": float(r.lon)} for r in stores.itertuples()]


def first_business_day() -> date:
    first = duckdb.sql(f"select min(business_date) from read_parquet('{PATHS.inbound / 'pos' / '*.parquet'}')").fetchone()[0]
    return pd.Timestamp(first).date()


def refresh_external(today: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    today = today or date.today()
    start = first_business_day() - timedelta(days=LOOKBACK_DAYS)
    weather = update_weather(store_locations(), start, today)
    last = today + timedelta(days=FORECAST_DAYS)
    holidays = load_or_fetch_holidays(list(range(start.year, last.year + 1)), client_config()["client"]["country"])
    log.info("Holidays: %d days (%d -> %d)", len(holidays), start.year, last.year)
    return weather, holidays

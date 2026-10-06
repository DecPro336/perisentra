"""Public holidays from the Nager.Date API, with the `holidays` package as offline fallback."""

from __future__ import annotations

import httpx
import pandas as pd

from perisentra.config import PATHS
from perisentra.utils import get_logger

log = get_logger(__name__)

NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"


# Fixed-date US holidays: Nager.Date returns the *observed* federal date (e.g. Friday 3 July when the 4th is
# a Saturday). Shopping peaks follow the actual date, so those are moved back to it.
FIXED_DATE = {"US": {"New Year's Day": (1, 1), "Juneteenth National Independence Day": (6, 19),
                     "Independence Day": (7, 4), "Veterans Day": (11, 11), "Christmas Day": (12, 25)}}


def _from_api(year: int, country: str) -> pd.DataFrame:
    resp = httpx.get(NAGER_URL.format(year=year, country=country), timeout=30)
    resp.raise_for_status()
    fixed = FIXED_DATE.get(country, {})
    # nationwide holidays only; the local name is the spelling people use (e.g. "Labor Day")
    rows = []
    for h in resp.json():
        if not h.get("global", True):
            continue
        d = h["date"]
        if h["localName"] in fixed:
            m, dd = fixed[h["localName"]]
            d = f"{year}-{m:02d}-{dd:02d}"
        rows.append({"date": d, "name": h["localName"], "local_name": h["localName"], "source": "nager.date"})
    return pd.DataFrame(rows)


def _from_package(year: int, country: str) -> pd.DataFrame:
    import holidays

    cal = holidays.country_holidays(country, years=year, observed=False)
    return pd.DataFrame([{"date": d.isoformat(), "name": n, "local_name": n, "source": "holidays-pkg"}
                         for d, n in sorted(cal.items())])


def load_or_fetch_holidays(years: list[int], country: str = "US", refresh: bool = False) -> pd.DataFrame:
    frames = []
    for year in years:
        cache = PATHS.external / "holidays" / f"{country}_{year}.parquet"
        if cache.exists() and not refresh:
            frames.append(pd.read_parquet(cache))
            continue
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            df = _from_api(year, country)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Nager.Date unavailable for %s (%s) - using holidays package", year, exc)
            df = _from_package(year, country)
        df["country"] = country
        df.to_parquet(cache, index=False)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.date
    return out.drop_duplicates("date").sort_values("date").reset_index(drop=True)

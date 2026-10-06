"""Real-world inputs of the simulated world: daily weather (Open-Meteo) and US public holidays (Nager.Date).

Weather is kept in one incremental store: archived days (ERA5) never change; recent days and the forecast
window are refreshed from the forecast API on every run. Without network, missing days get a deterministic
climatology so the world keeps running (flagged `source = fallback`).
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import httpx
import numpy as np
import pandas as pd

from fernbrook.settings import PATHS, get_logger

log = get_logger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
DAILY_VARS = "temperature_2m_max,temperature_2m_min,precipitation_sum"
BATCH = 5                 # locations per request (keeps each call well under the per-minute quota)
ARCHIVE_LAG_DAYS = 6      # the ERA5 archive trails real time by about this much
WEATHER_COLUMNS = ["location_id", "date", "temp_max", "temp_min", "precipitation", "source"]
# Nager.Date returns the *observed* federal date for fixed-date holidays (e.g. Friday 3 July when the 4th is a
# Saturday); shopping peaks follow the actual date
FIXED_DATE = {"US": {"New Year's Day": (1, 1), "Juneteenth National Independence Day": (6, 19),
                     "Independence Day": (7, 4), "Veterans Day": (11, 11), "Christmas Day": (12, 25)}}


# ----------------------------------------------------------------------------------------------
# weather
# ----------------------------------------------------------------------------------------------
def _get(url: str, params: dict, retries: int = 4) -> list[dict]:
    for attempt in range(retries):
        try:
            resp = httpx.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            resp.raise_for_status()
            body = resp.json()
            return body if isinstance(body, list) else [body]
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Open-Meteo request failed (%s), attempt %d", exc, attempt + 1)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Open-Meteo unavailable: {url}")


def _frames(payloads: list[dict], locations: list[dict], source: str) -> pd.DataFrame:
    rows = [pd.DataFrame({"location_id": loc["location_id"], "date": pd.to_datetime(body["daily"]["time"]).date,
                          "temp_max": body["daily"]["temperature_2m_max"],
                          "temp_min": body["daily"]["temperature_2m_min"],
                          "precipitation": body["daily"]["precipitation_sum"], "source": source})
            for loc, body in zip(locations, payloads)]
    return pd.concat(rows, ignore_index=True)


def _fetch(locations: list[dict], start: date | None, end: date | None, recent: bool) -> pd.DataFrame:
    frames = []
    for i in range(0, len(locations), BATCH):
        chunk = locations[i:i + BATCH]
        params = {"latitude": ",".join(str(x["lat"]) for x in chunk),
                  "longitude": ",".join(str(x["lon"]) for x in chunk),
                  "daily": DAILY_VARS, "timezone": "auto", "temperature_unit": "fahrenheit",
                  "precipitation_unit": "inch"}
        if recent:
            frames.append(_frames(_get(FORECAST_URL, {**params, "past_days": 14, "forecast_days": 16}), chunk,
                                  "open-meteo-forecast"))
        else:
            frames.append(_frames(_get(ARCHIVE_URL, {**params, "start_date": start.isoformat(),
                                                     "end_date": end.isoformat()}), chunk, "open-meteo-archive"))
        time.sleep(1.0)
    return pd.concat(frames, ignore_index=True).dropna(subset=["temp_max"])


def climatology(locations: list[dict], days: list[date], seed: int = 7) -> pd.DataFrame:
    """Deterministic continental-climate stand-in for days the APIs cannot provide."""
    rng = np.random.default_rng(seed)
    doy = np.array([d.timetuple().tm_yday for d in days])
    out = []
    for loc in locations:
        mean = 60.0 - 1.4 * (float(loc["lat"]) - 41) + 22.0 * np.sin(2 * np.pi * (doy - 110) / 365.25)
        tmax = mean + rng.normal(0, 4.5, len(days))
        rain = np.where(rng.random(len(days)) < 0.32, rng.gamma(0.8, 0.25, len(days)), 0.0)
        out.append(pd.DataFrame({"location_id": loc["location_id"], "date": days, "temp_max": tmax.round(1),
                                 "temp_min": (tmax - 14 - rng.random(len(days)) * 6).round(1),
                                 "precipitation": rain.round(2), "source": "fallback"}))
    return pd.concat(out, ignore_index=True)


def weather(locations: list[dict], start: date, end: date, today: date | None = None) -> pd.DataFrame:
    """Daily weather for [start, end] at each location, updating the local store from the APIs as needed."""
    today = today or date.today()
    path = PATHS.cache / "weather.parquet"
    store = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=WEATHER_COLUMNS)
    store["date"] = pd.to_datetime(store["date"]).dt.date
    ids = {x["location_id"] for x in locations}
    have = store[store["location_id"].isin(ids)]
    archive_until = today - timedelta(days=ARCHIVE_LAG_DAYS)
    fresh = []
    try:
        archived = set(zip(have.loc[have["source"] == "open-meteo-archive", "location_id"],
                           have.loc[have["source"] == "open-meteo-archive", "date"]))
        gap = [d for d in pd.date_range(start, min(end, archive_until)).date
               if any((x["location_id"], d) not in archived for x in locations)]
        if gap:
            fresh.append(_fetch(locations, min(gap), max(gap), recent=False))
        if end >= today - timedelta(days=14):
            fresh.append(_fetch(locations, None, None, recent=True))
    except RuntimeError as exc:
        log.warning("%s: days without data get the climatological fallback", exc)
    if fresh:
        new = pd.concat(fresh, ignore_index=True)
        new["priority"] = (new["source"] == "open-meteo-archive").astype(int) + 1
        old = store.assign(priority=(store["source"] == "open-meteo-archive").astype(int) * 2)
        store = (pd.concat([old, new], ignore_index=True).sort_values("priority", ascending=False)
                 .drop_duplicates(["location_id", "date"]).drop(columns="priority")
                 .sort_values(["location_id", "date"]).reset_index(drop=True))
        PATHS.cache.mkdir(parents=True, exist_ok=True)
        store[WEATHER_COLUMNS].to_parquet(path, index=False)
    days = list(pd.date_range(start, end).date)
    full = pd.MultiIndex.from_product([sorted(ids), days], names=["location_id", "date"])
    out = store.set_index(["location_id", "date"]).reindex(full)
    missing = out["temp_max"].isna() & (out.index.get_level_values("date") <= today + timedelta(days=15))
    if missing.any():
        fb = climatology(locations, days).set_index(["location_id", "date"])
        out.loc[missing, fb.columns] = fb.loc[missing[missing].index].to_numpy()
    return out.reset_index()


# ----------------------------------------------------------------------------------------------
# holidays
# ----------------------------------------------------------------------------------------------
def _holidays_from_api(year: int, country: str) -> pd.DataFrame:
    resp = httpx.get(NAGER_URL.format(year=year, country=country), timeout=30)
    resp.raise_for_status()
    fixed = FIXED_DATE.get(country, {})
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


def _holidays_from_package(year: int, country: str) -> pd.DataFrame:
    import holidays as hol

    cal = hol.country_holidays(country, years=year, observed=False)
    return pd.DataFrame([{"date": d.isoformat(), "name": n, "local_name": n, "source": "holidays-pkg"}
                         for d, n in sorted(cal.items())])


def public_holidays(years: list[int], country: str) -> pd.DataFrame:
    frames = []
    for year in years:
        path = PATHS.cache / "holidays" / f"{country}_{year}.parquet"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                df = _holidays_from_api(year, country)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Nager.Date unavailable for %s (%s): using the holidays package", year, exc)
                df = _holidays_from_package(year, country)
            df["country"] = country
            df.to_parquet(path, index=False)
        frames.append(pd.read_parquet(path))
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.date
    return out.drop_duplicates("date").sort_values("date").reset_index(drop=True)

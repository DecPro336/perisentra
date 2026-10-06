"""Open-Meteo client: daily weather at each store, kept in one incremental store (°F, inches).

Archived days (ERA5, which trails real time by about six days) never change. The most recent days and the
forecast horizon come from the forecast API and are refreshed on every run, so each morning's forecasts use the
latest weather forecast. Without network, missing days get a deterministic climatology and are flagged
`source = 'fallback'`, which the data-quality page shows.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import httpx
import numpy as np
import pandas as pd

from perisentra.config import PATHS
from perisentra.utils import get_logger

log = get_logger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_VARS = "temperature_2m_max,temperature_2m_min,precipitation_sum"
BATCH = 5                 # locations per request (keeps each call well under the per-minute quota)
ARCHIVE_LAG_DAYS = 6
FORECAST_DAYS = 16
COLUMNS = ["location_id", "date", "temp_max", "temp_min", "precipitation", "source"]
STORE = PATHS.external / "weather" / "weather.parquet"


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
    return pd.concat([pd.DataFrame({
        "location_id": loc["location_id"], "date": pd.to_datetime(body["daily"]["time"]).date,
        "temp_max": body["daily"]["temperature_2m_max"], "temp_min": body["daily"]["temperature_2m_min"],
        "precipitation": body["daily"]["precipitation_sum"], "source": source,
    }) for loc, body in zip(locations, payloads)], ignore_index=True)


def _fetch(locations: list[dict], start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """Archive for [start, end]; without dates, the last 14 days and the forecast horizon."""
    frames = []
    for i in range(0, len(locations), BATCH):
        chunk = locations[i:i + BATCH]
        params = {"latitude": ",".join(str(x["lat"]) for x in chunk),
                  "longitude": ",".join(str(x["lon"]) for x in chunk),
                  "daily": DAILY_VARS, "timezone": "auto", "temperature_unit": "fahrenheit",
                  "precipitation_unit": "inch"}
        if start is None:
            frames.append(_frames(_get(FORECAST_URL, {**params, "past_days": 14, "forecast_days": FORECAST_DAYS}),
                                  chunk, "open-meteo-forecast"))
        else:
            frames.append(_frames(_get(ARCHIVE_URL, {**params, "start_date": start.isoformat(),
                                                     "end_date": end.isoformat()}), chunk, "open-meteo-archive"))
        time.sleep(1.0)
    return pd.concat(frames, ignore_index=True).dropna(subset=["temp_max"])


def climatology_fallback(locations: list[dict], start: date, end: date, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    doy = days.dayofyear.to_numpy()
    out = []
    for loc in locations:
        mean = 60.0 - 1.4 * (float(loc["lat"]) - 41) + 22.0 * np.sin(2 * np.pi * (doy - 110) / 365.25)
        noise = np.zeros(len(days))
        for t in range(1, len(days)):
            noise[t] = 0.7 * noise[t - 1] + rng.normal(0, 4.5)
        tmax = mean + noise
        rain = np.where(rng.random(len(days)) < 0.32, rng.gamma(0.8, 0.25, len(days)), 0.0)
        out.append(pd.DataFrame({"location_id": loc["location_id"], "date": days.date, "temp_max": tmax.round(1),
                                 "temp_min": (tmax - 14 - rng.random(len(days)) * 6).round(1),
                                 "precipitation": rain.round(2), "source": "fallback"}))
    return pd.concat(out, ignore_index=True)


def update_weather(locations: list[dict], start: date, today: date | None = None) -> pd.DataFrame:
    """Bring the store up to date for [start, today + forecast horizon] and return that window."""
    today = today or date.today()
    end = today + timedelta(days=FORECAST_DAYS - 1)
    store = pd.read_parquet(STORE) if STORE.exists() else pd.DataFrame(columns=COLUMNS)
    store["date"] = pd.to_datetime(store["date"]).dt.date
    ids = sorted({x["location_id"] for x in locations})
    archived = set(zip(store.loc[store["source"] == "open-meteo-archive", "location_id"],
                       store.loc[store["source"] == "open-meteo-archive", "date"]))
    archive_until = today - timedelta(days=ARCHIVE_LAG_DAYS)
    gap = [d for d in pd.date_range(start, archive_until).date if any((i, d) not in archived for i in ids)]
    fresh = []
    try:
        if gap:
            fresh.append(_fetch(locations, min(gap), max(gap)))
        fresh.append(_fetch(locations))
    except RuntimeError as exc:
        log.error("%s: missing days get the climatological fallback", exc)
    if fresh:
        new = pd.concat(fresh, ignore_index=True)
        new["priority"] = (new["source"] == "open-meteo-archive").astype(int) + 1
        old = store.assign(priority=(store["source"] == "open-meteo-archive").astype(int) * 2)
        store = (pd.concat([old, new], ignore_index=True).sort_values("priority", ascending=False)
                 .drop_duplicates(["location_id", "date"]).drop(columns="priority"))
    full = pd.MultiIndex.from_product([ids, pd.date_range(start, end).date], names=["location_id", "date"])
    window = store.set_index(["location_id", "date"]).reindex(full)
    missing = window["temp_max"].isna()
    if missing.any():
        fb = climatology_fallback(locations, start, end).set_index(["location_id", "date"])
        window.loc[missing, COLUMNS[2:]] = fb.loc[missing[missing].index, COLUMNS[2:]].to_numpy()
        log.warning("Weather: %d location-days filled with the climatological fallback", int(missing.sum()))
    window = window.reset_index()
    rest = store[~store.set_index(["location_id", "date"]).index.isin(window.set_index(["location_id", "date"]).index)]
    STORE.parent.mkdir(parents=True, exist_ok=True)
    out = pd.concat([rest, window], ignore_index=True).sort_values(["location_id", "date"])
    out[COLUMNS].to_parquet(STORE, index=False)
    sources = window["source"].value_counts().to_dict()
    log.info("Weather for %d stores, %s -> %s: %s", len(ids), start, end, sources)
    return window

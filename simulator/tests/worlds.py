"""Small offline worlds for the tests (3 stores, 40 SKUs, climatological weather)."""

import copy
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fernbrook.catalog import build_catalog
from fernbrook.external import climatology
from fernbrook.settings import config
from fernbrook.world import World

HOLIDAYS = pd.DataFrame({"date": [date(2024, 11, 28), date(2024, 12, 25), date(2025, 1, 1), date(2025, 7, 4)],
                         "name": ["Thanksgiving Day", "Christmas Day", "New Year's Day", "Independence Day"]})


def small_config() -> dict:
    cfg = copy.deepcopy(config())
    cfg["world"]["n_skus"] = 40
    cfg["stores"] = cfg["stores"][:3]
    return cfg


def make_world(horizon_end: date, cfg: dict | None = None) -> World:
    """A 3-store, 40-SKU world with climatological weather (no network)."""
    cfg = cfg or small_config()
    cat = build_catalog(cfg, np.random.default_rng(1))
    t0 = date.fromisoformat(str(cfg["calendar"]["start_date"])) - timedelta(days=int(cfg["calendar"]["warmup_days"]))
    locs = [{"location_id": s["id"], "lat": s["lat"], "lon": s["lon"]} for s in cfg["stores"]]
    weather = climatology(locs, list(pd.date_range(t0, horizon_end).date))
    return World(cfg=cfg, catalog=cat, weather=weather, holidays=HOLIDAYS, seed=5, horizon_end=horizon_end)


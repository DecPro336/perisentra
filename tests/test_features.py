from datetime import date, timedelta

import numpy as np
import polars as pl

from perisentra.features.build import demand_signal, history_stats


def _panel(days=60, censored_day=40):
    d0 = date(2026, 1, 1)
    rows = []
    for i in range(days):
        rows.append({"store_id": 1, "sku_id": 7, "date": d0 + timedelta(days=i), "is_open": True, "is_in_season": True,
                     "units_sold": 2.0 if i == censored_day else 10.0, "is_censored": i == censored_day,
                     "is_markdown": False, "family": "X", "footfall": 1000.0})
    return pl.DataFrame(rows)


def test_censored_day_signal_is_not_the_capped_sale():
    p = demand_signal(_panel())
    row = p.filter(pl.col("date") == date(2026, 2, 10))
    assert row["signal"][0] >= 9.9          # recent uncensored mean, not the 2 units sold


def test_history_stats_use_only_the_past():
    p = demand_signal(_panel())
    # change the future: stats as of day 30 must not move
    p2 = p.with_columns(pl.when(pl.col("date") > date(2026, 1, 31)).then(999.0).otherwise(pl.col("signal")).alias("signal"))
    a = history_stats(p).filter(pl.col("date") == date(2026, 1, 31))
    b = history_stats(p2).filter(pl.col("date") == date(2026, 1, 31))
    assert np.isclose(a["sig_ma28"][0], b["sig_ma28"][0])
    assert np.isclose(a["sig_ewm"][0], b["sig_ewm"][0])


def test_targets_beyond_the_calendar_fail_loudly():
    """Regression: a target day missing from the calendar must not silently get NaN calendar features."""
    import pandas as pd
    import pytest

    from perisentra.features.build import FeatureContext, build_targets

    p = demand_signal(_panel())
    days = pd.date_range("2026-01-01", periods=60)                 # the warehouse calendar ends on 1 March
    cal = pd.DataFrame({"date_day": days.date, "weekday": days.weekday, "day_of_month": days.day, "month": days.month,
                        "year": days.year, "day_of_year": days.dayofyear, "is_holiday": False, "holiday_name": None,
                        "is_pre_holiday": False, "days_to_next_holiday": None, "days_since_holiday": None})
    ctx = FeatureContext(products=pd.DataFrame({"sku_id": [7], "family": ["X"], "subfamily": ["X"], "shelf_life_days": [3],
                                                "regular_price": [2.0], "unit_cost": [1.0], "launch_date": [date(2025, 1, 1)]}),
                         stores=pd.DataFrame({"store_id": [1], "store_format": ["supermarket"], "region": ["Ohio"]}),
                         calendar=cal, climate=pd.DataFrame({"store_id": [1], "day_of_year": [1], "temp_normal": [40.0]}))
    tgt = pl.DataFrame({"store_id": [1], "sku_id": [7], "date": [date(2026, 3, 15)], "horizon": [1], "promo_pct": [0.0],
                        "in_flyer": [False], "sibling_promo_share": [0.0], "temp_max": [50.0], "precipitation": [0.0]})
    with pytest.raises(ValueError, match="calendar does not cover"):
        build_targets(p, tgt.with_columns(pl.col("store_id").cast(pl.Int64), pl.col("sku_id").cast(pl.Int64)), ctx)

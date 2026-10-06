"""Feature engineering shared by training, backtesting and daily scoring.

Direct multi-horizon design: every target row (store, SKU, day d) is paired with an origin o = d - k
(k = 1..7 days ahead). Features describing the *past* are computed as of the origin, features that are
known in advance (calendar, planned promos, weather forecast) are taken at the target day. During
training each row gets a random horizon so one global model learns all horizons.

The demand signal used for history features treats stock-outs as censored: on censored days the
signal is max(sales, recent uncensored mean) rather than the observed (too low) sales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
import polars as pl

KEYS = ["store_id", "sku_id"]
CATEGORICAL = ["store_id", "family", "subfamily", "store_format", "region"]
WEATHER = ["temp_max", "temp_anomaly", "hot_degree", "precipitation", "rain_flag"]
TREATMENT = ["discount_on_target", "discount_coverage"]       # set to 0 to get the baseline (no markdown)
FEATURES = CATEGORICAL + [
    "horizon", "shelf_life_days", "log_price", "price_rank_in_family", "unit_margin_rate", "sku_age_days",
    "weekday", "day_of_month", "month", "day_of_year", "is_holiday", "is_pre_holiday",
    "days_to_next_holiday", "days_since_holiday",
    *WEATHER,
    "promo_pct", "in_flyer", "sibling_promo_share", *TREATMENT,
    "sig_ma7", "sig_ma28", "sig_ma91", "sig_std28", "sig_ewm", "last_signal", "zero_share28",
    "censored_share28", "markdown_share28", "history_days", "fam_store_ma28", "footfall_ma7", "footfall_trend",
    "lag7", "lag14", "lag21", "lag28", "dow_ma4",
]

HOT_F = 77.0         # heat threshold (°F); weather comes from Open-Meteo in imperial units
RAIN_IN = 0.2        # rainy day threshold (inches)

PANEL_COLUMNS = ["store_id", "sku_id", "date", "is_open", "is_in_season", "units_sold", "is_censored",
                 "is_markdown", "markdown_pct", "markdown_units_labelled", "opening_stock", "receipts",
                 "promo_pct", "in_flyer", "sibling_promo_share", "footfall", "temp_max", "precipitation",
                 "test_discount_pct"]
FUTURE_COLUMNS = ["store_id", "sku_id", "date", "is_open", "is_in_season", "promo_pct", "in_flyer",
                  "sibling_promo_share", "temp_max", "precipitation"]


@dataclass
class FeatureContext:
    """Static inputs needed to build features (product/store dims, calendar, climate normals)."""
    products: pd.DataFrame          # sku_id, family, subfamily, shelf_life_days, regular_price, unit_cost, launch_date
    stores: pd.DataFrame            # store_id, store_format, region
    calendar: pd.DataFrame          # date_day, weekday, ... (int_calendar)
    climate: pd.DataFrame           # store_id, day_of_year, temp_normal
    weather_mask: list[str] = field(default_factory=list)    # families where weather features are dropped
    categories: dict[str, list] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.categories:
            p, s = self.products, self.stores
            self.categories = {
                "store_id": sorted(s["store_id"].astype(int).tolist()),
                "family": sorted(p["family"].unique().tolist()),
                "subfamily": sorted(p["subfamily"].unique().tolist()),
                "store_format": sorted(s["store_format"].unique().tolist()),
                "region": sorted(s["region"].unique().tolist()),
            }


HISTORY_CAP = 90    # history_days is capped so a 120-day scoring panel and the full training panel agree


def climate_normals(weather: pd.DataFrame) -> pd.DataFrame:
    """Per-store seasonal temperature normal from a 2-harmonic regression (for temperature anomalies)."""
    rows = []
    w = weather.dropna(subset=["temp_max"])
    for sid, g in w.groupby("store_id"):
        doy = pd.to_datetime(g["weather_date"]).dt.dayofyear.to_numpy()
        a = 2 * np.pi * doy / 365.25
        X = np.column_stack([np.ones_like(a), np.sin(a), np.cos(a), np.sin(2 * a), np.cos(2 * a)])
        beta, *_ = np.linalg.lstsq(X, g["temp_max"].to_numpy(), rcond=None)
        grid = np.arange(1, 367)
        ag = 2 * np.pi * grid / 365.25
        Xg = np.column_stack([np.ones_like(ag), np.sin(ag), np.cos(ag), np.sin(2 * ag), np.cos(2 * ag)])
        rows.append(pd.DataFrame({"store_id": int(sid), "day_of_year": grid, "temp_normal": Xg @ beta}))
    return pd.concat(rows, ignore_index=True)


# ----------------------------------------------------------------------------------------------
# history statistics (as of each day)
# ----------------------------------------------------------------------------------------------
def demand_signal(panel: pl.DataFrame) -> pl.DataFrame:
    """Add `signal`: censoring-aware demand estimate used for history features."""
    live = pl.col("is_open") & pl.col("is_in_season")
    p = panel.sort(KEYS + ["date"]).with_columns(
        clean=pl.when(live & ~pl.col("is_censored")).then(pl.col("units_sold").cast(pl.Float64)).otherwise(None),
    )
    p = p.with_columns(
        clean_ma28=(pl.col("clean").shift(1).rolling_mean(28, min_samples=3).over(KEYS)),
    )
    p = p.with_columns(
        signal=pl.when(~live).then(None)
        .when(pl.col("is_censored"))
        .then(pl.max_horizontal(pl.col("units_sold").cast(pl.Float64), pl.col("clean_ma28").fill_null(0.0)))
        .otherwise(pl.col("units_sold").cast(pl.Float64))
    )
    return p.drop(["clean", "clean_ma28"])


def _rmean(col: str, n: int) -> pl.Expr:
    s = pl.col(col).fill_null(0.0).rolling_sum(n, min_samples=1).over(KEYS)
    c = pl.col(col).is_not_null().cast(pl.Float64).rolling_sum(n, min_samples=1).over(KEYS)
    return pl.when(c > 0).then(s / c).otherwise(None)


def history_stats(panel: pl.DataFrame) -> pl.DataFrame:
    """Per store-SKU-day statistics using information up to and including that day."""
    live = (pl.col("is_open") & pl.col("is_in_season")).cast(pl.Float64)
    p = panel.with_columns(
        sig_sq=pl.col("signal") ** 2,
        zero=pl.when(pl.col("signal").is_not_null()).then((pl.col("signal") == 0).cast(pl.Float64)),
        cens=pl.when(live > 0).then(pl.col("is_censored").cast(pl.Float64)),
        mdflag=pl.when(live > 0).then(pl.col("is_markdown").cast(pl.Float64)),
        fullprice=pl.when(~pl.col("is_markdown")).then(pl.col("signal")),
    )
    p = p.with_columns(
        sig_ma7=_rmean("signal", 7), sig_ma28=_rmean("signal", 28), sig_ma91=_rmean("signal", 91),
        sq28=_rmean("sig_sq", 28), zero_share28=_rmean("zero", 28), censored_share28=_rmean("cens", 28),
        markdown_share28=_rmean("mdflag", 28),
        fullprice_ma28=_rmean("fullprice", 28),
        sig_ewm=pl.col("signal").ewm_mean(alpha=0.25, ignore_nulls=True, min_samples=1).forward_fill().over(KEYS),
        last_signal=pl.col("signal").forward_fill().over(KEYS),
        history_days=pl.col("signal").is_not_null().cast(pl.Int32).cum_sum().over(KEYS).clip(upper_bound=HISTORY_CAP),
    )
    p = p.with_columns(sig_std28=(pl.col("sq28") - pl.col("sig_ma28") ** 2).clip(lower_bound=0).sqrt())
    stats = p.select(KEYS + ["date", "sig_ma7", "sig_ma28", "sig_ma91", "sig_std28", "sig_ewm", "last_signal",
                             "zero_share28", "censored_share28", "markdown_share28", "history_days",
                             "fullprice_ma28"])
    # family-store level (cold-start borrowing): average SKU ma28 within the store-family that day
    fam = (p.select(KEYS + ["date", "family", "sig_ma28"])
             .group_by(["store_id", "family", "date"]).agg(fam_store_ma28=pl.col("sig_ma28").mean()))
    # store footfall (store-level, deduplicated)
    foot = (p.select(["store_id", "date", "footfall", "is_open"]).unique(["store_id", "date"]).sort(["store_id", "date"])
              .with_columns(f=pl.when(pl.col("is_open")).then(pl.col("footfall").cast(pl.Float64))))
    foot = foot.with_columns(
        footfall_ma7=(pl.col("f").fill_null(0).rolling_sum(7, min_samples=1).over("store_id")
                      / pl.col("f").is_not_null().cast(pl.Float64).rolling_sum(7, min_samples=1).over("store_id")),
        f91=(pl.col("f").fill_null(0).rolling_sum(91, min_samples=1).over("store_id")
             / pl.col("f").is_not_null().cast(pl.Float64).rolling_sum(91, min_samples=1).over("store_id")),
    ).with_columns(footfall_trend=pl.col("footfall_ma7") / pl.col("f91")).select(
        ["store_id", "date", "footfall_ma7", "footfall_trend"])
    stats = stats.join(p.select(KEYS + ["date", "family"]), on=KEYS + ["date"], how="left")
    stats = stats.join(fam, on=["store_id", "family", "date"], how="left").drop("family")
    stats = stats.join(foot, on=["store_id", "date"], how="left")
    return stats


# ----------------------------------------------------------------------------------------------
# assembling the design matrix
# ----------------------------------------------------------------------------------------------
def _with_family(panel: pl.DataFrame, ctx: FeatureContext) -> pl.DataFrame:
    if "family" in panel.columns:
        return panel
    return panel.join(pl.from_pandas(ctx.products[["sku_id", "family"]]), on="sku_id", how="left")


def build_targets(panel: pl.DataFrame, targets: pl.DataFrame, ctx: FeatureContext,
                  stats: pl.DataFrame | None = None) -> pd.DataFrame:
    """targets: rows with store_id, sku_id, date, horizon + target-day covariates.

    `panel` must contain history up to each row's origin (date - horizon) and the signal column.
    Returns a pandas frame with FEATURES (+ passthrough columns).
    """
    if stats is None:
        stats = history_stats(panel)
    t = targets.with_columns(origin=pl.col("date") - pl.duration(days=pl.col("horizon")))
    t = t.join(stats.rename({"date": "origin"}), on=KEYS + ["origin"], how="left")

    # same-weekday lags of the target day (all <= origin because horizon <= 7)
    sig = panel.select(KEYS + ["date", "signal"])
    for lag in (7, 14, 21, 28):
        t = t.join(sig.with_columns(date=pl.col("date") + pl.duration(days=lag)).rename({"signal": f"lag{lag}"}),
                   on=KEYS + ["date"], how="left")
    t = t.with_columns(dow_ma4=pl.mean_horizontal("lag7", "lag14", "lag21", "lag28"))

    # calendar
    cal = pl.from_pandas(ctx.calendar[["date_day", "weekday", "day_of_month", "month", "day_of_year", "is_holiday",
                                       "is_pre_holiday", "days_to_next_holiday", "days_since_holiday"]]) \
        .rename({"date_day": "date"}).with_columns(pl.col("date").cast(pl.Date))
    t = t.join(cal, on="date", how="left")
    missing = t.filter(pl.col("weekday").is_null())
    if missing.height:
        raise ValueError(f"calendar does not cover target dates up to {missing['date'].max()}")

    # weather: anomaly vs the store's seasonal normal
    clim = pl.from_pandas(ctx.climate).with_columns(pl.col("store_id").cast(t.schema["store_id"]),
                                                    pl.col("day_of_year").cast(pl.Int64))
    t = t.with_columns(pl.col("day_of_year").cast(pl.Int64)).join(clim, on=["store_id", "day_of_year"], how="left")
    t = t.with_columns(
        temp_anomaly=pl.col("temp_max") - pl.col("temp_normal"),
        hot_degree=(pl.col("temp_max") - HOT_F).clip(lower_bound=0),
        rain_flag=(pl.col("precipitation") > RAIN_IN).cast(pl.Float64),
    )

    # static product / store attributes
    prod = ctx.products.copy()
    prod["log_price"] = np.log(prod["regular_price"])
    prod["price_rank_in_family"] = prod.groupby("family")["regular_price"].rank(pct=True)
    prod["unit_margin_rate"] = 1 - prod["unit_cost"] / prod["regular_price"]
    prod = pl.from_pandas(prod[["sku_id", "family", "subfamily", "shelf_life_days", "log_price",
                                "price_rank_in_family", "unit_margin_rate", "launch_date"]]) \
        .with_columns(pl.col("sku_id").cast(t.schema["sku_id"]), pl.col("launch_date").cast(pl.Date))
    if "family" in t.columns:
        t = t.drop("family")
    if "subfamily" in t.columns:
        t = t.drop("subfamily")
    t = t.join(prod, on="sku_id", how="left")
    st = pl.from_pandas(ctx.stores[["store_id", "store_format", "region"]]).with_columns(
        pl.col("store_id").cast(t.schema["store_id"]))
    t = t.join(st, on="store_id", how="left")
    t = t.with_columns(sku_age_days=(pl.col("date") - pl.col("launch_date")).dt.total_days().clip(0, 3650))

    for c in TREATMENT:
        if c not in t.columns:
            t = t.with_columns(pl.lit(0.0).alias(c))
    df = t.to_pandas()
    for c in ("days_to_next_holiday", "days_since_holiday"):
        df[c] = df[c].fillna(60).clip(upper=60)
    for c in ("is_holiday", "is_pre_holiday", "in_flyer"):
        df[c] = df[c].fillna(False).astype(float)
    if ctx.weather_mask:
        masked = df["family"].isin(ctx.weather_mask)
        df.loc[masked, WEATHER] = np.nan
    for c, cats in ctx.categories.items():
        df[c] = pd.Categorical(df[c], categories=cats)
    return df


def training_frame(panel: pl.DataFrame, ctx: FeatureContext, start: date, end: date,
                   horizon_max: int = 7, seed: int = 0) -> pd.DataFrame:
    """Design matrix for target days in [start, end] with one random horizon per row."""
    panel = demand_signal(_with_family(panel, ctx))
    stats = history_stats(panel)
    live = pl.col("is_open") & pl.col("is_in_season")
    tgt = panel.filter(live & (pl.col("date") >= start) & (pl.col("date") <= end))
    rng = np.random.default_rng(seed)
    tgt = tgt.with_columns(horizon=pl.Series(rng.integers(1, horizon_max + 1, tgt.height)).cast(pl.Int32))
    # treatment features: sticker discount and the share of stock it covered (whole-shelf test = 1)
    avail = (pl.col("opening_stock") + pl.col("receipts")).clip(lower_bound=1)
    tgt = tgt.with_columns(
        discount_on_target=pl.when(pl.col("test_discount_pct").fill_null(0) > 0).then(pl.col("test_discount_pct"))
        .when(pl.col("is_markdown")).then(pl.col("markdown_pct")).otherwise(0.0),
        discount_coverage=pl.when(pl.col("test_discount_pct").fill_null(0) > 0).then(1.0)
        .when(pl.col("is_markdown")).then((pl.col("markdown_units_labelled") / avail).clip(0, 1)).otherwise(0.0),
    )
    tgt = tgt.with_columns(available=(pl.col("opening_stock") + pl.col("receipts")).cast(pl.Float64))
    keep = ["store_id", "sku_id", "date", "horizon", "units_sold", "is_censored", "promo_pct", "in_flyer",
            "sibling_promo_share", "temp_max", "precipitation", "discount_on_target", "discount_coverage",
            "is_markdown", "test_discount_pct", "family", "available"]
    df = build_targets(panel, tgt.select(keep), ctx, stats)
    return df[df["history_days"].fillna(0) >= 7].reset_index(drop=True)


def scoring_frame(panel: pl.DataFrame, future: pl.DataFrame, ctx: FeatureContext, origin: date,
                  horizon: int = 7) -> pd.DataFrame:
    """Baseline (no markdown) features for target days origin+1 .. origin+horizon."""
    panel = demand_signal(_with_family(panel.filter(pl.col("date") <= origin), ctx))
    stats = history_stats(panel)
    fut = future.filter((pl.col("date") > origin) & (pl.col("date") <= origin + timedelta(days=horizon)))
    fut = fut.with_columns(horizon=(pl.col("date") - pl.lit(origin)).dt.total_days().cast(pl.Int32))
    keep = ["store_id", "sku_id", "date", "horizon", "is_open", "is_in_season", "promo_pct", "in_flyer",
            "sibling_promo_share", "temp_max", "precipitation"]
    return build_targets(panel, fut.select(keep), ctx, stats)

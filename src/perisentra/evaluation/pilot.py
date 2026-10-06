"""Pilot: Perisentra's daily task list goes to treatment stores, matched control stores keep the current rule.

Design (decided before the pilot starts, from pre-period data only)
    - treatment stores stratified by format; each is matched to the most similar remaining store of the same
      format (standardised pre-period sales, waste rate, markdown rate and last year's seasonal profile)
    - evaluation: difference-in-differences on weekly store outcomes, matched-pair bootstrap CIs

After the pilot, the treatment stores keep the task list (deployment.live_stores = pilot in client.yaml).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from perisentra import warehouse as wh
from perisentra.config import PATHS, as_date, client_config
from perisentra.utils import get_logger, read_json, write_json

log = get_logger(__name__)
DESIGN = PATHS.pilot / "design.json"
OUTCOMES = ["waste_value", "waste_units", "markdown_events", "discount_given", "gross_margin", "net_sales",
            "units_sold", "stockout_rate", "margin_rate"]


# ----------------------------------------------------------------------------------------------
# design
# ----------------------------------------------------------------------------------------------
def store_weeks(start: date, end: date) -> pd.DataFrame:
    df = wh.query(f"""
        select store_id, week_start, sum(waste_value) as waste_value, sum(waste_units) as waste_units,
               sum(markdown_events) as markdown_events, sum(discount_given) as discount_given,
               sum(gross_margin) as gross_margin, sum(net_sales) as net_sales, sum(units_sold) as units_sold,
               sum(stockout_rate * sku_days) / sum(sku_days) as stockout_rate
        from marts.mart_store_family_week
        where week_start >= DATE '{start}' and week_start <= DATE '{end}'
        group by 1, 2 order by 1, 2""")
    df["margin_rate"] = df["gross_margin"] / df["net_sales"]
    return df


def design_pilot(seed: int | None = None) -> dict:
    pc = client_config()["pilot"]
    start = as_date(pc["start"])
    pre = store_weeks(start - timedelta(weeks=pc["pre_weeks"]), start - timedelta(days=1))
    stores = wh.stores()[["store_id", "store_format", "store_name"]]
    agg = pre.groupby("store_id").agg(net_sales=("net_sales", "mean"), waste_value=("waste_value", "mean"),
                                      markdown_events=("markdown_events", "mean")).reset_index().merge(stores)
    agg["waste_rate"] = agg["waste_value"] / agg["net_sales"]
    agg["log_sales"] = np.log(agg["net_sales"])
    agg["md_rate"] = agg["markdown_events"] / agg["net_sales"] * 1000
    # seasonal profile from last year (pre-pilot data only): how each store's sales moved from the
    # pre-period weeks to the pilot weeks a year earlier. Matching on it protects parallel trends
    # against regional summer effects (college towns empty out in summer, lake towns fill up).
    ly = lambda d: d - timedelta(weeks=52)
    ly_pre = store_weeks(ly(start - timedelta(weeks=pc["pre_weeks"])), ly(start - timedelta(days=1)))
    ly_pil = store_weeks(ly(start), ly(as_date(pc["end"])))
    season = (ly_pil.groupby("store_id")["net_sales"].mean() / ly_pre.groupby("store_id")["net_sales"].mean())
    agg["season_ratio"] = agg["store_id"].map(np.log(season)).fillna(0.0)
    z = agg[["log_sales", "waste_rate", "md_rate", "season_ratio"]]
    z = (z - z.mean()) / z.std()
    z["season_ratio"] *= 2.0                    # parallel trends matter most for a DiD readout
    agg[["z1", "z2", "z3", "z4"]] = z.to_numpy()
    rng = np.random.default_rng(seed or pc["design_seed"])
    quota = dict(pc["quota_by_format"])
    treat = []
    for fmt, q in quota.items():
        pool = agg[agg["store_format"] == fmt]["store_id"].to_numpy()
        treat += [int(x) for x in rng.choice(pool, size=min(q, len(pool) // 2), replace=False)]
    pairs, used = [], set(treat)
    for t in treat:
        row = agg[agg["store_id"] == t].iloc[0]
        cand = agg[(agg["store_format"] == row["store_format"]) & (~agg["store_id"].isin(used))]
        cols = ["z1", "z2", "z3", "z4"]
        dist = np.sqrt(((cand[cols] - row[cols].to_numpy(float)) ** 2).sum(1))
        c = int(cand.iloc[int(np.argmin(dist.to_numpy()))]["store_id"])
        used.add(c)
        pairs.append({"treatment": t, "control": c, "format": row["store_format"],
                      "distance": float(dist.min()), "season_treatment": float(np.exp(row["season_ratio"])),
                      "season_control": float(np.exp(agg.loc[agg["store_id"] == c, "season_ratio"].iloc[0]))})
    design = {"start": str(pc["start"]), "end": str(pc["end"]), "treatment": treat,
              "control": [p["control"] for p in pairs], "pairs": pairs,
              "rest": [int(s) for s in agg["store_id"] if s not in used], "pre_weeks": pc["pre_weeks"]}
    write_json(DESIGN, design)
    log.info("Pilot design: treatment %s, matched controls %s", treat, design["control"])
    return design


def pilot_design() -> dict:
    """The saved design, or {} before the pilot has been designed."""
    return read_json(DESIGN) if DESIGN.exists() else {}


def live_stores() -> list[int]:
    """Stores that receive the daily task list."""
    live = client_config()["deployment"]["live_stores"]
    if live == "pilot":
        return [int(s) for s in pilot_design().get("treatment", [])]
    return [int(s) for s in live]


# ----------------------------------------------------------------------------------------------
# evaluation (uses only the warehouse, like a real pilot readout)
# ----------------------------------------------------------------------------------------------
def evaluate(n_boot: int = 2000, seed: int = 3) -> dict:
    design = read_json(DESIGN)
    start, end = as_date(design["start"]), as_date(design["end"])
    pre_start = start - timedelta(weeks=design["pre_weeks"])
    _, last = wh.bounds()
    weeks = store_weeks(pre_start, last)
    weeks["week_start"] = pd.to_datetime(weeks["week_start"]).dt.date
    weeks = weeks[[w + timedelta(days=6) <= last for w in weeks["week_start"]]]    # complete weeks only
    weeks["period"] = np.where(weeks["week_start"] < start, "pre",
                               np.where(weeks["week_start"] <= end, "pilot", "after"))
    weeks["group"] = weeks["store_id"].map(
        {**{s: "treatment" for s in design["treatment"]}, **{s: "control" for s in design["control"]}}).fillna("rest")
    main = weeks[weeks["period"].isin(["pre", "pilot"])]
    per_store = main.groupby(["store_id", "period"])[OUTCOMES].mean().unstack("period")
    rng = np.random.default_rng(seed)
    pairs = design["pairs"]
    results = {}
    for m in OUTCOMES:
        diffs = []
        base = []
        for p in pairs:
            t, c = p["treatment"], p["control"]
            dt = per_store.loc[t, (m, "pilot")] - per_store.loc[t, (m, "pre")]
            dc = per_store.loc[c, (m, "pilot")] - per_store.loc[c, (m, "pre")]
            # control trend scaled to the treatment store's level (ratio DiD) keeps pairs comparable
            rel_c = dc / per_store.loc[c, (m, "pre")] if per_store.loc[c, (m, "pre")] else 0
            diffs.append(dt - rel_c * per_store.loc[t, (m, "pre")])
            base.append(per_store.loc[t, (m, "pre")])
        diffs, base = np.array(diffs, float), np.array(base, float)
        est = diffs.mean()
        pct = 100 * diffs.sum() / base.sum() if base.sum() else np.nan
        boot = []
        for _ in range(n_boot):
            k = rng.integers(0, len(diffs), len(diffs))
            boot.append(100 * diffs[k].sum() / base[k].sum() if base[k].sum() else np.nan)
        lo, hi = np.nanpercentile(boot, [2.5, 97.5])
        results[m] = {"did_per_store_week": float(est), "did_pct": float(pct), "ci_low": float(lo), "ci_high": float(hi),
                      "treatment_pre": float(base.mean())}
    series = (weeks.groupby(["group", "week_start"])[["waste_value", "markdown_events", "gross_margin", "net_sales",
                                                      "stockout_rate"]].mean().reset_index())
    series["margin_rate"] = series["gross_margin"] / series["net_sales"]
    flat = per_store.copy()
    flat.columns = [f"{m}_{period}" for m, period in flat.columns]                 # e.g. waste_value_pilot
    report = {"design": design, "data_end": last, "did": results, "weekly": series.to_dict("records"),
              "store_period": flat.reset_index().to_dict("records")}
    write_json(PATHS.reports / "pilot_evaluation.json", report)
    return report

"""Ground-truth validation of a decision system running on the simulated chain.

A real retailer never knows true demand (only capped sales), true price response or what a pilot store would
have done without the change. The simulator does, so it can grade the consumer's published outputs:

    forecasts    backtest predictions vs true demand: bias on all days, on stock-out days, and on items whose
                 recent sales are heavily capped by stock-outs
    price        estimated elasticities vs the true ones (mean error, coverage of the credible intervals)
    pilot        the measured effect (difference-in-differences) vs the true effect: the pilot period replayed
                 with the stores' current rule and identical random numbers

It reads the consumer's artefacts read-only (paths below) and writes `var/reports/validation.{json,md}`.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from fernbrook.settings import PATHS, as_date, get_logger
from fernbrook.stores import TaskListPolicy, load_task_list

log = get_logger(__name__)
METHODS = ["model", "legacy", "seasonal_naive", "ma28"]
PILOT_METRICS = ["waste_value", "markdown_events", "gross_margin", "net_sales", "units_sold", "margin_rate"]


def _wape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.abs(y - p).sum() / max(y.sum(), 1e-9))


def _bias(y: np.ndarray, p: np.ndarray) -> float:
    return float((p - y).sum() / max(y.sum(), 1e-9))


def _true_demand() -> pd.DataFrame:
    files = sorted(PATHS.truth.glob("truth_*.parquet"))
    if not files:
        raise FileNotFoundError("no ground truth yet")
    t = pd.concat([pd.read_parquet(f, columns=["date", "store_id", "sku_id", "true_demand"]) for f in files])
    t["date"] = pd.to_datetime(t["date"])
    return t


# ----------------------------------------------------------------------------------------------
# forecasts
# ----------------------------------------------------------------------------------------------
def forecasts(predictions: Path) -> dict:
    df = pd.read_parquet(predictions)
    df["date"] = pd.to_datetime(df["date"])
    df = df.merge(_true_demand(), on=["date", "store_id", "sku_id"], how="inner")
    for m in METHODS:
        df[m] = df[m].fillna(df["ma28"]).fillna(0)

    def block(d: pd.DataFrame) -> dict:
        y = d["true_demand"].to_numpy(float)
        return {"rows": len(d), **{m: {"wape": _wape(y, d[m].to_numpy(float)), "bias": _bias(y, d[m].to_numpy(float))}
                                   for m in METHODS}}

    return {"all_days": block(df), "stockout_days": block(df[df["censored"]]),
            "chronically_censored": block(df[df["censored_share28"].fillna(0) >= 0.25]),
            "note": "Bias on stock-out days alone mixes in a selection effect (a stock-out happens when demand was "
                    "high): compare methods on all days and on chronically censored items."}


# ----------------------------------------------------------------------------------------------
# price response
# ----------------------------------------------------------------------------------------------
def price_response(model_dir: Path) -> dict:
    family = pd.read_parquet(model_dir / "family.parquet")
    sku = pd.read_parquet(model_dir / "sku.parquet")
    truth = pd.read_parquet(PATHS.truth / "products.parquet")
    sku = sku.merge(truth[["sku_id", "true_elasticity"]], on="sku_id")
    fam_true = truth.groupby("family")["true_elasticity"].mean().rename("true_elasticity")
    family = family.merge(fam_true, left_on="family", right_index=True)
    tested = sku[sku["source"] == "posterior"]
    rows = [{"family": r.family, "estimate": round(r.mean, 3), "true": round(r.true_elasticity, 3),
             "naive": None if pd.isna(r.naive_elasticity) else round(r.naive_elasticity, 3),
             "inside_hdi": bool(r.hdi_low <= r.true_elasticity <= r.hdi_high)} for r in family.itertuples()]
    return {"model": model_dir.name, "families": rows,
            "family_mae": float((family["mean"] - family["true_elasticity"]).abs().mean()),
            "naive_family_mae": float((family["naive_elasticity"] - family["true_elasticity"]).abs().mean()),
            "family_hdi_coverage": float(np.mean([r["inside_hdi"] for r in rows])),
            "tested_skus": len(tested),
            "tested_sku_mae": float((tested["mean"] - tested["true_elasticity"]).abs().mean()) if len(tested) else None,
            "tested_sku_hdi_coverage": float(((tested["hdi_low"] <= tested["true_elasticity"])
                                               & (tested["true_elasticity"] <= tested["hdi_high"])).mean())
            if len(tested) else None}


# ----------------------------------------------------------------------------------------------
# pilot
# ----------------------------------------------------------------------------------------------
def _store_outcomes(world, recs: list, stores: list[int]) -> pd.DataFrame:
    """Store totals with the definitions a warehouse readout uses (recorded expired + damaged waste, open and
    in-season days only), so the true effect and a measured effect are comparable."""
    sid = world.series["store_id"].to_numpy()
    rows = []
    for r in recs:
        live = r.active & world.store_open[world.store_idx, r.t]
        rev = r.units_sold * world.regular_price(r.t) * r.price_ratio * live
        waste = (r.waste_recorded + r.damaged) * live
        for s in stores:
            m = sid == s
            rows.append({"store_id": s, "waste_value": float((waste[m] * world.cost[m]).sum()),
                         "net_sales": float(rev[m].sum()),
                         "gross_margin": float(rev[m].sum() - (r.units_sold[m] * live[m] * world.cost[m]).sum()),
                         "markdown_events": int(((r.md_pct[m] > 0) & (r.md_labelled[m] > 0) & live[m]).sum()),
                         "units_sold": int((r.units_sold[m] * live[m]).sum())})
    return pd.DataFrame(rows).groupby("store_id").sum(numeric_only=True)


def replay_pilot(start: date, end: date, stores: list[int]) -> dict:
    """True effect: replay [start, end] from the state saved the morning the first task list arrived, once with
    the published task lists and once with the stores' current rule, using identical random numbers."""
    import copy

    from fernbrook.runner import load_world

    name = f"checkpoint_{start.isoformat()}.npz"
    if not (PATHS.state / name).exists():
        raise FileNotFoundError(f"no checkpoint saved for {start}")
    actual = load_world(end, name=name)
    counterfactual = copy.deepcopy(actual)
    while actual.today <= end:
        tasks = load_task_list(actual.today)
        actual.step(TaskListPolicy(actual, tasks) if tasks is not None else None)
        counterfactual.step()
    a = _store_outcomes(actual, actual.records, stores)
    b = _store_outcomes(counterfactual, counterfactual.records, stores)
    return _effect(a, b)


def _effect(a: pd.DataFrame, b: pd.DataFrame) -> dict:
    out = {}
    for m in ["waste_value", "markdown_events", "gross_margin", "net_sales", "units_sold"]:
        out[m] = {"with_change": float(a[m].sum()), "without": float(b[m].sum()),
                  "pct_change": float(100 * (a[m].sum() / b[m].sum() - 1)) if b[m].sum() else None}
    ra, rb = a["gross_margin"].sum() / a["net_sales"].sum(), b["gross_margin"].sum() / b["net_sales"].sum()
    out["margin_rate"] = {"with_change": float(ra), "without": float(rb), "pct_change": float(100 * (ra / rb - 1))}
    return out


def pilot(readout_path: Path) -> dict:
    readout = json.loads(readout_path.read_text())
    design = readout["design"]
    start, end = as_date(design["start"]), as_date(design["end"])
    stored = PATHS.truth / "pilot_true_effect.json"
    if stored.exists():                       # computed when the historical pilot was simulated
        truth = json.loads(stored.read_text())
        if "engine" in next(iter(truth.values())):
            truth = {k: {"with_change": v["engine"], "without": v["legacy"], "pct_change": v["pct_change"]}
                     for k, v in truth.items()}
    else:
        truth = replay_pilot(start, end, [int(s) for s in design["treatment"]])
    rows = []
    for m in PILOT_METRICS:
        did = readout["did"].get(m)
        true = truth.get(m, {}).get("pct_change")
        if did is None or true is None:
            continue
        rows.append({"metric": m, "measured_pct": round(did["did_pct"], 2), "ci_low": round(did["ci_low"], 2),
                     "ci_high": round(did["ci_high"], 2), "true_pct": round(true, 2),
                     "inside_ci": bool(did["ci_low"] <= true <= did["ci_high"]),
                     "same_direction": bool(np.sign(did["did_pct"]) == np.sign(true))})
    return {"window": [start.isoformat(), end.isoformat()], "stores": design["treatment"], "metrics": rows}


# ----------------------------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------------------------
def report(product_data: Path) -> dict:
    out: dict = {"generated_at": datetime.now().isoformat(timespec="seconds")}
    checks = {
        "forecasts": (lambda: forecasts(product_data / "reports" / "backtest_predictions.parquet")),
        "price_response": (lambda: price_response(product_data / "models" / "elasticity"
                                                  / (product_data / "models" / "elasticity" / "CHAMPION")
                                                  .read_text().strip())),
        "pilot": (lambda: pilot(product_data / "reports" / "pilot_evaluation.json")),
    }
    for name, fn in checks.items():
        try:
            out[name] = fn()
        except FileNotFoundError as exc:
            out[name] = {"skipped": f"input not available: {exc}"}
            log.warning("Validation of %s skipped: %s", name, exc)
    PATHS.reports.mkdir(parents=True, exist_ok=True)
    (PATHS.reports / "validation.json").write_text(json.dumps(out, indent=2, default=str))
    (PATHS.reports / "validation.md").write_text(_markdown(out))
    return out


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{100 * v:+.1f}%"


def _markdown(r: dict) -> str:
    lines = ["# Ground-truth validation", "", f"Generated {r['generated_at']} from the simulator's ground truth.", ""]
    f = r.get("forecasts", {})
    if "all_days" in f:
        lines += ["## Forecasts vs true demand (backtest)", "",
                  "| Scope | Rows | Perisentra bias | Current rule bias | 28-day average bias | Perisentra WAPE |",
                  "|---|---:|---:|---:|---:|---:|"]
        for key, label in (("all_days", "All days"), ("stockout_days", "Stock-out days"),
                           ("chronically_censored", "Chronically censored items")):
            b = f[key]
            lines.append(f"| {label} | {b['rows']:,} | {_pct(b['model']['bias'])} | {_pct(b['legacy']['bias'])} | "
                         f"{_pct(b['ma28']['bias'])} | {b['model']['wape']:.3f} |")
        lines += ["", f"_{f['note']}_", ""]
    p = r.get("price_response", {})
    if "families" in p:
        summary = (f"Family estimates are within **{p['family_mae']:.2f}** of the true elasticity on average "
                   f"(naive regression on history: {p['naive_family_mae']:.2f}); the true value is inside the 94% "
                   f"interval for {p['family_hdi_coverage']:.0%} of families and "
                   f"{(p['tested_sku_hdi_coverage'] or 0):.0%} of the {p['tested_skus']} tested SKUs.")
        lines += ["## Price elasticity vs truth", "", summary, "",
                  "| Family | Estimate | True | Naive | Inside 94% HDI |", "|---|---:|---:|---:|:---:|"]
        for x in p["families"]:
            naive = "–" if x["naive"] is None else f"{x['naive']:.2f}"
            inside = "yes" if x["inside_hdi"] else "no"
            lines.append(f"| {x['family']} | {x['estimate']:.2f} | {x['true']:.2f} | {naive} | {inside} |")
        lines.append("")
    pl = r.get("pilot", {})
    if "metrics" in pl:
        lines += [f"## Pilot: measured vs true effect ({pl['window'][0]} to {pl['window'][1]})", "",
                  "| Metric | Measured (DiD) | 95% CI | True | Inside CI |", "|---|---:|---:|---:|:---:|"]
        for x in pl["metrics"]:
            lines.append(f"| {x['metric'].replace('_', ' ')} | {x['measured_pct']:+.1f}% | "
                         f"{x['ci_low']:+.1f}% to {x['ci_high']:+.1f}% | {x['true_pct']:+.1f}% | "
                         f"{'yes' if x['inside_ci'] else 'no'} |")
        lines.append("")
    for name in ("forecasts", "price_response", "pilot"):
        if "skipped" in r.get(name, {}):
            lines.append(f"- {name.replace('_', ' ')}: {r[name]['skipped']}")
    return "\n".join(lines) + "\n"


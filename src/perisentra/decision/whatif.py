"""What-if: evaluate a user-chosen markdown against doing nothing, with the engine's constraints."""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from perisentra import warehouse as wh
from perisentra.config import PATHS
from perisentra.decision.engine import _hist
from perisentra.decision.inputs import build_engine_input
from perisentra.decision.rules import Rules, current_rules
from perisentra.elasticity.model import ElasticityModel
from perisentra.forecasting.model import DemandModel
from perisentra.risk.montecarlo import ActionSet, RiskBatch, simulate

_models: dict[str, object] = {}


def _load(meta: dict) -> tuple[DemandModel, ElasticityModel]:
    key = meta["demand_model"] + meta["elasticity_model"]
    if key not in _models:
        _models.clear()
        _models[key] = (DemandModel.load(meta["demand_model"]), ElasticityModel.load(meta["elasticity_model"]))
    return _models[key]  # type: ignore[return-value]


def evaluate(store_id: int, sku_id: int, discount_pct: float, window_days: int, n_paths: int = 2000,
             rules: Rules | None = None) -> dict:
    meta = json.loads((PATHS.serving / "run_meta.json").read_text())
    as_of = date.fromisoformat(meta["as_of_date"])
    dm, em = _load(meta)
    rules = rules or current_rules()
    fc = pd.read_parquet(PATHS.serving / "forecasts.parquet")
    fc = fc[(fc["store_id"] == store_id) & (fc["sku_id"] == sku_id)].copy()
    if fc.empty:
        raise KeyError("unknown store/sku")
    fc["date"] = fc["date"].dt.date
    X = pd.read_parquet(PATHS.serving / "engine_features.parquet")
    X = X[(X["store_id"] == store_id) & (X["sku_id"] == sku_id)]
    lots = pd.read_parquet(PATHS.serving / "lots.parquet")
    lots = lots[(lots["store_id"] == store_id) & (lots["sku_id"] == sku_id)]
    recs = pd.read_parquet(PATHS.serving / "recommendations.parquet")
    ref = recs.loc[(recs["store_id"] == store_id) & (recs["sku_id"] == sku_id), ["store_id", "sku_id", "order_reference"]] \
        .rename(columns={"order_reference": "reference_order"})
    from perisentra.pipeline.score import serving_inputs

    on_order, stickers, calendar = serving_inputs(store_id, sku_id)
    inp = build_engine_input(as_of, fc, X, lots, wh.products(), calendar, dm, em, ref, stickers, on_order=on_order)
    m = inp.meta.iloc[0]
    reg, cost, fam = float(m["regular_price"]), float(m["unit_cost"]), m["family"]
    d = float(discount_pct) / 100
    cap = rules.max_discount(fam)
    # within the cap, snapping stays within it (as in the engine); beyond it the max_discount check below fails
    new_price = rules.snap_price(reg * (1 - d), reg * (1 - cap) if d <= cap + 1e-9 else None) if d > 0 else reg
    eff = 1 - new_price / reg
    w = int(window_days) - 1
    batch = RiskBatch(lots=inp.lots, incoming=inp.incoming, shelf=inp.meta["shelf_life_days"].to_numpy(),
                      mu=inp.mu, price=inp.price, cost=np.array([cost]), k=inp.k, path_sigma=inp.path_sigma,
                      elasticity=inp.elasticity, next_delivery=inp.next_delivery, cover_end=inp.cover_end,
                      promo=inp.promo)
    res = simulate(batch, ActionSet(discount=np.array([[0.0, eff]]), window=np.array([-1, w])), n_paths=n_paths, seed=11,
                   stickers=inp.stickers)
    units_labelled = int(inp.lots[0, : w + 1].sum()) if w >= 0 else 0
    win_margin = float(1 - res.cogs_window[0, 1] / res.revenue_window[0, 1]) if res.revenue_window[0, 1] > 0 else 0.0
    checks = [
        {"rule": "promo_lock", "ok": not (bool(m["is_promo_today"]) and rules.promotions.lock_markdowns_during_promo)},
        {"rule": "max_discount", "ok": eff <= cap + 1e-9, "limit_pct": 100 * cap},
        {"rule": "unit_margin_floor", "ok": new_price >= cost * (1 + rules.unit_floor(fam)) - 1e-9,
         "min_price": round(cost * (1 + rules.unit_floor(fam)), 2)},
        {"rule": "window_margin_floor", "ok": d == 0 or win_margin >= rules.window_floor(fam),
         "value": round(win_margin, 3), "limit": rules.window_floor(fam)},
        {"rule": "units_to_label", "ok": d == 0 or units_labelled > 0, "units": units_labelled},
        {"rule": "markdown_window", "ok": d == 0 or window_days <= rules.markdown.max_days_before_expiry,
         "limit": rules.markdown.max_days_before_expiry},
        {"rule": "pays_for_itself", "ok": d == 0 or not rules.objective.markdown_must_pay_for_itself
         or float(res.revenue[0, 1] - res.revenue[0, 0]) >= rules.objective.min_revenue_gain,
         "revenue_change": round(float(res.revenue[0, 1] - res.revenue[0, 0]), 2)},
    ]

    def pack(a: int) -> dict:
        return {"waste_units": float(res.waste_units[0, a]), "waste_value": float(res.waste_value[0, a]),
                "p_waste": float(res.p_waste[0, a]), "revenue": float(res.revenue[0, a]),
                "margin": float(res.revenue[0, a] - res.cogs[0, a]), "sold": float(res.sold[0, a]),
                "net_margin": float(res.revenue[0, a] - res.cogs[0, a] - res.waste_value[0, a]),
                "sold_markdown": float(res.sold_markdown[0, a]), "discount_cost": float(res.discount_given[0, a]),
                "p_stockout": float(res.p_stockout[0, a]), "lost_sales": float(res.lost_sales[0, a]),
                "waste_hist": _hist(res.waste_samples[0, a])}

    return {"store_id": store_id, "sku_id": sku_id, "discount_pct": round(100 * eff, 1), "requested_pct": discount_pct,
            "window_days": window_days, "regular_price": reg, "new_price": new_price, "units_labelled": units_labelled,
            "elasticity_mean": float(m["elasticity_mean"]), "n_paths": n_paths, "baseline": pack(0), "scenario": pack(1),
            "checks": checks, "feasible": all(c["ok"] for c in checks)}

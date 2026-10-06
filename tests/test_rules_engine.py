import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from perisentra.decision.engine import EngineInput, decide
from perisentra.decision.rules import Rules


def test_price_snapping_and_family_lookups():
    r = Rules()
    assert r.snap_price(6.245) == 6.29
    assert r.snap_price(5.31) == 5.29
    assert r.max_discount("Anything") == 0.5
    r2 = Rules.model_validate({"markdown": {"max_discount_pct": {"default": 40, "Cheese": 20}}})
    assert r2.max_discount("Cheese") == 0.2 and r2.max_discount("Meat") == 0.4


def test_rules_validation_rejects_bad_values():
    with pytest.raises(ValidationError):
        Rules.model_validate({"markdown": {"ladder_pct": [120]}})
    with pytest.raises(ValidationError):
        Rules.model_validate({"margin": {"unit_floor_pct": {"Meat": 5}}})   # missing default


def _input(n=2, promo=(False, False), expiring=12, mu=4.0):
    H, W = 7, 21
    lots = np.zeros((n, W)); lots[:, 0] = expiring; lots[:, 3] = 5
    meta = pd.DataFrame({
        "store_id": np.arange(n) + 1, "sku_id": 1000 + np.arange(n), "family": "Prepared Foods", "regular_price": 4.99,
        "unit_cost": 2.0, "shelf_life_days": 5, "case_pack": 1, "expiry_imputed": False, "history_days": 200,
        "rel_width": 0.8, "is_promo_today": list(promo), "elasticity_source": "posterior", "elasticity_mean": 2.0,
        "elasticity_sd": 0.1, "reference_order": 10.0, "forecast_today": mu, "forecast_week": mu * 7, "sig_ma28": mu,
        "drivers": [[] for _ in range(n)],
    })
    return EngineInput(meta=meta, lots=lots, incoming=np.zeros((n, H)), mu=np.full((n, H), mu),
                       price=np.full((n, H), 4.99), k=np.full(n, 20.0), path_sigma=np.full(n, 0.05),
                       elasticity=np.full((n, 50), 2.0), next_delivery=np.full(n, 1), cover_end=np.full(n, 2))


def test_engine_marks_down_expiring_overstock_and_respects_promo_lock():
    out = decide(_input(promo=(False, True)), Rules(), n_paths=800, seed=4).recommendations
    assert (out["rules_version"] == Rules().version).all()            # every decision records its rules version
    assert out.loc[0, "action"] == "MARKDOWN"
    assert out.loc[0, "expected_waste_value"] < out.loc[0, "baseline_waste_value"]
    assert out.loc[1, "action"] == "NO_ACTION"                       # promotion running -> locked
    assert "PROMO_LOCK" in out.loc[1, "reason_codes"]


def test_engine_does_not_discount_when_stock_will_sell():
    out = decide(_input(expiring=2, mu=12.0), Rules(), n_paths=800, seed=5).recommendations
    assert (out["action"] == "NO_ACTION").all()
    codes = _codes(out.loc[0])
    assert "WILL_SELL_THROUGH" in codes and "NOT_PROFITABLE" not in codes    # no talk of blocked markdowns


def test_engine_respects_max_discount():
    rules = Rules.model_validate({"markdown": {"max_discount_pct": {"default": 20}}})
    out = decide(_input(), rules, n_paths=600, seed=6).recommendations
    assert (out["discount_pct"] <= 20 + 1e-6).all()


def test_price_endings_never_push_a_discount_past_the_cap():
    """3.99 at a 30% cap: the 30% step must snap to 2.99 (25%), not to the nearer 2.79 (30.1%)."""
    rules = Rules.model_validate({"markdown": {"max_discount_pct": {"default": 30}}})
    assert rules.snap_price(3.99 * 0.7) == 2.79                                # nearest ending, no cap
    assert rules.snap_price(3.99 * 0.7, floor=3.99 * 0.7) == 2.99              # within the cap
    inp = _input(expiring=30, mu=2.0)
    inp.meta["regular_price"] = 3.99
    inp.price[:] = 3.99
    out = decide(inp, rules, n_paths=400, seed=12)
    assert (out.recommendations["discount_pct"] <= 30 + 1e-6).all()
    feasible = [c for item in out.candidates.values() for c in item["candidates"] if c["feasible"]]
    assert feasible and all(c["discount_pct"] <= 30 + 1e-6 for c in feasible)


def test_orders_already_placed_are_netted_out():
    """Regression: two evenings feeding the same delivery must not both order the full requirement."""
    inp = _input(expiring=0, mu=10.0)
    base = decide(inp, Rules(), n_paths=600, seed=8).recommendations
    on_order = np.zeros_like(inp.mu)
    on_order[:, 1] = 60                      # tomorrow's delivery is already fully ordered
    inp.on_order = on_order
    topped = decide(inp, Rules(), n_paths=600, seed=8).recommendations
    assert (topped["order_recommended"] < base["order_recommended"]).all()


def test_partial_rule_updates_keep_the_rest():
    from perisentra.decision.rules import merge_rules

    base = Rules.model_validate({"markdown": {"max_discount_pct": {"default": 50, "Cheese": 30}}}).model_dump()
    merged = Rules.model_validate(merge_rules(base, {"objective": {"tie_tolerance_pct": 9}}))
    assert merged.objective.tie_tolerance_pct == 9 and merged.max_discount("Cheese") == 0.3


def _codes(row) -> dict:
    import json

    return {c["code"]: c["params"] for c in json.loads(row["reason_codes"])}


def test_demand_drivers_agree_with_the_direction_of_the_change():
    inp = _input(expiring=0, mu=4.0)
    inp.meta["demand_norm"] = 8.0                                   # forecast 50% below the full-price norm
    inp.meta["drivers"] = [["weekday_peak", "rain"], ["weekday_low"]]
    out = decide(inp, Rules(), n_paths=300, seed=9).recommendations
    assert _codes(out.loc[0])["DEMAND_BELOW_NORMAL"]["drivers"] == ["rain"]    # a strong weekday cannot explain a drop
    assert _codes(out.loc[1])["DEMAND_BELOW_NORMAL"]["drivers"] == ["weekday_low"]


def test_waste_on_lots_too_fresh_to_mark_down_is_explained():
    inp = _input(expiring=0, mu=0.5)
    inp.lots[:] = 0
    inp.lots[:, 5] = 20                                             # expires in 6 days: outside the markdown window
    out = decide(inp, Rules(), n_paths=300, seed=10).recommendations
    codes = _codes(out.loc[0])
    assert out.loc[0, "action"] == "NO_ACTION"
    assert codes["EXPIRY_RISK"]["days"] == 7 and "MARKDOWN_TOO_EARLY" in codes


def test_no_reorder_for_products_leaving_the_assortment():
    inp = _input(expiring=0, mu=10.0)
    inp.meta["leaving_assortment"] = [True, False]
    out = decide(inp, Rules(), n_paths=300, seed=11).recommendations
    assert out.loc[0, "order_recommended"] == 0 and out.loc[0, "order_reference"] == 0
    assert out.loc[1, "order_recommended"] > 0


def test_a_markdown_blocked_by_rules_is_explained_by_those_rules():
    """When every sticker breaks a rule, the reasons name the rules, not "a markdown is not worth it"."""
    rules = Rules.model_validate({"margin": {"unit_floor_pct": {"default": 150}}})     # price >= 5.00: no sticker fits
    out = decide(_input(expiring=12, mu=4.0), rules, n_paths=300, seed=13).recommendations
    codes = _codes(out.loc[0])
    assert out.loc[0, "action"] == "NO_ACTION"
    assert "UNIT_MARGIN_FLOOR" in codes and "MARKDOWN_NOT_WORTH_IT" not in codes

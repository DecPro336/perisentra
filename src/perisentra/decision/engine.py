"""Decision engine: pick the commercial action for every store-SKU each morning.

Kept separate from the models on purpose: it consumes forecasts, elasticity draws and stock, applies
the business rules from configuration, and can be re-run in seconds when rules change (no retraining).

Selection
    1. candidates: no action, or a sticker of d% (ladder) on lots expiring within w days (w <= rule)
    2. hard constraints: promo lock, max discount per family, price endings, unit margin floor,
       expected margin floor over the markdown window
    3. objective: lowest expected waste value; among actions within the tie tolerance of the best one,
       the highest expected gross margin (avoids discounting units that would sell anyway)
    4. exploration: on a small share of decisions pick uniformly among near-equivalent actions and log
       the propensity, so future elasticity refits see unconfounded price variation
    5. secondary actions: order quantity for the next delivery (newsvendor on simulated paths) and
       donation of units that will still be unsold at close
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from perisentra.config import model_config
from perisentra.decision.rules import Rules
from perisentra.risk.montecarlo import ActionSet, RiskBatch, simulate

STOCKOUT_ALERT = float(model_config()["risk"]["stockout_alert"])
NO_ACTION = "NO_ACTION"
MARKDOWN = "MARKDOWN"


@dataclass
class EngineInput:
    meta: pd.DataFrame            # one row per series (see REQUIRED_META)
    lots: np.ndarray              # (n, W)
    incoming: np.ndarray          # (n, H)
    mu: np.ndarray                # (n, H)
    price: np.ndarray             # (n, H)
    k: np.ndarray                 # (n,)
    path_sigma: np.ndarray        # (n,)
    elasticity: np.ndarray        # (n, D)
    next_delivery: np.ndarray     # (n,)
    cover_end: np.ndarray         # (n,)
    stickers: np.ndarray | None = None   # (n, W) stickers already on the shelf
    on_order: np.ndarray | None = None   # (n, H) units already ordered, arriving on the morning of day h
    promo: np.ndarray | None = None      # (n, H) promotion running that day


REQUIRED_META = ["store_id", "sku_id", "family", "regular_price", "unit_cost", "shelf_life_days", "case_pack",
                 "expiry_imputed", "history_days", "rel_width", "is_promo_today", "elasticity_source",
                 "elasticity_mean", "elasticity_sd", "reference_order", "forecast_today", "forecast_week",
                 "sig_ma28", "drivers"]


@dataclass
class EngineOutput:
    recommendations: pd.DataFrame
    candidates: dict[tuple[int, int], dict] = field(default_factory=dict)   # candidates + waste histograms


def _action_grid(rules: Rules) -> tuple[np.ndarray, np.ndarray]:
    ladder = np.array(rules.markdown.ladder_pct, dtype=float) / 100
    windows = np.arange(rules.markdown.max_days_before_expiry)
    d = np.concatenate([[0.0], np.repeat(ladder, len(windows))])
    w = np.concatenate([[-1], np.tile(windows, len(ladder))])
    return d, w


def _confidence(meta: dict, rules: Rules) -> tuple[float, str, list[dict]]:
    s_fc = float(np.clip(1 - meta["rel_width"] / 2.5, 0, 1))
    s_hist = float(np.clip(meta["history_days"] / 56, 0, 1))
    s_exp = 0.6 if meta["expiry_imputed"] else 1.0
    s_el = (1.0 if meta["elasticity_source"] == "posterior" else 0.7) * float(np.clip(1.2 - meta["elasticity_sd"], 0.4, 1))
    score = 0.4 * s_fc + 0.2 * s_hist + 0.15 * s_exp + 0.25 * s_el
    tier = "HIGH" if score >= rules.confidence.high_min_score else (
        "MEDIUM" if score >= rules.confidence.medium_min_score else "LOW")
    parts = [{"factor": "forecast_precision", "score": round(s_fc, 2)},
             {"factor": "history_length", "score": round(s_hist, 2)},
             {"factor": "expiry_data", "score": round(s_exp, 2)},
             {"factor": "price_response", "score": round(s_el, 2)}]
    return round(score, 3), tier, parts


def _hist(samples: np.ndarray, cap: int = 12) -> list[float]:
    s = np.clip(np.round(samples), 0, cap).astype(int)
    return (np.bincount(s, minlength=cap + 1) / len(s)).round(4).tolist()


def decide(inp: EngineInput, rules: Rules, n_paths: int = 600, seed: int = 0, chunk: int = 32,
           keep_candidates: bool = True, run_id: str = "") -> EngineOutput:
    missing = [c for c in REQUIRED_META if c not in inp.meta.columns]
    if missing:
        raise ValueError(f"engine input is missing columns: {', '.join(missing)}")
    meta = inp.meta.reset_index(drop=True)
    n = len(meta)
    d_grid, w_grid = _action_grid(rules)
    A = len(d_grid)
    rng = np.random.default_rng(seed)
    jj = np.arange(inp.lots.shape[1])

    # per-series effective discounts after price-point snapping, and feasibility masks
    reg = meta["regular_price"].to_numpy(float)
    cost = meta["unit_cost"].to_numpy(float)
    eff = np.zeros((n, A))
    new_price = np.repeat(reg[:, None], A, axis=1)
    blocked = np.full((n, A), "", dtype=object)
    fam = meta["family"].to_numpy()
    max_disc = np.array([rules.max_discount(f) for f in fam])
    snap_cache: dict[tuple[float, float, float | None], float] = {}
    for a in range(1, A):
        for i in range(n):
            # steps within the family's cap snap to a price ending that stays within it; deeper steps are blocked
            floor = reg[i] * (1 - max_disc[i]) if d_grid[a] <= max_disc[i] + 1e-9 else None
            key = (reg[i], d_grid[a], floor)
            if key not in snap_cache:
                snap_cache[key] = rules.snap_price(reg[i] * (1 - d_grid[a]), floor)
            new_price[i, a] = snap_cache[key]
            eff[i, a] = 1 - snap_cache[key] / reg[i]
    unit_floor = np.array([rules.unit_floor(f) for f in fam])
    win_floor = np.array([rules.window_floor(f) for f in fam])
    units_in_window = np.stack([(inp.lots * (jj[None, :] <= w)).sum(1) if w >= 0 else np.zeros(n)
                                for w in w_grid], axis=1)
    promo = meta["is_promo_today"].to_numpy(bool) & rules.promotions.lock_markdowns_during_promo
    for a in range(1, A):
        blocked[:, a] = np.where(units_in_window[:, a] <= 0, "NOTHING_TO_LABEL", blocked[:, a])
        # price endings can round a small discount away entirely
        blocked[:, a] = np.where((blocked[:, a] == "") & (eff[:, a] <= 0.005), "NO_PRICE_CHANGE", blocked[:, a])
        blocked[:, a] = np.where((blocked[:, a] == "") & promo, "PROMO_LOCK", blocked[:, a])
        over_cap = (d_grid[a] > max_disc + 1e-9) | (eff[:, a] > max_disc + 1e-9)       # a hard limit: no tolerance
        blocked[:, a] = np.where((blocked[:, a] == "") & over_cap, "MAX_DISCOUNT", blocked[:, a])
        blocked[:, a] = np.where((blocked[:, a] == "") & (new_price[:, a] < cost * (1 + unit_floor) - 1e-9),
                                 "UNIT_MARGIN_FLOOR", blocked[:, a])

    # identical candidates (same shelf price on the same units) are evaluated once: keep the narrowest window
    for i in range(n):
        seen: set[tuple[float, float]] = set()
        for a in range(1, A):
            if blocked[i, a] in ("NOTHING_TO_LABEL",):
                continue
            key = (round(new_price[i, a], 2), float(units_in_window[i, a]))
            if key in seen:
                blocked[i, a] = "DUPLICATE"
            seen.add(key)

    # Monte Carlo for every candidate (chunked to bound memory)
    fields = ["waste_units", "waste_value", "p_waste", "revenue", "cogs", "sold", "sold_markdown", "discount_given",
              "lost_sales", "p_stockout", "leftover_today", "revenue_window", "cogs_window"]
    res = {f: np.zeros((n, A)) for f in fields}
    required = np.zeros((n, A, n_paths), np.float32)
    waste_hist: dict[int, tuple[list, list]] = {}
    shelf_all = meta["shelf_life_days"].to_numpy()
    has_label = units_in_window[:, 1:].max(1) > 0 if A > 1 else np.zeros(n, dtype=bool)
    for group, actions_for in ((np.nonzero(has_label)[0], "full"), (np.nonzero(~has_label)[0], "none")):
        for c0 in range(0, len(group), chunk if actions_for == "full" else chunk * 8):
            ids = group[c0:c0 + (chunk if actions_for == "full" else chunk * 8)]
            batch = RiskBatch(lots=inp.lots[ids], incoming=inp.incoming[ids], shelf=shelf_all[ids], mu=inp.mu[ids],
                              price=inp.price[ids], cost=cost[ids], k=inp.k[ids], path_sigma=inp.path_sigma[ids],
                              elasticity=inp.elasticity[ids], next_delivery=inp.next_delivery[ids],
                              cover_end=inp.cover_end[ids], promo=None if inp.promo is None else inp.promo[ids])
            if actions_for == "full":
                aset = ActionSet(discount=eff[ids], window=w_grid)
            else:   # nothing to label: only "no action" needs simulating
                aset = ActionSet(discount=np.zeros((len(ids), 1)), window=np.array([-1]))
            out = simulate(batch, aset, n_paths=n_paths, seed=seed + int(ids[0]),
                           stickers=None if inp.stickers is None else inp.stickers[ids])
            for f in fields:
                v = getattr(out, f)
                res[f][ids] = v if v.shape[1] == A else np.repeat(v, A, axis=1)
            rc = out.required_cover
            required[ids] = rc if rc.shape[1] == A else np.repeat(rc, A, axis=1)
            if keep_candidates:
                for j, i in enumerate(ids):
                    waste_hist[int(i)] = out.waste_samples[j] if out.waste_samples.shape[1] == A else \
                        np.repeat(out.waste_samples[j], A, axis=0)

    # expected margin floor over the markdown window
    with np.errstate(divide="ignore", invalid="ignore"):
        win_margin = np.where(res["revenue_window"] > 0, 1 - res["cogs_window"] / res["revenue_window"], 0.0)
    for a in range(1, A):
        blocked[:, a] = np.where((blocked[:, a] == "") & (win_margin[:, a] < win_floor), "WINDOW_MARGIN_FLOOR",
                                 blocked[:, a])

    if rules.objective.markdown_must_pay_for_itself:
        gain = res["revenue"] - res["revenue"][:, :1]
        for a in range(1, A):
            blocked[:, a] = np.where((blocked[:, a] == "") & (gain[:, a] < rules.objective.min_revenue_gain),
                                     "NOT_PROFITABLE", blocked[:, a])

    feasible = blocked == ""
    feasible[:, 0] = True
    margin = res["revenue"] - res["cogs"]

    # the store's current rule (flat sticker in the last days of shelf life), as the reference point
    shelf = meta["shelf_life_days"].to_numpy(int)
    leg_w = np.minimum(rules.legacy.days_before_expiry - 1, shelf - 2)
    leg_d = rules.legacy.markdown_pct / 100
    legacy_idx = np.zeros(n, dtype=int)
    for i in range(n):
        if leg_w[i] >= 0 and inp.lots[i, : leg_w[i] + 1].sum() > 0:
            match = np.nonzero((np.abs(d_grid - leg_d) < 1e-9) & (w_grid == leg_w[i]))[0]
            if len(match):
                legacy_idx[i] = match[0]
    tol = rules.objective.tie_tolerance_pct / 100
    min_gain = rules.objective.min_waste_gain

    rows = []
    candidates: dict[tuple[int, int], list[dict]] = {}
    sl_lo, sl_hi = rules.replenishment.service_level_bounds
    meta_rows = meta.to_dict("records")
    for i in range(n):
        m = meta_rows[i]
        wv = np.where(feasible[i], res["waste_value"][i], np.inf)
        best = float(wv.min())
        near = feasible[i] & (wv <= best + max(tol * best, min_gain))
        # a markdown must beat doing nothing by a meaningful amount
        if res["waste_value"][i, 0] - best < min_gain:
            near = np.arange(A) == 0
        idx_near = np.nonzero(near)[0]
        greedy = int(idx_near[np.argmax(margin[i, idx_near])])
        explored = False
        chosen = greedy
        if len(idx_near) > 1 and rng.random() < rules.exploration.rate:
            chosen = int(rng.choice(idx_near))
            explored = chosen != greedy
        propensity = (1 - rules.exploration.rate) * (chosen == greedy) + rules.exploration.rate / len(idx_near) \
            if len(idx_near) > 1 else 1.0

        # replenishment: newsvendor quantile of simulated requirement for the chosen action
        margin_rate = 1 - cost[i] / reg[i]
        service = float(np.clip(margin_rate + 0.3, sl_lo, sl_hi))
        nxt_i = int(inp.next_delivery[i])
        already = float(inp.on_order[i, nxt_i]) if inp.on_order is not None and nxt_i < inp.mu.shape[1] else 0.0
        req = required[i, chosen] - already          # units already on order for that delivery are netted out
        q_star = float(np.quantile(req, service)) if req.any() else 0.0
        pack = max(int(m["case_pack"]), 1)
        q_rec = int(np.ceil(max(q_star, 0) / pack) * pack)
        q_model = q_rec                               # what the engine itself would order tonight
        ref = float(m["reference_order"])
        order_action = "KEEP"
        if m.get("leaving_assortment"):
            ref, q_rec, q_model = 0.0, 0, 0            # no longer listed: nothing to reorder
        elif rules.replenishment.enabled and nxt_i < inp.mu.shape[1]:
            diff = q_rec - ref
            if abs(diff) >= max(rules.replenishment.min_change_units, rules.replenishment.min_change_pct / 100 * ref):
                if ref > 0:
                    cap = rules.replenishment.max_change_pct / 100 * max(ref, pack)
                    q_rec = float(np.clip(q_rec, max(ref - cap, 0), ref + cap))
                    q_rec = int(np.floor(q_rec / pack) * pack) if q_rec < ref else int(np.ceil(q_rec / pack) * pack)
                if q_rec != round(ref):
                    order_action = "REDUCE" if q_rec < ref else "INCREASE"
            if order_action == "KEEP":
                q_rec = round(ref)
        else:
            q_rec = round(ref)

        donate_units = 0
        if rules.donation.enabled and res["leftover_today"][i, chosen] >= rules.donation.min_units:
            donate_units = round(res["leftover_today"][i, chosen])

        score, tier, parts = _confidence(m, rules)
        reasons = _reasons(i, chosen, m, res, d_grid, w_grid, eff, new_price, blocked, units_in_window, inp,
                           order_action, q_rec, ref, donate_units, explored, rules.donation.tax_benefit_pct,
                           rules.markdown.max_days_before_expiry)
        action = NO_ACTION if chosen == 0 else MARKDOWN
        rows.append({
            "store_id": int(m["store_id"]), "sku_id": int(m["sku_id"]), "family": m["family"], "action": action,
            "discount_pct": round(100 * eff[i, chosen], 1), "markdown_window_days": int(w_grid[chosen] + 1),
            "nominal_discount_pct": round(100 * d_grid[chosen]),
            "units_to_label": int(units_in_window[i, chosen]) if chosen else 0,
            "regular_price": reg[i], "new_price": float(new_price[i, chosen]) if chosen else reg[i],
            "unit_cost": cost[i],
            "expected_waste_units": float(res["waste_units"][i, chosen]),
            "expected_waste_value": float(res["waste_value"][i, chosen]),
            "baseline_waste_units": float(res["waste_units"][i, 0]),
            "baseline_waste_value": float(res["waste_value"][i, 0]),
            "waste_avoided_value": float(res["waste_value"][i, 0] - res["waste_value"][i, chosen]),
            "legacy_action": NO_ACTION if legacy_idx[i] == 0 else MARKDOWN,
            "legacy_waste_value": float(res["waste_value"][i, legacy_idx[i]]),
            "legacy_margin": float(margin[i, legacy_idx[i]]),
            "legacy_net_margin": float(margin[i, legacy_idx[i]] - res["waste_value"][i, legacy_idx[i]]),
            "legacy_discount_cost": float(res["discount_given"][i, legacy_idx[i]]),
            "expected_revenue": float(res["revenue"][i, chosen]), "baseline_revenue": float(res["revenue"][i, 0]),
            "expected_margin": float(margin[i, chosen]), "baseline_margin": float(margin[i, 0]),
            "expected_net_margin": float(margin[i, chosen] - res["waste_value"][i, chosen]),
            "baseline_net_margin": float(margin[i, 0] - res["waste_value"][i, 0]),
            "expected_discount_cost": float(res["discount_given"][i, chosen]),
            "p_waste": float(res["p_waste"][i, chosen]), "p_waste_baseline": float(res["p_waste"][i, 0]),
            "p_stockout": float(res["p_stockout"][i, chosen]), "expected_lost_sales": float(res["lost_sales"][i, chosen]),
            "stock_on_hand": int(inp.lots[i].sum()), "units_expiring_3d": int(inp.lots[i, :3].sum()),
            "order_reference": round(ref), "order_recommended": int(q_rec), "order_action": order_action,
            "order_model": int(q_model),
            "service_level": round(service, 3), "donate_units": donate_units,
            "confidence_score": score, "confidence_tier": tier, "confidence_factors": json.dumps(parts),
            "reason_codes": json.dumps(reasons), "explored": explored, "propensity": round(float(propensity), 4),
            "n_candidates_near": len(idx_near), "forecast_today": float(m["forecast_today"]),
            "forecast_week": float(m["forecast_week"]), "elasticity_mean": float(m["elasticity_mean"]),
            "run_id": run_id, "rules_version": rules.version,
        })
        if keep_candidates:
            cand = []
            for a in range(A):
                if a and blocked[i, a] in ("NOTHING_TO_LABEL", "DUPLICATE", "NO_PRICE_CHANGE"):
                    continue
                cand.append({"action": NO_ACTION if a == 0 else MARKDOWN, "discount_pct": round(100 * eff[i, a], 1),
                             "window_days": int(w_grid[a] + 1), "new_price": float(new_price[i, a]),
                             "waste_units": round(float(res["waste_units"][i, a]), 2),
                             "waste_value": round(float(res["waste_value"][i, a]), 2),
                             "revenue": round(float(res["revenue"][i, a]), 2), "margin": round(float(margin[i, a]), 2),
                             "net_margin": round(float(margin[i, a] - res["waste_value"][i, a]), 2),
                             "p_waste": round(float(res["p_waste"][i, a]), 3),
                             "p_stockout": round(float(res["p_stockout"][i, a]), 3),
                             "window_margin_rate": round(float(win_margin[i, a]), 3),
                             "feasible": bool(feasible[i, a]), "blocked_by": blocked[i, a] or None,
                             "chosen": a == chosen})
            ws = waste_hist[i]
            candidates[(int(m["store_id"]), int(m["sku_id"]))] = {
                "candidates": cand, "waste_hist_baseline": _hist(ws[0]), "waste_hist_chosen": _hist(ws[chosen])}
    return EngineOutput(pd.DataFrame(rows), candidates)


UP_ONLY = {"weekday_peak", "promotion", "pre_holiday"}
DOWN_ONLY = {"weekday_low", "footfall_down", "sibling_promo", "out_of_season"}


def _reasons(i, chosen, m, res, d_grid, w_grid, eff, new_price, blocked, units_in_window, inp, order_action,
             q_rec, ref, donate_units, explored, benefit_pct=0.0, md_days=3) -> list[dict]:
    r: list[dict] = []
    H = inp.mu.shape[1]
    exp3 = int(inp.lots[i, :md_days].sum())          # units close enough to expiry to be marked down
    pw0 = float(res["p_waste"][i, 0])
    blocks = {b for b in blocked[i] if b and b != "NOTHING_TO_LABEL"}
    allowed_markdown = bool((blocked[i, 1:] == "").any())
    if chosen:
        r.append({"code": "EXPIRY_RISK", "level": "warning",
                  "params": {"units": int(units_in_window[i, chosen]), "days": int(w_grid[chosen] + 1),
                             "p_waste": round(pw0 * 100), "waste_amount": round(float(res["waste_value"][i, 0]), 2)}})
        lift = (1 - eff[i, chosen]) ** (-float(m["elasticity_mean"])) - 1
        r.append({"code": "MARKDOWN_LIFT", "level": "info",
                  "params": {"discount": round(100 * eff[i, chosen]), "lift_pct": round(100 * lift),
                             "elasticity": round(float(m["elasticity_mean"]), 2)}})
        r.append({"code": "WASTE_AVOIDED", "level": "success",
                  "params": {"amount": round(float(res["waste_value"][i, 0] - res["waste_value"][i, chosen]), 2),
                             "units": round(float(res["waste_units"][i, 0] - res["waste_units"][i, chosen]), 1)}})
        if abs(new_price[i, chosen] - m["regular_price"] * (1 - d_grid[chosen])) > 0.005:
            r.append({"code": "PRICE_POINT", "level": "info", "params": {"price": float(new_price[i, chosen])}})
    elif exp3 > 0 and pw0 < 0.25:
        r.append({"code": "WILL_SELL_THROUGH", "level": "success",
                  "params": {"p_sell": round((1 - pw0) * 100), "units": exp3}})
    elif exp3 > 0:
        last = int(np.flatnonzero(inp.lots[i, :md_days] > 0).max()) + 1      # 1 = tonight
        r.append({"code": "EXPIRY_RISK", "level": "warning",
                  "params": {"units": exp3, "days": last, "p_waste": round(pw0 * 100),
                             "waste_amount": round(float(res["waste_value"][i, 0]), 2)}})
        if allowed_markdown or not blocks:    # otherwise the rules that blocked every markdown say why
            r.append({"code": "MARKDOWN_NOT_WORTH_IT", "level": "info", "params": {}})
    elif pw0 >= 0.25:
        # the waste risk sits on lots that are still too fresh to mark down: say so, the order absorbs it
        r.append({"code": "EXPIRY_RISK", "level": "warning",
                  "params": {"units": int(inp.lots[i, :H].sum()), "days": H, "p_waste": round(pw0 * 100),
                             "waste_amount": round(float(res["waste_value"][i, 0]), 2)}})
        r.append({"code": "MARKDOWN_TOO_EARLY", "level": "info", "params": {"days": md_days}})
    sells_through = not chosen and exp3 > 0 and pw0 < 0.25
    for b in sorted(blocks) if not sells_through else []:     # no markdown was needed: blocked ones are noise
        if b == "PROMO_LOCK":
            r.append({"code": "PROMO_LOCK", "level": "info", "params": {}})
        elif b in ("UNIT_MARGIN_FLOOR", "WINDOW_MARGIN_FLOOR"):
            deep = [round(100 * eff[i, a]) for a in range(1, len(d_grid)) if blocked[i, a] == b]   # as shown in the table
            r.append({"code": b, "level": "info", "params": {"from_discount": min(deep)}})
        elif b == "MAX_DISCOUNT":
            r.append({"code": "MAX_DISCOUNT", "level": "info", "params": {}})
        elif b == "NOT_PROFITABLE" and not chosen:
            r.append({"code": "NOT_PROFITABLE", "level": "info", "params": {}})
    fc, base = float(m["forecast_today"]), float(m.get("demand_norm") or m["sig_ma28"] or 0)
    if base >= 1 and abs(fc / base - 1) >= 0.15:
        up = fc > base
        # keep only drivers that push demand the same way (rain, heat and holidays depend on the family)
        against = UP_ONLY if not up else DOWN_ONLY
        r.append({"code": "DEMAND_ABOVE_NORMAL" if up else "DEMAND_BELOW_NORMAL", "level": "info",
                  "params": {"pct": round(100 * (fc / base - 1)),
                             "drivers": [d for d in m["drivers"] if d not in against]}})
    if float(res["p_stockout"][i, chosen]) >= STOCKOUT_ALERT:
        r.append({"code": "STOCKOUT_RISK", "level": "warning",
                  "params": {"p": round(100 * float(res["p_stockout"][i, chosen]))}})
    if order_action != "KEEP":
        r.append({"code": f"ORDER_{order_action}", "level": "action",
                  "params": {"reference": round(ref), "recommended": int(q_rec)}})
    if donate_units:
        r.append({"code": "DONATE_AT_CLOSE", "level": "action", "params": {"units": donate_units, "benefit_pct": benefit_pct}})
    if m["expiry_imputed"]:
        r.append({"code": "EXPIRY_IMPUTED", "level": "muted", "params": {}})
    if m["history_days"] < 35:
        r.append({"code": "THIN_HISTORY", "level": "muted", "params": {"days": int(m["history_days"])}})
    if m["elasticity_source"] != "posterior":
        r.append({"code": "ELASTICITY_BORROWED", "level": "muted", "params": {"family": m["family"]}})
    if explored:
        r.append({"code": "EXPLORATION", "level": "muted", "params": {}})
    return r

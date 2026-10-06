"""Assemble the decision engine's inputs from forecasts, stock lots and model artefacts."""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from perisentra.decision.engine import EngineInput

H = 7
LOOKAHEAD_DAYS = 10
# weekdays (Mon = 0) on which each ERP delivery schedule delivers, when the store is open
SCHEDULE_WEEKDAYS = {"daily": {0, 1, 2, 3, 4, 5}, "mon_wed_fri": {0, 2, 4}, "in_store_bake": set(range(7))}


def delivery_offsets(as_of: date, schedules: np.ndarray, store_ids: np.ndarray, store_calendar: pd.DataFrame,
                     horizon: int = LOOKAHEAD_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Offset of the next delivery that tonight's order feeds, and of the delivery after it.

    schedules: the ERP delivery schedule of each series; store_calendar: store_id, date_day, is_open for the next
    days (holiday closures and Sunday closing come from the store master)."""
    cal = store_calendar.copy()
    cal["date_day"] = pd.to_datetime(cal["date_day"]).dt.date
    is_open = cal["is_open"].astype(bool)
    open_days = set(zip(cal.loc[is_open, "store_id"].astype(int), cal.loc[is_open, "date_day"]))
    nxt = np.full(len(schedules), horizon, dtype=int)
    end = np.full(len(schedules), horizon + 1, dtype=int)
    cache: dict[tuple[str, int], tuple[int, int]] = {}
    for i, (sched, sid) in enumerate(zip(schedules, store_ids)):
        key = (sched if sched in SCHEDULE_WEEKDAYS else "daily", int(sid))
        if key not in cache:
            days = [h for h in range(1, horizon + 1)
                    if (key[1], as_of + timedelta(days=h)) in open_days
                    and (as_of + timedelta(days=h)).weekday() in SCHEDULE_WEEKDAYS[key[0]]]
            cache[key] = (days[0] if days else horizon, days[1] if len(days) > 1 else horizon + 1)
        nxt[i], end[i] = cache[key]
    return nxt, end


def _num(row: pd.Series, key: str) -> float:
    v = row.get(key)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f


def drivers(row: pd.Series) -> list[str]:
    """Plain-language demand drivers for today's forecast (used in reason codes)."""
    g = lambda k: _num(row, k)
    out = []
    if row.get("is_in_season") is False or g("is_in_season") == 0:
        return ["out_of_season"]            # leaves the assortment today: nothing else explains the drop
    if g("is_holiday") > 0:
        out.append("holiday")
    elif g("is_pre_holiday") > 0:
        out.append("pre_holiday")
    if g("rain_flag") > 0:
        out.append("rain")
    ta = g("temp_anomaly")
    if ta > 7:           # °F above the seasonal normal
        out.append("heat")
    elif ta < -7:
        out.append("cold")
    base, dow = g("sig_ma28"), g("dow_ma4")
    if base > 0 and not np.isnan(dow):
        if dow / base > 1.15:
            out.append("weekday_peak")
        elif dow / base < 0.85:
            out.append("weekday_low")
    if g("promo_pct") > 0:
        out.append("promotion")
    if g("sibling_promo_share") > 0.3:
        out.append("sibling_promo")
    if g("footfall_trend") < 0.93:
        out.append("footfall_down")
    return out


def build_engine_input(as_of: date, forecasts: pd.DataFrame, X: pd.DataFrame, lots: pd.DataFrame,
                       products: pd.DataFrame, store_calendar: pd.DataFrame, demand_model, elasticity_model,
                       reference_orders: pd.DataFrame | None = None, stickers: dict | None = None,
                       W: int = 21, on_order: pd.DataFrame | None = None) -> EngineInput:
    """forecasts: output of forecast_frame (horizon 1..7 for each series, horizon 1 = as_of).
    lots: store_id, sku_id, expiry_date, qty_on_hand, is_expiry_imputed (stock this morning incl. delivery).
    store_calendar: store_id, date_day, is_open for at least the next LOOKAHEAD_DAYS days.
    on_order: store_id, sku_id, delivery_date, qty_ordered for deliveries after this morning already ordered.
    stickers: {(store_id, sku_id): array of discounts by remaining-life index} already on the shelf.
    """
    fc = forecasts.copy()
    fc["store_id"] = fc["store_id"].astype(int)
    series = fc[["store_id", "sku_id"]].drop_duplicates().sort_values(["store_id", "sku_id"]).reset_index(drop=True)
    n = len(series)
    key = {(s, k): i for i, (s, k) in enumerate(zip(series["store_id"], series["sku_id"]))}
    if fc.empty:
        raise KeyError("no forecasts for the requested store / product")
    idx = np.array([key[(s, k)] for s, k in zip(fc["store_id"], fc["sku_id"])], dtype=int)
    hz = fc["horizon"].to_numpy(int) - 1
    ok = (hz >= 0) & (hz < H)
    mu = np.zeros((n, H))
    mu[idx[ok], hz[ok]] = fc["p50"].to_numpy()[ok]

    meta = series.merge(products[["sku_id", "family", "regular_price", "unit_cost", "shelf_life_days", "case_pack",
                                  "is_expiry_tracked", "delivery_schedule"]], on="sku_id", how="left")

    # promo price on promo days (shelf price before any markdown)
    Xi = X.copy()
    Xi["store_id"] = Xi["store_id"].astype(int)
    Xi["family"] = Xi["family"].astype(str)
    promo = np.zeros((n, H))
    xi = np.array([key.get((s, k), -1) for s, k in zip(Xi["store_id"], Xi["sku_id"])])
    xh = Xi["horizon"].to_numpy(int) - 1
    good = (xi >= 0) & (xh >= 0) & (xh < H)
    promo[xi[good], xh[good]] = Xi["promo_pct"].fillna(0).to_numpy()[good]
    price = meta["regular_price"].to_numpy()[:, None] * (1 - promo)

    # stock lots by remaining life
    lots_arr = np.zeros((n, W))
    imputed = np.zeros(n, dtype=bool)
    if len(lots):
        L = lots.copy()
        L["j"] = (pd.to_datetime(L["expiry_date"]) - pd.Timestamp(as_of)).dt.days
        L = L[(L["j"] >= 0) & (L["qty_on_hand"] > 0)]
        li = np.array([key.get((int(s), int(k)), -1) for s, k in zip(L["store_id"], L["sku_id"])])
        sel = li >= 0
        np.add.at(lots_arr, (li[sel], np.clip(L["j"].to_numpy()[sel], 0, W - 1)), L["qty_on_hand"].to_numpy()[sel])
        imp = L[sel & L["is_expiry_imputed"].to_numpy(bool)]
        for s, k in zip(imp["store_id"], imp["sku_id"]):
            imputed[key[(int(s), int(k))]] = True
    imputed |= ~meta["is_expiry_tracked"].fillna(False).to_numpy(bool)

    nxt, end = delivery_offsets(as_of, meta["delivery_schedule"].fillna("daily").to_numpy(),
                                meta["store_id"].to_numpy(), store_calendar)
    cover = np.zeros(n)
    for i in range(n):
        cover[i] = mu[i, nxt[i]:min(end[i], H)].sum() if nxt[i] < H else 0.0
    if reference_orders is not None and len(reference_orders):
        keyed = series.copy()
        if "weekday" in reference_orders.columns:
            keyed["weekday"] = [(as_of + timedelta(days=int(h))).weekday() for h in nxt]
            ref = keyed.merge(reference_orders, on=["store_id", "sku_id", "weekday"], how="left")["reference_order"]
        else:
            ref = keyed.merge(reference_orders, on=["store_id", "sku_id"], how="left")["reference_order"]
        ref = ref.to_numpy(float)
        ref = np.where(np.isnan(ref), cover * 1.1, ref)
    else:
        ref = cover * 1.1
    # deliveries already ordered; where nothing is on order yet, assume the usual order arrives
    ordered = np.zeros((n, H))
    if on_order is not None and len(on_order):
        oo = on_order.copy()
        oo["h"] = (pd.to_datetime(oo["delivery_date"]) - pd.Timestamp(as_of)).dt.days
        oo = oo[(oo["h"] >= 1) & (oo["h"] < H)]
        oi = np.array([key.get((int(s), int(k)), -1) for s, k in zip(oo["store_id"], oo["sku_id"])], dtype=int)
        sel = oi >= 0
        np.add.at(ordered, (oi[sel], oo["h"].to_numpy(int)[sel]), oo["qty_ordered"].to_numpy(float)[sel])
    incoming = ordered.copy()
    for i in range(n):
        for h in (nxt[i], end[i]):
            if h < H and ordered[i, h] == 0:
                incoming[i, h] = ref[i]

    fam = meta["family"].to_numpy()
    k, sigma = demand_model.family_params(fam)
    el = elasticity_model.draws_for(meta["sku_id"].to_numpy())
    sku_sum = elasticity_model.sku.set_index("sku_id")
    el_mean = sku_sum["mean"].reindex(meta["sku_id"]).fillna(1.5).to_numpy()
    el_sd = sku_sum["sd"].reindex(meta["sku_id"]).fillna(0.5).to_numpy()
    el_src = sku_sum["source"].reindex(meta["sku_id"]).fillna("family_predictive").to_numpy()

    today = fc[fc["horizon"] == 1].set_index(["store_id", "sku_id"])
    x1 = Xi[Xi["horizon"] == 1].set_index(["store_id", "sku_id"])
    t_idx = pd.MultiIndex.from_frame(series)
    meta["expiry_imputed"] = imputed
    meta["history_days"] = today["history_days"].reindex(t_idx).fillna(0).to_numpy()
    meta["rel_width"] = today["rel_width"].reindex(t_idx).fillna(2.0).to_numpy()
    meta["sig_ma28"] = today["sig_ma28"].reindex(t_idx).fillna(0).to_numpy()
    # full-price norm (markdown days excluded): the right yardstick for a no-markdown forecast
    norm = today["demand_norm"] if "demand_norm" in today else today["sig_ma28"]
    meta["demand_norm"] = norm.reindex(t_idx).fillna(0).to_numpy()
    meta["is_promo_today"] = promo[:, 0] > 0
    meta["elasticity_source"] = el_src
    meta["elasticity_mean"] = el_mean
    meta["elasticity_sd"] = el_sd
    meta["reference_order"] = np.round(ref, 1)
    meta["forecast_today"] = mu[:, 0]
    meta["forecast_week"] = mu.sum(1)
    x1r = x1.reindex(t_idx)
    meta["drivers"] = [drivers(r) for _, r in x1r.reset_index(drop=True).iterrows()]
    meta["leaving_assortment"] = ["out_of_season" in d for d in meta["drivers"]]

    st = None
    if stickers is not None:
        st = np.zeros((n, W), dtype=np.float32)
        for (s, kk), arr in stickers.items():
            if (s, kk) in key:
                st[key[(s, kk)], :len(arr)] = arr[:W]
    return EngineInput(meta=meta, lots=lots_arr, incoming=incoming, mu=mu, price=price, k=k, path_sigma=sigma,
                       elasticity=el, next_delivery=nxt, cover_end=end, stickers=st, on_order=ordered,
                       promo=promo > 0)


def reference_orders_from_deliveries(deliveries: pd.DataFrame, as_of: date, weeks: int = 4) -> pd.DataFrame:
    """Typical order for each delivery weekday: mean of the last N same-weekday deliveries."""
    d = deliveries.copy()
    d["delivery_date"] = pd.to_datetime(d["delivery_date"])
    d = d[d["delivery_date"] >= pd.Timestamp(as_of) - pd.Timedelta(weeks=weeks)]
    d["weekday"] = d["delivery_date"].dt.weekday
    return d.groupby(["store_id", "sku_id", "weekday"], as_index=False)["qty_ordered"].mean().rename(
        columns={"qty_ordered": "reference_order"})


def candidates_json(candidates: dict) -> pd.DataFrame:
    return pd.DataFrame([{"store_id": s, "sku_id": k, "payload": json.dumps(v)} for (s, k), v in candidates.items()])

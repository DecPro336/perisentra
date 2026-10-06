"""Write the simulated chain out as separate, imperfect source-system extracts (the inbound exchange folder).

Each folder mimics one system with its own keys, formats and quirks:

    erp/        master data (stores, products with delivery schedules, assortment, price history, holiday
                closures), deliveries with lot expiry (only for expiry-tracked SKUs), open orders
    pos/        daily POS aggregates keyed by POS store code + UPC, with re-sent duplicate batches
    wms/        stock movement ledger (receipts, sales, write-offs, count adjustments) + cycle counts
    quality/    manual waste log (inconsistent reason labels, a few missing entries)
    marketing/  promo calendar (weekly ad), keyed by UPC, with state-level scopes
    footfall/   door counter feed (JSON lines, sensor outages)
    pricing/    markdown label printer log, randomized price-test design log
    storeapp/   what stores did with their daily task list
    _manifests/ one JSON per delivered business day, written last: a consumer starts only when it exists

Ground truth (true demand, true elasticities) stays in the simulator's own folder.
"""

from __future__ import annotations

import json
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from fernbrook.settings import PATHS, get_logger
from fernbrook.world import DayRecord, World

log = get_logger(__name__)

REASON_VARIANTS = {"EXPIRED": ["EXPIRED", "Expired", "out of date", "past sell-by"], "DAMAGED": ["DAMAGED", "dmg"],
                   "DONATED": ["DONATED", "food bank"]}
PROMO_HORIZON_DAYS = 14        # the promo calendar is published two weeks ahead
OPEN_ORDER_DAYS = 4


def _tag_seed(tag: str) -> int:
    digits = tag.replace("-", "").lstrip("p")
    return int(digits) if digits.isdigit() else zlib.crc32(tag.encode())


class Writer:
    """Writes files under the inbound folder and remembers them for the delivery manifest."""

    def __init__(self, inbound: Path):
        self.inbound = inbound
        self.files: dict[str, int] = {}

    def frame(self, df: pd.DataFrame, rel: str, keep_empty: bool = False) -> None:
        if df.empty and not keep_empty:    # an empty event extract is not delivered (e.g. every store closed)
            return
        path = self.inbound / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        if rel.endswith(".parquet"):
            df.to_parquet(tmp, index=False)
        else:
            df.to_csv(tmp, index=False)
        tmp.replace(path)
        self.files[rel] = len(df)

    def lines(self, lines: list[str], rel: str) -> None:
        if not lines:
            return
        path = self.inbound / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(path)
        self.files[rel] = len(lines)


def export_records(world: World, records: list[DayRecord], tag: str, writer: Writer, *, daily: bool,
                   first_batch: bool = False) -> None:
    """Event extracts for the given simulated days. Daily deliveries get one file per system; a backfill
    batch is split by month like a historical bulk export."""
    if not records:
        raise ValueError("no simulated days to export")
    s = world.series
    D = len(records)
    t_idx = np.array([r.t for r in records])
    dates = np.array([world.dates[t] for t in t_idx])
    N = world.N
    rng = np.random.default_rng([world.seed, 991, _tag_seed(tag)])

    store_id = np.tile(s["store_id"].to_numpy(), D)
    sku_id = np.tile(s["sku_id"].to_numpy(), D)
    date_col = np.repeat(dates, N)
    active = np.stack([r.active for r in records]).ravel()
    store_open = np.stack([world.store_open[world.store_idx, t] for t in t_idx]).ravel()
    reg_price = np.concatenate([world.regular_price(t) for t in t_idx])

    def col(name: str) -> np.ndarray:
        return np.stack([getattr(r, name) for r in records]).ravel()

    def by_month(df: pd.DataFrame, date_column: str, prefix: str) -> None:
        if daily:
            writer.frame(df, f"{prefix}_{tag}.parquet")
            return
        month = pd.to_datetime(df[date_column]).dt.strftime("%Y_%m")
        for m, chunk in df.groupby(month):
            writer.frame(chunk, f"{prefix}_{m}_{tag}.parquet")

    units = col("units_sold")
    price_ratio = col("price_ratio")
    promo = col("promo_pct")
    md = col("md_pct")

    # ---- POS: one row per price type sold that day ------------------------------------------------
    units_md = col("units_md")
    units_reg = units - units_md
    pos_code = np.tile(s["store_id"].map(lambda i: f"STORE-{i:03d}").to_numpy(), D)
    upc = np.tile(s["upc"].to_numpy(), D)
    dup = col("pos_duplicate")
    parts = []
    for kind, qty in (("REG", units_reg), ("MD", units_md)):
        m = qty > 0
        if kind == "REG":
            disc = np.where(promo[m] > 0, promo[m], 0.0)
            ptype = np.where(promo[m] > 0, "PROMO", "REG")
        else:
            disc = md[m]
            ptype = np.full(int(m.sum()), "MD")
        gross = qty[m] * reg_price[m]
        parts.append(pd.DataFrame({
            "business_date": date_col[m], "store_code": pos_code[m], "upc": upc[m], "units": qty[m].astype(int),
            "gross_amount": np.round(gross, 2), "discount_amount": np.round(gross * disc, 2), "price_type": ptype,
            "batch_id": f"POS-{tag}-001", "_dup": dup[m],
        }))
    pos = pd.concat(parts, ignore_index=True)
    pos["net_amount"] = (pos["gross_amount"] - pos["discount_amount"]).round(2)
    pos = pd.concat([pos, pos[pos["_dup"]].assign(batch_id=f"POS-{tag}-RESEND")], ignore_index=True).drop(columns="_dup")
    by_month(pos, "business_date", "pos/pos_daily_sales")

    # ---- markdown label printer log (stickers / ESL overrides) ---------------------------------------
    labelled = col("md_labelled")
    src = col("source")
    m = (md > 0) & (labelled > 0)
    writer.frame(pd.DataFrame({
        "label_date": date_col[m], "store_id": store_id[m], "sku_id": sku_id[m],
        "discount_pct": np.round(md[m] * 100).astype(int), "units_labelled": labelled[m].astype(int),
        "label_source": np.select([src[m] == 1, src[m] == 2], ["ENGINE", "PRICE_TEST"], "STORE_RULE")}),
        f"pricing/markdown_labels_{tag}.parquet")

    # ---- deliveries (ERP) ---------------------------------------------------------------------------
    received = col("received")
    ordered = col("ordered_for_today")
    life = col("lot_life")
    sel = (ordered > 0) | (received > 0)
    tracked = np.tile(s["expiry_tracked"].to_numpy(), D)
    deliv_dates = date_col[sel]
    expiry = (pd.to_datetime(deliv_dates) + pd.to_timedelta(life[sel] - 1, unit="D")).date
    deliveries = pd.DataFrame({
        "delivery_date": deliv_dates, "store_id": store_id[sel], "sku_id": sku_id[sel],
        "qty_ordered": ordered[sel].astype(int), "qty_received": received[sel].astype(int),
        "expiry_date": np.where(tracked[sel], expiry, None),
    })
    deliveries.insert(0, "lot_id", [f"L{tag.replace('-', '')}{i:08d}" for i in range(len(deliveries))])
    writer.frame(deliveries, f"erp/deliveries/deliveries_{tag}.parquet")

    # ---- WMS stock movements ------------------------------------------------------------------------
    waste_rec = col("waste_recorded")
    damaged = col("damaged")
    donated = col("donated")
    adjust = col("adjust")
    write_off = waste_rec + damaged + donated
    mv = []
    for mtype, qty in (("RECEIPT", received), ("SALE", -units), ("WRITE_OFF", -write_off), ("ADJUST", adjust)):
        nz = qty != 0
        mv.append(pd.DataFrame({"movement_date": date_col[nz], "store_id": store_id[nz], "sku_id": sku_id[nz],
                                "movement_type": mtype, "quantity": qty[nz].astype(int)}))
    if first_batch:
        first_open = records[0].book_open
        nz = first_open != 0
        mv.append(pd.DataFrame({"movement_date": dates[0], "store_id": s["store_id"].to_numpy()[nz],
                                "sku_id": s["sku_id"].to_numpy()[nz], "movement_type": "OPENING",
                                "quantity": first_open[nz].astype(int)}))
    by_month(pd.concat(mv, ignore_index=True), "movement_date", "wms/movements/stock_movements")

    counted = col("counted")
    nz = counted >= 0
    writer.frame(pd.DataFrame({"count_date": date_col[nz], "store_id": store_id[nz], "sku_id": sku_id[nz],
                               "counted_qty": counted[nz].astype(int),
                               "book_qty": (counted[nz] - adjust[nz]).astype(int)}), f"wms/cycle_counts_{tag}.csv")

    # ---- waste log (manual entry) ---------------------------------------------------------------------
    cost = np.tile(s["unit_cost"].to_numpy(), D)
    wl = []
    for reason, qty in (("EXPIRED", waste_rec), ("DAMAGED", damaged), ("DONATED", donated)):
        nz = qty > 0
        n = int(nz.sum())
        variants = REASON_VARIANTS[reason]
        labels = np.where(rng.random(n) < 0.9, variants[0], rng.choice(variants, n))
        wl.append(pd.DataFrame({"log_date": date_col[nz], "store_id": store_id[nz], "sku_id": sku_id[nz],
                                "quantity": qty[nz].astype(int), "reason": labels,
                                "value_at_cost": np.round(qty[nz] * cost[nz], 2)}))
    waste = pd.concat(wl, ignore_index=True)
    waste.loc[rng.random(len(waste)) < 0.02, "value_at_cost"] = np.nan
    writer.frame(waste, f"quality/waste_log_{tag}.csv")

    # ---- footfall counters ----------------------------------------------------------------------------
    foot = np.stack([r.footfall for r in records])
    miss = np.stack([r.footfall_missing for r in records])
    sopen = np.stack([world.store_open[:, t] for t in t_idx])
    lines = [json.dumps({"sensor": f"DOOR-{sid:03d}", "store_id": int(sid), "date": dates[di].isoformat(),
                         "entries": int(foot[di, si])})
             for di in range(D) for si, sid in enumerate(world.store_ids) if sopen[di, si] and not miss[di, si]]
    writer.lines(lines, f"footfall/footfall_{tag}.jsonl")

    # ---- randomized price test design log ---------------------------------------------------------------
    test = col("test_pct")
    in_window = np.repeat((t_idx >= world.test_start) & (t_idx <= world.test_end), N)
    in_store = np.tile(world.in_test_store, D)
    nz = in_window & in_store & active & store_open & (promo == 0)
    if nz.any():
        writer.frame(pd.DataFrame({"test_id": "PT-2026-SPRING", "store_id": store_id[nz], "sku_id": sku_id[nz],
                                   "test_date": date_col[nz],
                                   "assigned_discount_pct": np.round(test[nz] * 100).astype(int)}),
                     f"pricing/price_test_assignments_{tag}.csv")

    # ---- ground truth (kept by the simulator) -----------------------------------------------------------
    live = active & store_open
    truth = pd.DataFrame({"date": date_col[live], "store_id": store_id[live], "sku_id": sku_id[live],
                          "true_demand": col("true_demand")[live].astype(int),
                          "true_extra": col("true_extra")[live].astype(int),
                          "units_md": units_md[live].astype(int), "md_pct": md[live].astype(np.float32),
                          "true_mu": col("true_mu")[live].astype(np.float32),
                          "units_sold": units[live].astype(int), "price_ratio": price_ratio[live].astype(np.float32),
                          "policy_source": src[live].astype(np.int8),
                          "waste_recorded": waste_rec[live].astype(int),
                          "waste_unrecorded": col("waste_unrecorded")[live].astype(int),
                          "damaged": damaged[live].astype(int), "donated_units": donated[live].astype(int),
                          "unit_cost": cost[live].astype(np.float32),
                          "regular_price": reg_price[live].astype(np.float32),
                          "phys_close": col("phys_close")[live].astype(int)})
    PATHS.truth.mkdir(parents=True, exist_ok=True)
    truth.to_parquet(PATHS.truth / f"truth_{tag}.parquet", index=False)


def export_masters(world: World, writer: Writer) -> None:
    """Master data and forward-looking extracts, as of the morning of `world.today`."""
    cat = world.catalog
    stores = cat.stores.copy()
    stores["sunday_open"] = stores["format"].map(lambda f: world.cfg["formats"][f]["sunday"] > 0)
    writer.frame(stores[["store_id", "pos_code", "name", "city", "region", "format", "lat", "lon", "surface_sqft",
                         "opened", "sunday_open"]], "erp/stores.csv", keep_empty=True)
    prods = cat.products.copy()
    prods["season_months"] = prods["season_months"].map(lambda m: "" if m is None else ",".join(map(str, m)))
    prods["delivery_schedule"] = prods["sku_id"].map(world.delivery_schedule())
    writer.frame(prods.drop(columns=["delivery"]), "erp/products.csv", keep_empty=True)
    writer.frame(cat.assortment, "erp/assortment.csv", keep_empty=True)
    step = world.cfg["world"]["inflation_step"]
    writer.frame(pd.concat([
        pd.DataFrame({"sku_id": world.series["sku_id"], "valid_from": world.t0, "regular_price": world.price_before}),
        pd.DataFrame({"sku_id": world.series["sku_id"], "valid_from": pd.to_datetime(str(step["date"])).date(),
                      "regular_price": world.price_after}),
    ]).drop_duplicates(["sku_id", "valid_from"]), "erp/price_history.csv", keep_empty=True)
    writer.frame(world.closures(), "erp/store_closures.csv", keep_empty=True)

    promos = world.promotions[world.promotions["start_date"] <= world.today + timedelta(days=PROMO_HORIZON_DAYS)].copy()
    reg = dict(zip(cat.products["sku_id"], cat.products["regular_price"]))
    promos["promo_price"] = [round(reg[s] * (1 - p / 100), 2) for s, p in zip(promos["sku_id"], promos["discount_pct"])]
    promos["in_flyer"] = promos["in_flyer"].map({True: "Y", False: "N"})
    writer.frame(promos.drop(columns=["sku_id"]), "marketing/promo_calendar.csv", keep_empty=True)

    # orders already placed for the next deliveries
    rows = []
    for k in range(OPEN_ORDER_DAYS):
        t = world.t + k
        if t >= world.n_days:
            break
        q = world.pending[t]
        sel = q > 0
        rows.append(pd.DataFrame({"delivery_date": world.dates[t], "store_id": world.series["store_id"][sel],
                                  "sku_id": world.series["sku_id"][sel], "qty_ordered": q[sel]}))
    open_orders = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["delivery_date", "store_id", "sku_id", "qty_ordered"])
    writer.frame(open_orders, "erp/open_orders.csv", keep_empty=True)

    truth = cat.truth_products.merge(cat.products[["sku_id", "family", "name"]], on="sku_id")
    PATHS.truth.mkdir(parents=True, exist_ok=True)
    truth.to_parquet(PATHS.truth / "products.parquet", index=False)
    design = {"price_test_stores": [int(x) for x in world.test_stores],
              "price_test_window": [str(world.cfg["price_test"]["start"]), str(world.cfg["price_test"]["end"])]}
    (PATHS.truth / "price_test.json").write_text(json.dumps(design, indent=2))


def write_manifest(writer: Writer, business_date: date, kind: str) -> Path:
    """The delivery is complete once its manifest exists (consumers wait for it)."""
    path = writer.inbound / "_manifests" / f"{business_date.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"business_date": business_date.isoformat(), "kind": kind,
            "delivered_at": datetime.now().isoformat(timespec="seconds"), "files": writer.files}
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(body, indent=2))
    tmp.replace(path)
    return path

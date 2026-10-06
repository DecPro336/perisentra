"""Lot-level simulation of a fresh-food retail chain.

The world holds a *hidden* demand process (ground truth) and plays it forward one day at a time:

    morning   deliveries arrive as lots with an expiry date; prices are set (promo / markdown / test)
    day       demand ~ Gamma-Poisson(mu); sales = min(demand, physical stock), depleted FIFO
    evening   damage + unrecorded shrink, expired lots written off (or donated), weekly cycle counts,
              orders placed for the next delivery day

Randomness uses common random numbers: every day draws the same random arrays in the same order
regardless of what the stores decide, so two courses of action replayed from the same state face identical
luck. That is what makes the true effect of a change measurable (see `validation.py`).

The calendar extends as time passes (`horizon_end`); everything already drawn for earlier days stays the same.
Only the dynamic state (stock lots, book errors, stickers, demand shocks, open orders) is saved between runs.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

import numpy as np
import pandas as pd
from scipy import stats

from fernbrook.catalog import Catalog

LEGACY_DOW = np.array([0.90, 0.88, 0.92, 0.95, 1.08, 1.22, 1.10])
# US grocery weekly patterns (Mon..Sun): weekend peaks, Friday seafood, weekend cookouts, weekday lunch trade
FAMILY_DOW = {
    "default": [0.90, 0.86, 0.90, 0.95, 1.08, 1.25, 1.12],
    "Bakery": [0.92, 0.90, 0.92, 0.94, 1.04, 1.22, 1.18],
    "Seafood": [0.80, 0.84, 0.92, 0.98, 1.45, 1.20, 0.95],
    "Meat": [0.85, 0.84, 0.88, 0.94, 1.15, 1.40, 1.20],
    "Prepared Foods": [1.04, 1.04, 1.04, 1.06, 1.10, 0.95, 0.86],
}
SEASON_SIGN = {"Salads & Fresh-Cut": 1, "Fresh Juice": 1, "Produce": 1, "Meat": 1, "Cheese": -1,
               "Prepared Foods": -1, "Deli Meats": -1, "Pastries & Desserts": -1, "Dairy": 1, "Seafood": -1,
               "Bakery": 0}
MAJOR_HOLIDAYS = {"New Year's Day", "Memorial Day", "Independence Day", "Labor Day", "Labour Day", "Thanksgiving Day",
                  "Christmas Day"}
COOKOUT_HOLIDAYS = {"Memorial Day", "Independence Day", "Labor Day", "Labour Day"}


STATE_ARRAYS = ("lots", "book_offset", "sticker", "ar", "sales_buf", "sales_cal", "soldout_cal")
PENDING_AHEAD = 16          # days of open orders kept in the saved state


class Policy(Protocol):
    def __call__(self, world: World, t: int) -> Actions: ...


@dataclass
class Actions:
    """Decisions for one morning. Arrays are length N (series); NaN / -1 means 'the store's current rule'."""
    markdown_pct: np.ndarray
    markdown_window: np.ndarray | None = None     # stickers on lots with remaining life <= window
    order_override: np.ndarray | None = None      # units for the order placed this evening (-1 = legacy)
    donate: np.ndarray | None = None              # donate expiring units at close instead of wasting
    source: np.ndarray | None = None              # 0 current rule, 1 task carried out, 2 price test, 3 task not done


@dataclass
class DayRecord:
    t: int
    units_sold: np.ndarray
    price_ratio: np.ndarray
    md_pct: np.ndarray
    promo_pct: np.ndarray
    flyer: np.ndarray
    test_pct: np.ndarray
    received: np.ndarray
    ordered_for_today: np.ndarray
    lot_life: np.ndarray
    waste_recorded: np.ndarray
    waste_unrecorded: np.ndarray
    damaged: np.ndarray
    donated: np.ndarray
    counted: np.ndarray
    adjust: np.ndarray
    book_open: np.ndarray
    book_close: np.ndarray
    phys_close: np.ndarray
    true_demand: np.ndarray
    true_mu: np.ndarray
    units_md: np.ndarray
    md_labelled: np.ndarray
    true_extra: np.ndarray
    active: np.ndarray
    footfall: np.ndarray
    footfall_missing: np.ndarray
    source: np.ndarray
    pos_duplicate: np.ndarray


@dataclass
class World:
    cfg: dict
    catalog: Catalog
    weather: pd.DataFrame          # location_id(store_id), date, temp_max, temp_min, precipitation
    holidays: pd.DataFrame         # date, name
    seed: int
    horizon_end: date              # last day of the calendar (extended on every run)
    t0: date = field(init=False)
    records: list[DayRecord] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        cfg, cat = self.cfg, self.catalog
        cal = cfg["calendar"]
        self.start = date.fromisoformat(str(cal["start_date"]))
        self.t0 = self.start - timedelta(days=int(cal["warmup_days"]))
        self.n_days = (self.horizon_end - self.t0).days + 1
        self.dates = [self.t0 + timedelta(days=i) for i in range(self.n_days)]
        rng = np.random.default_rng(self.seed)

        s = (cat.assortment.merge(cat.products, on="sku_id").merge(cat.truth_products, on="sku_id")
             .merge(cat.stores[["store_id", "format", "city", "region"]], on="store_id")
             .merge(cat.truth_stores, on="store_id")
             .sort_values(["store_id", "sku_id"]).reset_index(drop=True))
        self.series = s
        self.N = len(s)
        self.store_ids = cat.stores["store_id"].to_numpy()
        self.S = len(self.store_ids)
        sidx = {sid: i for i, sid in enumerate(self.store_ids)}
        self.store_idx = s["store_id"].map(sidx).to_numpy()
        fams = list(cfg["families"])
        self.families = fams
        self.family_idx = s["family"].map({f: i for i, f in enumerate(fams)}).to_numpy()
        self.sub_key = (s["store_id"].astype(str) + "|" + s["subfamily"]).to_numpy()
        self.sub_codes, self.sub_inv = np.unique(self.sub_key, return_inverse=True)

        self.shelf = s["shelf_life_days"].to_numpy().astype(int)
        self.W = int(self.shelf.max()) + 1
        self.pack = s["case_pack"].to_numpy().astype(int)
        self.cost = s["unit_cost"].to_numpy()
        self.base = (s["base_demand"] * s["store_scale"]).to_numpy()
        self.elasticity = s["true_elasticity"].to_numpy()
        self.k = s["dispersion_k"].to_numpy()
        self.promo_boost = s["promo_boost"].to_numpy()
        self.festive = s["festive_mult"].to_numpy()
        occasions = ["generic", "thanksgiving", "winter", "cookout"]
        self.festive_occasion = s["festive_occasion"].map({o: i for i, o in enumerate(occasions)}).to_numpy()
        self.trend = s["trend_per_year"].to_numpy()
        self.season_amp = s["season_amp"].to_numpy() * s["family"].map(SEASON_SIGN).fillna(0).to_numpy()
        self.season_phase = s["season_phase"].to_numpy()
        self.temp_sens = s["temp_sens"].to_numpy()
        self.hot_sens = s["hot_sens"].to_numpy()
        self.rain_sens = s["rain_sens"].to_numpy()
        self.dow_profile = np.array([FAMILY_DOW.get(f, FAMILY_DOW["default"]) for f in s["family"]])
        self.sunday_factor_store = cat.truth_stores.set_index("store_id").loc[self.store_ids, "sunday_factor"].to_numpy()
        self.footfall_base = cat.truth_stores.set_index("store_id").loc[self.store_ids, "footfall_base"].to_numpy()
        self.summer = cat.stores.set_index("store_id").loc[self.store_ids, "summer_effect"].to_numpy(float)
        self.listed_from = pd.to_datetime(s["listed_from"]).dt.date.to_numpy()
        self.season_months = s["season_months"].to_numpy()

        self._build_calendar()
        self._build_activity()
        self._build_prices()
        self._build_promotions(rng)
        self._build_price_test(rng)
        self._build_delivery_schedule()

        # ---- state -----------------------------------------------------------------------------
        self.lots = np.zeros((self.N, self.W), dtype=np.int32)
        init = np.ceil(self.base * 1.5).astype(np.int32)
        self.lots[np.arange(self.N), np.maximum(self.shelf - 2, 0)] = init
        self.book_offset = np.zeros(self.N, dtype=np.int32)
        self.sticker = np.zeros((self.N, self.W), dtype=np.float32)
        self.ar = np.zeros(self.N)
        window = int(cfg["legacy_policy"]["forecast_window_days"])      # the store rule's recent-sales window
        self.sales_buf = np.tile(self.base[:, None], (1, window)).astype(float)
        self.sales_cal = np.full((self.N, 28), np.nan)   # calendar-aligned history (NaN on closed days)
        self.soldout_cal = np.zeros((self.N, 28))         # 1 when the shelf emptied that day
        self.pending = np.zeros((self.n_days + 8, self.N), dtype=np.int32)
        self.t = 0

    # ------------------------------------------------------------------------------------------
    # static calendar / exogenous inputs
    # ------------------------------------------------------------------------------------------
    def _build_calendar(self) -> None:
        cal = self.cfg["calendar"]
        closed_md = set(cal["closed_holidays"])
        closed_names = set(cal.get("closed_holiday_names", []))
        hol = {d: n for d, n in zip(self.holidays["date"], self.holidays["name"])}
        D, S = self.n_days, self.S
        self.dow = np.array([d.weekday() for d in self.dates])
        self.month = np.array([d.month for d in self.dates])
        self.is_holiday = np.array([d in hol for d in self.dates])
        major = lambda n: n in MAJOR_HOLIDAYS
        self.is_major_holiday = np.array([d in hol and major(hol[d]) for d in self.dates])
        self.is_pre_holiday = np.array([(d + timedelta(days=1)) in hol and major(hol[d + timedelta(days=1)])
                                        for d in self.dates])
        self.store_open = np.ones((S, D), dtype=bool)
        for i, d in enumerate(self.dates):
            if d.strftime("%m-%d") in closed_md or hol.get(d) in closed_names:
                self.store_open[:, i] = False
            if d.weekday() == 6:
                self.store_open[self.sunday_factor_store == 0, i] = False
        # holiday shopping peaks by occasion: generic, thanksgiving, winter, cookout
        self.festive_day = np.zeros((4, D))
        for i, d in enumerate(self.dates):
            for ahead, w in ((1, 1.0), (2, 0.85), (3, 0.5)):
                if hol.get(d + timedelta(days=ahead)) == "Thanksgiving Day":
                    self.festive_day[1, i] = max(self.festive_day[1, i], w)
            if d.month == 12 and d.day in (23, 24, 30, 31):
                self.festive_day[2, i] = 1.0
            elif d.month == 12 and 18 <= d.day <= 22:
                self.festive_day[2, i] = 0.35
            for ahead, w in ((0, 0.5), (1, 1.0), (2, 0.8), (3, 0.4)):
                if hol.get(d + timedelta(days=ahead)) in COOKOUT_HOLIDAYS:
                    self.festive_day[3, i] = max(self.festive_day[3, i], w)
        self.festive_day[0] = np.maximum(self.festive_day[1] * 0.8, self.festive_day[2])

        w = self.weather.copy()
        w["date"] = pd.to_datetime(w["date"]).dt.date
        w = w.set_index(["location_id", "date"])
        idx = pd.MultiIndex.from_product([self.store_ids, self.dates])
        w = w.reindex(idx)
        self.temp_max = w["temp_max"].astype(float).to_numpy().reshape(S, D)
        self.precip = w["precipitation"].astype(float).fillna(0).to_numpy().reshape(S, D)
        self.temp_max = pd.DataFrame(self.temp_max).ffill(axis=1).bfill(axis=1).to_numpy()

        comp = np.ones((S, D))
        sidx = {sid: i for i, sid in enumerate(self.store_ids)}
        for c in self.cfg["world"].get("competitor_openings", []):
            if c["store_id"] not in sidx:
                continue
            d0 = date.fromisoformat(str(c["date"]))
            i0 = max(0, (d0 - self.t0).days)
            comp[sidx[c["store_id"]], i0:] *= (1 + c["effect"])
        self.competitor = comp

    def _build_activity(self) -> None:
        listed = np.array([[lf <= d for d in self.dates] for lf in self.listed_from])
        months = self.month[None, :]
        season = np.ones_like(listed)
        for i, m in enumerate(self.season_months):
            if m is not None and not (isinstance(m, float) and np.isnan(m)):
                season[i] = np.isin(months[0], list(m))
        self.active_mat = listed & season

    def _build_prices(self) -> None:
        step = self.cfg["world"]["inflation_step"]
        d_step = date.fromisoformat(str(step["date"]))
        base_price = self.series["regular_price"].to_numpy() / (1 + step["pct"] / 100)
        self.price_before = np.round(np.floor(base_price) + np.clip(np.round(base_price % 1, 2), 0.09, 0.99), 2)
        self.price_after = self.series["regular_price"].to_numpy()
        self.price_step_idx = (d_step - self.t0).days

    def regular_price(self, t: int) -> np.ndarray:
        return self.price_after if t >= self.price_step_idx else self.price_before

    def _promo_week(self, rng: np.random.Generator, d: date, pid: int, regions: list[str]) -> tuple[list[dict], int]:
        """The weekly ad starting on Wednesday `d`: about 4.5% of launched products, bakery rarely."""
        prods = self.catalog.products
        launched = prods[pd.to_datetime(prods["launch_date"]).dt.date <= d]
        weights = np.where(launched["family"] == "Bakery", 0.2, 1.0)
        n = rng.binomial(len(launched), 0.045)
        picks = launched.sample(n=n, weights=weights, random_state=int(rng.integers(1e9)))
        rows = []
        for _, p in picks.iterrows():
            pid += 1
            pct = float(rng.choice([15, 20, 25, 30, 34], p=[0.2, 0.3, 0.25, 0.17, 0.08]))
            scope = "NATIONAL" if rng.random() < 0.7 else f"REGION:{rng.choice(regions)}"
            rows.append({"promo_id": f"P{pid}", "sku_id": p["sku_id"], "upc": p["upc"], "start_date": d,
                         "end_date": d + timedelta(days=6), "discount_pct": pct,
                         "in_flyer": bool(rng.random() < 0.6), "scope": scope})
        return rows, pid

    def _build_promotions(self, rng: np.random.Generator) -> None:
        regions = sorted(self.catalog.stores["region"].unique())
        sequential_until = date.fromisoformat(str(self.cfg["calendar"]["sequential_promotions_until"]))
        rows: list[dict] = []
        pid = 5000
        d = self.t0
        while d.weekday() != 2:
            d += timedelta(days=1)
        # weeks of the generated history come from one sequence (whatever the horizon, so later draws on `rng`,
        # such as the price-test stores, never change); every later week has its own stream
        while d <= sequential_until:
            week, pid = self._promo_week(rng, d, pid, regions)
            rows += week
            d += timedelta(days=7)
        while d <= self.horizon_end:
            week, pid = self._promo_week(np.random.default_rng([self.seed, 7001, d.toordinal()]), d, pid, regions)
            rows += week
            d += timedelta(days=7)
        promos = pd.DataFrame(rows)
        promos = promos[promos["start_date"] <= self.horizon_end].reset_index(drop=True)
        self.promotions = promos
        D = self.n_days
        self.promo_pct = np.zeros((self.N, D), dtype=np.float32)
        self.flyer = np.zeros((self.N, D), dtype=bool)
        key = {sk: i for i, sk in enumerate(zip(self.series["store_id"], self.series["sku_id"]))}
        store_region = self.catalog.stores.set_index("store_id")["region"].to_dict()
        by_sku: dict[int, list[int]] = {}
        for i, sku in enumerate(self.series["sku_id"]):
            by_sku.setdefault(int(sku), []).append(i)
        for p in promos.itertuples():
            i0 = (p.start_date - self.t0).days
            i1 = min(D - 1, (p.end_date - self.t0).days)
            for si in by_sku.get(int(p.sku_id), []):
                st = int(self.series.at[si, "store_id"])
                if p.scope != "NATIONAL" and p.scope.split(":", 1)[1] != store_region[st]:
                    continue
                self.promo_pct[si, i0:i1 + 1] = p.discount_pct / 100
                self.flyer[si, i0:i1 + 1] = p.in_flyer
        del key
        # sibling promo pressure (cannibalisation): share of other SKUs in the store-subfamily on promo
        on = (self.promo_pct > 0).astype(np.float32)
        sums = np.zeros((len(self.sub_codes), D), dtype=np.float32)
        np.add.at(sums, self.sub_inv, on)
        counts = np.bincount(self.sub_inv, minlength=len(self.sub_codes)).astype(np.float32)
        others = np.maximum(counts[self.sub_inv] - 1, 1)
        self.sibling_promo = np.clip((sums[self.sub_inv] - on) / others[:, None], 0, 1)

    def _build_price_test(self, rng: np.random.Generator) -> None:
        pt = self.cfg["price_test"]
        stores = rng.choice(self.store_ids, size=pt["n_stores"], replace=False)
        self.test_stores = np.sort(stores)
        self.test_start = (date.fromisoformat(str(pt["start"])) - self.t0).days
        self.test_end = (date.fromisoformat(str(pt["end"])) - self.t0).days
        self.in_test_store = np.isin(self.series["store_id"].to_numpy(), self.test_stores)

    def _build_delivery_schedule(self) -> None:
        cls = self.series["delivery"].map({"daily": 0, "mwf": 1}).to_numpy().copy()
        cls[self.series["family"].to_numpy() == "Bakery"] = 2  # baked in store every open day
        self.delivery_class = cls
        D = self.n_days
        dow = self.dow
        deliv = np.zeros((3, self.S, D), dtype=bool)
        deliv[0] = (dow < 6)[None, :] & self.store_open
        deliv[1] = np.isin(dow, [0, 2, 4])[None, :] & self.store_open
        deliv[2] = self.store_open
        # next delivery index strictly after t for each (class, store)
        nxt = np.full((3, self.S, D + 1), D + 7, dtype=np.int32)
        for c in range(3):
            for si in range(self.S):
                running = D + 7
                for t in range(D - 1, -1, -1):
                    nxt[c, si, t] = running
                    if deliv[c, si, t]:
                        running = t
        self.deliv = deliv
        self.next_delivery = nxt

    # ------------------------------------------------------------------------------------------
    # dynamics
    # ------------------------------------------------------------------------------------------
    def active(self, t: int) -> np.ndarray:
        return self.active_mat[:, t]

    def mu(self, t: int, price_ratio: np.ndarray, store_shock: np.ndarray, active: np.ndarray) -> np.ndarray:
        si = self.store_idx
        d = self.dates[t]
        doy = d.timetuple().tm_yday
        dow = self.dow[t]
        dow_eff = self.dow_profile[:, dow]
        if dow == 6:
            dow_eff = dow_eff * self.sunday_factor_store[si]
        season = np.exp(self.season_amp * np.sin(2 * np.pi * (doy - 109) / 365.25 + self.season_phase))
        years = (t - 365) / 365.25
        trend = np.exp(self.trend * years)
        tmax = self.temp_max[si, t]
        wc = self.cfg["world"]["weather"]
        weather = np.exp(self.temp_sens * (tmax - wc["temp_base_f"]) + self.hot_sens * np.maximum(tmax - wc["hot_threshold_f"], 0)
                         + self.rain_sens * (self.precip[si, t] > wc["rain_threshold_in"]))
        hol = (0.85 if self.is_major_holiday[t] else 0.97) if self.is_holiday[t] else (1.12 if self.is_pre_holiday[t] else 1.0)
        fest = 1 + (self.festive - 1) * self.festive_day[self.festive_occasion, t]
        aug = 1 + self.summer[si] * self._summer_weight(d)
        promo = self.promo_pct[:, t] > 0
        promo_eff = np.where(promo, self.promo_boost, 1.0) * np.where(self.flyer[:, t], 1.22, 1.0)
        cannib = 1 - 0.10 * self.sibling_promo[:, t] * (~promo)
        price_eff = np.power(np.clip(price_ratio, 0.2, 1.5), -self.elasticity)
        mu = (self.base * dow_eff * season * trend * weather * hol * fest * aug
              * self.competitor[si, t] * np.exp(self.ar) * np.exp(store_shock[si]) * promo_eff * cannib * price_eff)
        mu = mu * self.store_open[si, t] * active
        return mu

    @staticmethod
    def _summer_weight(d: date) -> float:
        """College towns empty out and lake towns fill up from late May to late August."""
        if d.month in (6, 7) or (d.month == 8 and d.day <= 20):
            return 1.0
        if (d.month == 5 and d.day >= 15) or (d.month == 8 and d.day > 20):
            return 0.5
        return 0.0

    def _draws(self, t: int) -> dict[str, np.ndarray]:
        r = np.random.default_rng([self.seed, t])
        N, S = self.N, self.S
        return {
            "gamma": r.gamma(self.k, 1 / self.k),
            "u_dem": r.random(N),
            "ar": r.normal(0, 1, N),
            "store_shock": r.normal(0, 1, S),
            "short_u": r.random(N), "short_frac": r.uniform(0.5, 0.9, N),
            "age_u": r.random(N), "damage_u": r.random(N), "shrink_u": r.random(N), "miss_u": r.random(N),
            "foot_noise": r.normal(0, 0.02, S), "outage_u": r.random(S), "test_u": r.random(N),
            "test_lvl": r.integers(0, 4, N), "comply_u": r.random(N), "dup_u": r.random(N),
            "u_extra": r.random(N),
        }

    def step(self, policy: Policy | None = None, record: bool = True) -> DayRecord:
        t = self.t
        wcfg = self.cfg["world"]
        N, si = self.N, self.store_idx
        rnd = self._draws(t)
        active = self.active(t)
        open_ = self.store_open[si, t]

        # ---- morning: receive deliveries --------------------------------------------------------
        ordered = self.pending[t].copy()
        short = rnd["short_u"] < wcfg["shortship_prob"]
        received = np.where(short, np.floor(ordered * rnd["short_frac"]), ordered).astype(np.int32)
        received = received * open_
        aged = (rnd["age_u"] < 0.25) & (self.shelf >= 3)
        life = np.maximum(self.shelf - aged.astype(int), 1)
        self.lots[np.arange(N), life - 1] += received
        if not open_.all():   # deliveries for closed days roll to the next day
            carry = np.where(open_, 0, ordered)
            self.pending[t + 1] += carry.astype(np.int32)

        book_open = self.lots.sum(1) + self.book_offset - received

        # ---- pricing ----------------------------------------------------------------------------
        # Markdowns are day-before-expiry stickers on the oldest lots: `win` is the highest remaining-life index that
        # gets a sticker (-1 = none). A whole-shelf price change (the randomized test) is the special case
        # win = W-1, so a single elasticity governs both.
        promo = self.promo_pct[:, t]
        md, win = self._legacy_markdown()
        source = np.zeros(N, dtype=np.int8)
        test_pct = np.zeros(N)
        in_test = self.in_test_store & (self.test_start <= t <= self.test_end)
        if in_test.any():
            levels = np.array(self.cfg["price_test"]["discount_levels"], dtype=float) / 100
            assigned = (rnd["test_u"] < self.cfg["price_test"]["share_of_sku_days"]) & (promo == 0)
            test_pct = np.where(in_test & assigned, levels[rnd["test_lvl"]], 0.0)
            md = np.where(in_test, test_pct, md)
            win = np.where(in_test, np.where(test_pct > 0, self.W - 1, -1), win)
            source = np.where(in_test, 2, source).astype(np.int8)
        actions = policy(self, t) if policy is not None else None
        donate = np.zeros(N, dtype=bool)
        order_override = None
        if actions is not None:
            engine = ~np.isnan(actions.markdown_pct)
            comply = rnd["comply_u"] < self.cfg["stores_behaviour"]["task_compliance"]
            use = engine & comply
            md = np.where(use, actions.markdown_pct, md)
            if actions.markdown_window is not None:
                win = np.where(use, actions.markdown_window, win)
            source = np.where(use, 1, np.where(engine, 3, source)).astype(np.int8)
            if actions.donate is not None:
                donate = actions.donate & comply
            if actions.order_override is not None:
                order_override = np.where(comply, actions.order_override, -1)
        md = np.where(promo > 0, 0.0, md)
        win = np.where(md > 0, win, -1)
        base_ratio = np.where(promo > 0, 1 - promo, 1.0)

        # stickers persist on the lots they were put on until those units sell or expire; a whole-shelf
        # test price is temporary and applies to every unit for the day
        jj = np.arange(self.W)[None, :]
        test_day = in_test & (test_pct > 0)
        label = (md > 0) & ~test_day
        self.sticker = np.where(label[:, None] & (jj <= win[:, None]) & (self.lots > 0),
                                np.maximum(self.sticker, md[:, None]), self.sticker).astype(np.float32)
        self.sticker[self.lots == 0] = 0
        on_promo = promo > 0
        stick_mask = (self.sticker > 0) & ~on_promo[:, None]
        avail = self.lots.sum(1)
        q_md = np.where(test_day, avail, (self.lots * stick_mask).sum(1))
        md_today = np.where(test_day, test_pct, np.where(q_md > 0, (self.sticker * stick_mask).max(1), 0.0))

        # ---- demand & sales ---------------------------------------------------------------------
        store_shock = wcfg["store_shock_sigma"] * rnd["store_shock"]
        mu = self.mu(t, base_ratio, store_shock, active)
        lam = np.maximum(mu * rnd["gamma"], 1e-9)
        d_base = stats.poisson.ppf(np.clip(rnd["u_dem"], 1e-12, 1 - 1e-12), lam).astype(np.int32)
        uplift = np.power(np.clip(1 - md_today, 0.2, 1.0), -self.elasticity) - 1
        d_extra = stats.poisson.ppf(np.clip(rnd["u_extra"], 1e-12, 1 - 1e-12),
                                    np.maximum(lam * uplift, 1e-9)).astype(np.int32)
        sold_md_base = np.minimum(d_base, q_md)
        sold_md = sold_md_base + np.minimum(d_extra, q_md - sold_md_base)
        sold_reg = np.minimum(d_base - sold_md_base, avail - q_md)
        sales = (sold_md + sold_reg).astype(np.int32)
        self._deplete(sales)
        md = md_today
        with np.errstate(invalid="ignore", divide="ignore"):
            price_ratio = np.where(sales > 0, (sold_md * (1 - md) + sold_reg * base_ratio) / np.maximum(sales, 1),
                                   np.where(test_day, 1 - md, base_ratio))

        damaged = np.maximum(stats.binom.ppf(np.clip(rnd["damage_u"], 1e-12, 1), self.lots.sum(1),
                                             wcfg["damage_rate"]), 0).astype(np.int32)
        self._deplete(damaged)
        shrink = np.maximum(stats.binom.ppf(np.clip(rnd["shrink_u"], 1e-12, 1), self.lots.sum(1),
                                            wcfg["unrecorded_shrink_rate"]), 0).astype(np.int32)
        self._deplete(shrink)
        self.book_offset += shrink

        # ---- evening: expiry, donation, counts ---------------------------------------------------
        expired = self.lots[:, 0].copy()
        donated = np.where(donate, expired, 0)
        wasted = expired - donated
        missed = (rnd["miss_u"] < wcfg["waste_log_miss_rate"]) & (wasted > 0)
        waste_recorded = np.where(missed, 0, wasted)
        waste_unrecorded = np.where(missed, wasted, 0)
        self.book_offset += waste_unrecorded
        self.lots[:, :-1] = self.lots[:, 1:]
        self.lots[:, -1] = 0
        self.sticker[:, :-1] = self.sticker[:, 1:]
        self.sticker[:, -1] = 0
        self.sticker[self.lots == 0] = 0

        weekday = self.dow[t]
        count_today = (((self.family_idx + self.store_idx) % 6) == weekday) & open_ & (weekday < 6)
        adjust = np.where(count_today, -self.book_offset, 0).astype(np.int32)
        self.book_offset = np.where(count_today, 0, self.book_offset).astype(np.int32)
        phys_close = self.lots.sum(1)
        book_close = phys_close + self.book_offset
        counted = np.where(count_today, phys_close, -1)

        # ---- legacy forecast buffer & orders ----------------------------------------------------
        upd = open_ & active
        if upd.any():
            self.sales_buf = np.where(upd[:, None], np.roll(self.sales_buf, -1, axis=1), self.sales_buf)
            self.sales_buf[upd, -1] = sales[upd]
        # off-season / unlisted items keep the buyer's launch plan so the first order is sensible
        self.sales_buf[~active] = (self.base[~active] * 0.8)[:, None]
        self.sales_cal = np.roll(self.sales_cal, -1, axis=1)
        self.sales_cal[:, -1] = np.where(upd, sales, np.nan)
        self.sales_cal[~active] = np.nan
        self.soldout_cal = np.roll(self.soldout_cal, -1, axis=1)
        self.soldout_cal[:, -1] = np.where(upd, (sales >= avail) & (sales > 0), 0)
        order = self._legacy_order(t, active)
        if order_override is not None:
            use = order_override >= 0
            order = np.where(use, order_override, order) * self.store_open[si, t]
        nxt = self.next_delivery[self.delivery_class, si, t]
        valid = nxt < self.n_days
        np.add.at(self.pending, (nxt[valid], np.nonzero(valid)[0]), order[valid].astype(np.int32))

        # ---- footfall ---------------------------------------------------------------------------
        sopen = self.store_open[:, t]
        dow_s = np.array([0.88, 0.85, 0.88, 0.92, 1.08, 1.25, 1.14])[weekday]
        if weekday == 6:
            dow_s = dow_s * self.sunday_factor_store
        rain = np.where(self.precip[:, t] > self.cfg["world"]["weather"]["rain_threshold_in"], 0.94, 1.0)
        d = self.dates[t]
        aug = 1 + self.summer * self._summer_weight(d)
        footfall = (self.footfall_base * dow_s * rain * aug * self.competitor[:, t] * np.exp(store_shock)
                    * np.exp(rnd["foot_noise"]) * (0.85 if self.is_holiday[t] else 1.0) * sopen)
        outage = rnd["outage_u"] < wcfg["footfall_outage_rate"]

        # AR(1) demand state for tomorrow
        self.ar = wcfg["ar_phi"] * self.ar + wcfg["ar_sigma"] * rnd["ar"]

        rec = DayRecord(
            t=t, units_sold=sales, price_ratio=price_ratio, md_pct=md, promo_pct=promo,
            flyer=self.flyer[:, t].copy(), test_pct=test_pct, received=received, ordered_for_today=ordered,
            lot_life=life, waste_recorded=waste_recorded, waste_unrecorded=waste_unrecorded, damaged=damaged,
            donated=donated, counted=counted, adjust=adjust, book_open=book_open, book_close=book_close,
            phys_close=phys_close, true_demand=d_base, true_mu=mu, active=active,
            units_md=sold_md.astype(np.int32), md_labelled=np.where(md > 0, q_md, 0).astype(np.int32),
            true_extra=d_extra,
            footfall=np.round(footfall), footfall_missing=outage, source=source,
            pos_duplicate=rnd["dup_u"] < wcfg["pos_duplicate_rate"],
        )
        if record and self.dates[t] >= self.start:
            self.records.append(rec)
        self.t += 1
        return rec

    def _deplete(self, qty: np.ndarray) -> None:
        cum = np.cumsum(self.lots, axis=1)
        prev = cum - self.lots
        take = np.clip(qty[:, None] - prev, 0, self.lots)
        self.lots -= take.astype(np.int32)

    def _legacy_markdown(self) -> tuple[np.ndarray, np.ndarray]:
        """Flat sticker on units sold by today or tomorrow (j <= trigger; day-old units for 2-day items)."""
        trig = int(self.cfg["legacy_policy"]["trigger_days_to_expiry"])
        pct = self.cfg["legacy_policy"]["markdown_pct"] / 100
        win = np.minimum(trig, self.shelf - 2)
        j = np.arange(self.W)[None, :]
        has_old = (self.lots * (j <= win[:, None])).sum(1) > 0
        has_old &= win >= 0
        return np.where(has_old, pct, 0.0), np.where(has_old, win, -1)

    def _legacy_order(self, t: int, active: np.ndarray) -> np.ndarray:
        lcfg = self.cfg["legacy_policy"]
        si = self.store_idx
        nxt1 = self.next_delivery[self.delivery_class, si, t]
        nxt2 = self.next_delivery[self.delivery_class, si, np.minimum(nxt1, self.n_days)]
        f = self.sales_buf.mean(1)
        need = np.zeros(self.N)
        max_cover = 4
        for k in range(1, 4 + max_cover):
            d = t + k
            if d >= self.n_days:
                break
            in_cover = (d >= nxt1) & (d < nxt2)
            # store teams blend "same weekday over the last 3 weeks" with the 2-week average
            cols = [27 - (7 * w - k) for w in (1, 2, 3) if 0 <= 27 - (7 * w - k) <= 27]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)     # all-NaN rows right after a listing starts
                same_dow = np.nanmean(self.sales_cal[:, cols], axis=1) if cols else np.full(self.N, np.nan)
            generic = f * LEGACY_DOW[self.dow[d]]
            est = np.where(np.isnan(same_dow), generic, 0.6 * same_dow + 0.4 * generic)
            # store teams add a little after seeing empty shelves on that weekday
            soldout_dow = self.soldout_cal[:, cols].mean(1) if cols else 0.0
            est = est * (1 + 0.45 * soldout_dow + 0.15 * self.soldout_cal[:, -self.sales_buf.shape[1]:].mean(1))
            need += in_cover * est * self.store_open[si, d]
        sf = lcfg["safety_factor"]
        safety = np.where(self.shelf <= 2, sf["short"], np.where(self.shelf <= 6, sf["medium"], sf["long"]))
        need = need * (1 + safety)
        # units on hand still sellable on the delivery day (after tonight's shift, index j expires on day t+1+j)
        days_ahead = np.clip(nxt1 - t, 1, self.W)
        j = np.arange(self.W)[None, :]
        usable = (self.lots * (j >= (days_ahead - 1)[:, None])).sum(1)
        on_order = self.pending[np.minimum(nxt1, self.pending.shape[0] - 1), np.arange(self.N)]
        qty = np.maximum(0, need - usable - on_order)
        qty = np.ceil(qty / self.pack) * self.pack
        nxt_active = self.active_mat[np.arange(self.N), np.minimum(nxt1, self.n_days - 1)]
        # no ordering on days the store is closed
        return (qty * nxt_active * self.store_open[si, t]).astype(np.int32)

    # ------------------------------------------------------------------------------------------
    # state and calendar helpers
    # ------------------------------------------------------------------------------------------
    def index_of(self, d: date) -> int:
        return (d - self.t0).days

    @property
    def today(self) -> date:
        """The next day to be played (the morning the stores are about to open)."""
        return self.dates[self.t]

    def state(self) -> dict[str, np.ndarray]:
        out = {name: getattr(self, name) for name in STATE_ARRAYS}
        out["pending"] = self.pending[self.t:self.t + PENDING_AHEAD].copy()
        out["t"] = np.array(self.t)
        return out

    def load_state(self, state: dict[str, np.ndarray]) -> None:
        for name in STATE_ARRAYS:
            setattr(self, name, np.array(state[name]))
        self.t = int(state["t"])
        ahead = np.array(state["pending"])
        rows = min(len(ahead), self.pending.shape[0] - self.t)
        self.pending[self.t:self.t + rows] = ahead[:rows]

    def delivery_schedule(self) -> pd.Series:
        """Delivery schedule per SKU, as the ERP holds it."""
        cls = pd.Series(self.delivery_class, index=self.series["sku_id"]).groupby(level=0).first()
        return cls.map({0: "daily", 1: "mon_wed_fri", 2: "in_store_bake"})

    def closures(self) -> pd.DataFrame:
        """Store closures on public holidays (stores closed on Sundays carry their own flag in the store master)."""
        hol = dict(zip(self.holidays["date"], self.holidays["name"]))
        closed_md = set(self.cfg["calendar"]["closed_holidays"])
        closed_names = set(self.cfg["calendar"].get("closed_holiday_names", []))
        rows = []
        for i, d in enumerate(self.dates):
            if d.strftime("%m-%d") in closed_md or hol.get(d) in closed_names:
                reason = hol.get(d, "Closed")
                rows += [{"store_id": int(s), "closure_date": d, "reason": reason} for s in self.store_ids]
        return pd.DataFrame(rows, columns=["store_id", "closure_date", "reason"])


def run(world: World, until: date, policy: Callable | None = None, record: bool = True,
        progress: Callable[[int, date], None] | None = None) -> None:
    end_t = world.index_of(until)
    while world.t <= end_t:
        world.step(policy, record=record)
        if progress and world.t % 30 == 0:
            progress(world.t, world.dates[world.t - 1])

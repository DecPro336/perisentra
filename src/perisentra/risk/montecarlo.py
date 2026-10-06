"""Monte Carlo risk layer: simulate the next days of each store-SKU under candidate actions.

For each series we draw demand paths from the forecast distribution and play them against the stock
actually on the shelf, lot by lot:

    D_base[h] ~ Poisson(mu[h] * exp(eta) * G[h])     eta ~ N(-s^2/2, s^2) multi-day level shock,
                                                      G ~ Gamma(k, 1/k) day-level overdispersion
    D_extra[h] ~ Poisson(lambda * ((1 - d)^-e - 1))   extra demand attracted by a d% sticker,
                                                      e drawn from the elasticity posterior
    stickered units sell first (cheaper), extra demand only buys stickered units, sales FIFO by expiry,
    unsold units on their expiry day are waste.

The same base-demand draws are reused for every action of a series (common random numbers), so the
differences between actions are not drowned by simulation noise. Lots that cannot expire inside the
horizon are pooled into one "far" bucket that sells last, which keeps the state small.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class RiskBatch:
    lots: np.ndarray          # (n, W) units on hand by remaining life j (j=0 expires tonight), incl. today's delivery
    incoming: np.ndarray      # (n, H) units arriving on the morning of day h (h >= 1), fresh
    shelf: np.ndarray         # (n,) shelf life of incoming lots
    mu: np.ndarray            # (n, H) expected base demand (regular / promo price), 0 when closed
    price: np.ndarray         # (n, H) shelf price before markdown (promo price on promo days)
    cost: np.ndarray          # (n,)
    k: np.ndarray             # (n,) NB dispersion
    path_sigma: np.ndarray    # (n,)
    elasticity: np.ndarray    # (n, n_draws)
    next_delivery: np.ndarray  # (n,) offset (days) of the next delivery that tonight's order feeds (>= 1)
    cover_end: np.ndarray     # (n,) offset of the delivery after that (exclusive end of the cover period)
    promo: np.ndarray | None = None   # (n, H) promotion running: shelf price is the promo price, stickers give no extra lift


@dataclass
class ActionSet:
    discount: np.ndarray      # (n, A) effective sticker discount per series after price-point snapping (0 = none)
    window: np.ndarray        # (A,) stickers on lots with remaining life j <= window (-1 = none)


@dataclass
class RiskResult:
    waste_units: np.ndarray       # (n, A) expected waste of the stock on hand this morning
    waste_value: np.ndarray       # (n, A) expected, at cost
    p_waste: np.ndarray           # (n, A) P(any of this morning's stock wasted)
    revenue: np.ndarray           # (n, A)
    cogs: np.ndarray              # (n, A)
    sold: np.ndarray              # (n, A)
    sold_markdown: np.ndarray     # (n, A)
    discount_given: np.ndarray    # (n, A) currency
    lost_sales: np.ndarray        # (n, A)
    p_stockout: np.ndarray        # (n, A) before the next delivery
    leftover_today: np.ndarray    # (n, A) expected units expiring tonight unsold
    required_cover: np.ndarray    # (n, A, P) units needed at next delivery to cover demand until the one after
    waste_samples: np.ndarray     # (n, A, P) waste units per path (stock on hand this morning)
    revenue_window: np.ndarray    # (n, A) revenue while the markdown is active (days 0..window)
    cogs_window: np.ndarray       # (n, A)


def simulate(batch: RiskBatch, actions: ActionSet, n_paths: int = 600, seed: int = 0,
             stickers: np.ndarray | None = None) -> RiskResult:
    rng = np.random.default_rng(seed)
    n = batch.lots.shape[0]
    H = batch.mu.shape[1]
    A, P = actions.discount.shape[1], n_paths
    f32 = np.float32
    FAR = H                                                    # index of the pooled far bucket

    # state: near lots j = 0..H-1 plus a far bucket (cannot expire within the horizon)
    near = batch.lots[:, :H].astype(f32)
    far = batch.lots[:, H:].sum(1).astype(f32)
    base = np.concatenate([near, far[:, None]], axis=1)                                     # (n, H+1)
    jj = np.arange(H + 1)
    md_mask = ((jj[None, None, :] <= actions.window[None, :, None]) & (jj[None, None, :] < FAR)
               & (actions.discount[:, :, None] > 0))                                        # (n, A, H+1)
    lots = np.broadcast_to(base[:, None, None, :], (n, A, P, H + 1))
    stick = lots * md_mask[:, :, None, :]
    unst = lots - stick
    disc = np.broadcast_to(actions.discount[:, :, None].astype(f32), (n, A, P)).copy()
    if stickers is not None and stickers.any():   # stickers already on the shelf persist
        st = np.zeros((n, H + 1), dtype=bool)
        st[:, :H] = stickers[:, :H] > 0
        pre = st[:, None, None, :] & ~md_mask[:, :, None, :]
        stick = stick + unst * pre
        unst = unst * ~pre
        pre_disc = stickers.max(1)[:, None, None]
        disc = np.maximum(disc, np.broadcast_to(pre_disc, disc.shape) * (stick.sum(-1) > 0)).astype(f32)
    stick = np.ascontiguousarray(stick)
    unst = np.ascontiguousarray(unst)
    incoming_flag = np.zeros((n, A, P, H + 1), dtype=f32)     # 1 for cells that hold stock delivered after this morning

    sigma = batch.path_sigma[:, None]
    eta = rng.normal(-0.5 * sigma ** 2, sigma, (n, P)).astype(f32)
    e = batch.elasticity[np.arange(n)[:, None], rng.integers(0, batch.elasticity.shape[1], (n, P))].astype(f32)
    uplift = np.power(np.clip(1 - disc, 0.2, 1.0), -e[:, None, :]) - 1                       # (n, A, P)
    uplift_max = uplift.max(axis=1)                                                           # (n, P)
    promo = batch.promo if batch.promo is not None else np.zeros((n, H), dtype=bool)

    zeros = lambda: np.zeros((n, A, P), f32)
    waste_cur, revenue, sold, sold_md, disc_given, lost = zeros(), zeros(), zeros(), zeros(), zeros(), zeros()
    rev_win, cogs_win, leftover_today, stock_at_delivery = zeros(), zeros(), zeros(), zeros()
    stockout = np.zeros((n, A, P), dtype=bool)
    demand_cover = np.zeros((n, P), f32)
    cost3 = batch.cost[:, None, None].astype(f32)
    rows = np.arange(n)

    for h in range(H):
        if h > 0:
            inc = batch.incoming[:, h].astype(f32)
            at_delivery = batch.next_delivery == h
            if at_delivery.any():
                stock_at_delivery[at_delivery] = (stick + unst)[at_delivery].sum(-1)
            if inc.any():
                L = batch.shelf - 1
                idx = np.where(h + L <= H - 1, np.clip(L, 0, H - 1), FAR)
                unst[rows, :, :, idx] += inc[:, None, None]
                incoming_flag[rows, :, :, idx] = 1.0
        k = batch.k[:, None]
        g = rng.gamma(k, 1 / k, (n, P)).astype(f32)
        lam = batch.mu[:, h][:, None] * np.exp(eta) * g                                       # (n, P)
        d_base = rng.poisson(lam).astype(f32)                                                 # shared across actions
        # extra (deal-seeking) demand: one draw at the deepest discount, thinned for shallower ones, so actions
        # share their randomness (common random numbers) and deeper discounts never get less extra demand
        n_max = rng.poisson(lam * uplift_max)
        thin = np.where(uplift_max[:, None, :] > 0, uplift / np.maximum(uplift_max[:, None, :], 1e-12), 0.0)
        d_extra = rng.binomial(np.broadcast_to(n_max[:, None, :], thin.shape), np.clip(thin, 0, 1)).astype(f32)
        on_promo = promo[:, h][:, None, None]
        d_extra = np.where(on_promo, 0.0, d_extra)
        disc_h = np.where(on_promo, 0.0, disc)
        in_cover = (h >= batch.next_delivery) & (h < batch.cover_end)
        demand_cover += d_base * in_cover[:, None]

        q_md = stick.sum(-1)
        q_reg = unst.sum(-1)
        db = d_base[:, None, :]
        s_md_base = np.minimum(db, q_md)
        s_md = s_md_base + np.minimum(d_extra, q_md - s_md_base)
        s_reg = np.minimum(db - s_md_base, q_reg)
        short = db - s_md_base - s_reg
        lost += short
        stockout |= (short > 0) & (h < batch.next_delivery)[:, None, None]
        _fifo(stick, s_md)
        _fifo(unst, s_reg)
        price = batch.price[:, h][:, None, None]
        rev_h = s_md * price * (1 - disc_h) + s_reg * price
        revenue += rev_h
        in_win = (h <= actions.window)[None, :, None]
        rev_win += rev_h * in_win
        cogs_win += (s_md + s_reg) * cost3 * in_win
        disc_given += s_md * price * disc_h
        sold += s_md + s_reg
        sold_md += s_md

        expiring_cur = stick[..., 0] + unst[..., 0] * (1 - incoming_flag[..., 0])
        waste_cur += expiring_cur
        if h == 0:
            leftover_today = stick[..., 0] + unst[..., 0]
        # age by one day (in place); the far bucket does not move
        for arr in (stick, unst, incoming_flag):
            arr[..., : H - 1] = arr[..., 1:H]
            arr[..., H - 1] = 0

    required = demand_cover[:, None, :] - stock_at_delivery
    return RiskResult(
        waste_units=waste_cur.mean(-1), waste_value=waste_cur.mean(-1) * batch.cost[:, None],
        p_waste=(waste_cur > 0).mean(-1), revenue=revenue.mean(-1), cogs=sold.mean(-1) * batch.cost[:, None],
        sold=sold.mean(-1), sold_markdown=sold_md.mean(-1), discount_given=disc_given.mean(-1),
        lost_sales=lost.mean(-1), p_stockout=stockout.mean(-1), leftover_today=leftover_today.mean(-1),
        required_cover=required, waste_samples=waste_cur, revenue_window=rev_win.mean(-1),
        cogs_window=cogs_win.mean(-1),
    )


def _fifo(stock: np.ndarray, qty: np.ndarray) -> None:
    """Deplete `qty` units from the oldest lots first (in place). stock: (..., W), qty: (...)."""
    cum = np.cumsum(stock, axis=-1)
    take = np.clip(qty[..., None] - (cum - stock), 0, stock)
    stock -= take

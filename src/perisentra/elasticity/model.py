"""Hierarchical Bayesian price elasticity (PyMC), learned from the randomized price test.

Why not learn from history? Historical markdowns all happened in the last day or two of shelf life, on stock
that was left over *because* demand was weak. Regressing sales on price over that history credits or blames the
discount for demand that was already low, so the naive estimate is biased towards zero. The spring
randomized test assigned discounts independently of stock and demand, which identifies the effect.

Model (per store-SKU-day in the test):

    sales = min(D, available)                          stock-outs -> censored likelihood
    D ~ NegBinomial(mu, alpha_family)
    log mu = log(baseline forecast) + a_family
             - e_sku * log(1 - discount)                (discount = randomized whole-shelf price cut)
             + b_sib * sibling_promo_share               (cannibalisation by promoted siblings)
             + b_temp_family * temp_anomaly              (residual weather)
    e_sku    ~ Normal(e_family, sigma_sku)              partial pooling: SKUs borrow from their family
    e_family ~ Normal(mu_e, tau)                        families borrow from the chain

SKUs that were not in the test get draws from their family's predictive distribution.
"""

from __future__ import annotations

import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import polars as pl

from perisentra import warehouse as wh
from perisentra.config import PATHS, model_config
from perisentra.features.build import build_targets, demand_signal, history_stats
from perisentra.utils import get_logger, read_json, timed, write_json

log = get_logger(__name__)
MODEL_DIR = PATHS.models / "elasticity"
N_KEEP = 400


# ----------------------------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------------------------
def experiment_rows(trained_until: date | None = None) -> pd.DataFrame:
    sql = """
        select f.store_id, f.sku_id, f.date, f.family, f.units_sold, f.test_discount_pct,
               f.opening_stock + f.receipts as available, f.is_censored, f.sibling_promo_share,
               f.temp_max, f.in_flyer
        from marts.fct_store_sku_daily f
        where f.test_discount_pct is not null and f.is_open and f.is_in_season and not f.is_promo
    """
    df = wh.query(sql)
    if trained_until:
        df = df[pd.to_datetime(df["date"]).dt.date <= trained_until]
    return df


def attach_baseline(rows: pd.DataFrame) -> pd.DataFrame:
    """Baseline expected demand at regular price (horizon-1 forecast from the champion demand model)."""
    from perisentra.forecasting.model import DemandModel

    model = DemandModel.load()
    ctx = wh.feature_context(model.weather_mask, model.categories)
    start = pd.to_datetime(rows["date"]).min() - pd.Timedelta(days=100)
    panel = wh.panel(start=start.date(), end=pd.to_datetime(rows["date"]).max().date(),
                     stores=sorted(rows["store_id"].unique().tolist()))
    panel = demand_signal(panel)
    stats = history_stats(panel)
    tgt = pl.from_pandas(rows[["store_id", "sku_id", "date", "sibling_promo_share", "temp_max", "in_flyer"]]) \
        .with_columns(pl.col("date").cast(pl.Date), pl.col("store_id").cast(pl.Int32), pl.col("sku_id").cast(pl.Int32),
                      horizon=pl.lit(1, pl.Int32), promo_pct=pl.lit(0.0), precipitation=pl.lit(0.0))
    wx = panel.select(["store_id", "sku_id", "date", "precipitation"])
    tgt = tgt.drop("precipitation").join(wx, on=["store_id", "sku_id", "date"], how="left")
    X = build_targets(panel, tgt, ctx, stats)
    out = rows.copy()
    out["date"] = pd.to_datetime(out["date"])
    X["date"] = pd.to_datetime(X["date"])
    X["baseline"] = model.predict(X)
    out = out.merge(X[["store_id", "sku_id", "date", "baseline", "temp_anomaly"]].astype({"store_id": int}),
                    on=["store_id", "sku_id", "date"], how="left")
    return out.dropna(subset=["baseline"])


def naive_estimates() -> pd.DataFrame:
    """What an analyst gets from history: log-sales vs effective price on markdown vs normal days."""
    df = wh.query("""
        select family, store_id, sku_id, date, units_sold, price_ratio, is_markdown,
               avg(case when not is_markdown and not is_promo and not is_censored then units_sold end)
                 over (partition by store_id, sku_id order by date rows between 28 preceding and 1 preceding) as ref
        from marts.fct_store_sku_daily
        where is_open and is_in_season and not is_promo and test_discount_pct is null
    """)
    df = df[(df["ref"] > 0.5) & (df["price_ratio"] > 0.3)]
    rows = []
    for fam, g in df.groupby("family"):
        x = np.log(g["price_ratio"].clip(0.3, 1.0))
        y = np.log((g["units_sold"] + 0.5) / (g["ref"] + 0.5))
        slope = np.polyfit(x, y, 1)[0]
        rows.append({"family": fam, "naive_elasticity": float(-slope), "naive_rows": len(g),
                     "markdown_share": float(g["is_markdown"].mean())})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------------------------
# model
# ----------------------------------------------------------------------------------------------
def fit(rows: pd.DataFrame, seed: int = 11):
    import pymc as pm

    cfg = model_config()["elasticity"]
    fams = sorted(rows["family"].unique())
    skus = sorted(rows["sku_id"].unique())
    fam_idx = rows["family"].map({f: i for i, f in enumerate(fams)}).to_numpy()
    sku_idx = rows["sku_id"].map({s: i for i, s in enumerate(skus)}).to_numpy()
    sku_fam = (rows.drop_duplicates("sku_id").set_index("sku_id").loc[skus, "family"]
               .map({f: i for i, f in enumerate(fams)}).to_numpy())
    log_offset = np.log(np.clip(rows["baseline"].to_numpy(float), 0.05, None))
    log_price = np.log(1 - rows["test_discount_pct"].to_numpy(float))
    sib = rows["sibling_promo_share"].fillna(0).to_numpy(float)
    temp = rows["temp_anomaly"].fillna(0).to_numpy(float) / 5.0
    y = rows["units_sold"].to_numpy(int)
    cens = rows["is_censored"].to_numpy(bool)
    # stock-out days with nothing on the shelf carry no information about demand (P(D >= 0) = 1)
    cens_info = cens & (y > 0) & (y <= 200)
    unc = ~cens
    # stock-out rows are bucketed by sales level so the integer grid for P(D < s) stays small
    buckets = []
    for lo, hi in ((1, 12), (13, 40), (41, 200)):
        sel = cens_info & (y >= lo) & (y <= hi)
        if sel.any():
            grid = np.arange(int(y[sel].max()))
            buckets.append((sel, grid, grid[None, :] < y[sel][:, None]))

    coords = {"family": list(fams), "sku": [str(s) for s in skus]}
    with pm.Model(coords=coords):
        mu_e = pm.Normal("mu_e", 1.5, 0.6)
        tau = pm.HalfNormal("tau", 0.5)
        e_fam_z = pm.Normal("e_fam_z", 0, 1, dims="family")
        e_fam = pm.Deterministic("e_family", mu_e + tau * e_fam_z, dims="family")
        sigma_sku = pm.HalfNormal("sigma_sku", 0.4)
        e_sku_z = pm.Normal("e_sku_z", 0, 1, dims="sku")
        e_sku = pm.Deterministic("e_sku", e_fam[sku_fam] + sigma_sku * e_sku_z, dims="sku")
        a_fam = pm.Normal("a_family", 0, 0.3, dims="family")
        b_sib = pm.Normal("b_sibling_promo", 0, 0.5)
        b_temp = pm.Normal("b_temp", 0, 0.1, dims="family")
        alpha = pm.Gamma("alpha", 2.0, 0.1, dims="family")
        log_mu = log_offset + a_fam[fam_idx] - e_sku[sku_idx] * log_price + b_sib * sib + b_temp[fam_idx] * temp
        mu = pm.math.exp(log_mu)
        al = alpha[fam_idx]
        # uncensored days: exact NB likelihood
        pm.NegativeBinomial("sales", mu=mu[unc], alpha=al[unc], observed=y[unc])
        # stock-out days: log P(D >= s) = log(1 - sum_{d<s} pmf(d)), exact and cheap on small integer grids
        for b, (sel, grid, below) in enumerate(buckets):
            mu_c, al_c = mu[sel][:, None], al[sel][:, None]
            logpmf = pm.logp(pm.NegativeBinomial.dist(mu=mu_c, alpha=al_c), grid[None, :])
            logcdf = pm.math.logsumexp(pm.math.where(below, logpmf, -np.inf), axis=1)
            pm.Potential(f"stockout_days_{b}", pm.math.log1mexp(pm.math.minimum(logcdf, -1e-9)).sum())
        t0 = time.time()
        idata = pm.sample(draws=cfg["draws"], tune=cfg["tune"], chains=cfg["chains"], target_accept=cfg["target_accept"],
                          nuts_sampler="nutpie", random_seed=seed, progressbar=False)
        elapsed = time.time() - t0
    return idata, {"families": fams, "skus": skus, "sku_family": [fams[i] for i in sku_fam], "seconds": elapsed}


def diagnostics(idata) -> dict:
    import arviz as az

    post = idata["posterior"] if not hasattr(idata, "posterior") else idata.posterior
    if hasattr(post, "to_dataset"):
        post = post.to_dataset()
    out = {}
    try:
        rh = az.rhat(post[["e_family", "mu_e", "tau", "sigma_sku", "b_sibling_promo"]])
        out["rhat_max"] = float(max(float(rh[v].max()) for v in rh.data_vars))
        ess = az.ess(post[["e_family", "mu_e", "tau", "sigma_sku", "b_sibling_promo"]])
        out["ess_bulk_min"] = float(min(float(ess[v].min()) for v in ess.data_vars))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never break training
        log.warning("diagnostics failed: %s", exc)
    try:
        ss = idata["sample_stats"] if not hasattr(idata, "sample_stats") else idata.sample_stats
        out["divergences"] = int(ss["diverging"].sum())
    except Exception:  # noqa: BLE001
        out["divergences"] = -1
    return out


def summarise(idata, meta: dict, rows: pd.DataFrame, seed: int = 5) -> dict[str, pd.DataFrame]:
    post = idata["posterior"] if not hasattr(idata, "posterior") else idata.posterior
    stack = lambda v: post[v].stack(sample=("chain", "draw")).transpose("sample", ...).values
    e_fam, e_sku = stack("e_family"), stack("e_sku")
    sigma = stack("sigma_sku")
    rng = np.random.default_rng(seed)
    idx = rng.choice(e_fam.shape[0], size=min(N_KEEP, e_fam.shape[0]), replace=False)
    fams, skus = meta["families"], meta["skus"]

    def hdi(x: np.ndarray, prob: float = 0.94) -> tuple[float, float]:
        s = np.sort(x)
        n = len(s)
        w = int(np.floor(prob * n))
        i = int(np.argmin(s[w:] - s[: n - w]))
        return float(s[i]), float(s[i + w])

    fam_rows = []
    for j, f in enumerate(fams):
        lo, hi = hdi(e_fam[:, j])
        fam_rows.append({"family": f, "mean": float(e_fam[:, j].mean()), "sd": float(e_fam[:, j].std()),
                         "hdi_low": lo, "hdi_high": hi,
                         "test_rows": int((rows["family"] == f).sum()),
                         "test_skus": int(rows.loc[rows["family"] == f, "sku_id"].nunique())})
    family = pd.DataFrame(fam_rows)

    # draws for every SKU in the catalogue: posterior if tested, family predictive otherwise
    products = wh.products()[["sku_id", "family"]]
    draws = []
    sku_rows = []
    tested = {s: i for i, s in enumerate(skus)}
    for p in products.itertuples():
        if p.sku_id in tested:
            d = e_sku[idx, tested[p.sku_id]]
            source = "posterior"
        else:
            j = fams.index(p.family) if p.family in fams else None
            base = e_fam[idx, j] if j is not None else e_fam[idx].mean(1)
            d = base + sigma[idx] * rng.standard_normal(len(idx))
            source = "family_predictive"
        d = np.clip(d, 0.05, 5.0)
        lo, hi = hdi(d)
        sku_rows.append({"sku_id": p.sku_id, "family": p.family, "mean": float(d.mean()), "sd": float(d.std()),
                         "hdi_low": lo, "hdi_high": hi, "source": source})
        draws.append(pd.DataFrame({"sku_id": p.sku_id, "draw": np.arange(len(d)), "elasticity": d.astype(np.float32)}))
    sku = pd.DataFrame(sku_rows)
    coef = {"b_sibling_promo": float(stack("b_sibling_promo").mean()), "mu_e": float(stack("mu_e").mean()),
            "tau": float(stack("tau").mean()), "sigma_sku": float(sigma.mean())}
    return {"family": family, "sku": sku, "draws": pd.concat(draws, ignore_index=True), "coefficients": coef}


# ----------------------------------------------------------------------------------------------
# persistence
# ----------------------------------------------------------------------------------------------
class ElasticityModel:
    def __init__(self, version: str, draws: pd.DataFrame, family: pd.DataFrame, sku: pd.DataFrame, meta: dict):
        self.version, self.family, self.sku, self.meta = version, family, sku, meta
        self.draws = draws
        piv = draws.pivot(index="sku_id", columns="draw", values="elasticity")
        self._matrix = piv.to_numpy(np.float32)
        self._row = {int(s): i for i, s in enumerate(piv.index)}
        self._fallback = float(family["mean"].mean())

    def draws_for(self, sku_ids: np.ndarray) -> np.ndarray:
        """(n_sku, n_draws) elasticity draws."""
        rows = [self._row.get(int(s)) for s in sku_ids]
        out = np.empty((len(rows), self._matrix.shape[1]), np.float32)
        for i, r in enumerate(rows):
            out[i] = self._matrix[r] if r is not None else self._fallback
        return out

    @classmethod
    def load_trained_before(cls, cutoff: date) -> ElasticityModel:
        """Latest saved posterior fitted only on data before `cutoff` (no look-ahead in simulations)."""
        versions = [(str(read_json(d / "meta.json")["trained_until"])[:10], d.name) for d in MODEL_DIR.iterdir()
                    if (d / "meta.json").exists()]
        eligible = sorted(v for v in versions if date.fromisoformat(v[0]) < cutoff)
        if not eligible:
            raise FileNotFoundError(f"no elasticity model fitted before {cutoff}")
        return cls.load(eligible[-1][1])

    @classmethod
    def load(cls, version: str | None = None) -> ElasticityModel:
        version = version or (MODEL_DIR / "CHAMPION").read_text().strip()
        d = MODEL_DIR / version
        return cls(version, pd.read_parquet(d / "draws.parquet"), pd.read_parquet(d / "family.parquet"),
                   pd.read_parquet(d / "sku.parquet"), read_json(d / "meta.json"))


def fit_and_log(trained_until: date | None = None) -> ElasticityModel:
    import mlflow

    from perisentra.monitoring import tracking

    with timed(log, "Preparing price-test rows with baseline forecasts"):
        rows = attach_baseline(experiment_rows(trained_until))
    log.info("Price-test rows: %s, SKUs %d, stores %d, censored %.1f%%", f"{len(rows):,}", rows["sku_id"].nunique(),
             rows["store_id"].nunique(), 100 * rows["is_censored"].mean())
    with timed(log, "Sampling hierarchical elasticity model (nutpie NUTS)"):
        idata, meta = fit(rows)
    diag = diagnostics(idata)
    res = summarise(idata, meta, rows)
    naive = naive_estimates()
    family = res["family"].merge(naive, on="family", how="left")
    version = f"elasticity-{(trained_until or wh.bounds()[1]):%Y%m%d}-{datetime.now():%H%M%S}"
    out = MODEL_DIR / version
    out.mkdir(parents=True, exist_ok=True)
    res["draws"].to_parquet(out / "draws.parquet", index=False)
    family.to_parquet(out / "family.parquet", index=False)
    res["sku"].to_parquet(out / "sku.parquet", index=False)
    meta_out = {"version": version, "trained_until": trained_until or wh.bounds()[1], "rows": len(rows),
                "skus_tested": len(meta["skus"]), "sampling_seconds": meta["seconds"], "diagnostics": diag,
                "coefficients": res["coefficients"], "censored_share": float(rows["is_censored"].mean()),
                "stores": sorted(int(s) for s in rows["store_id"].unique())}
    write_json(out / "meta.json", meta_out)
    log.info("Elasticity: %s | diagnostics %s", family[["family", "mean", "naive_elasticity"]].round(2).to_dict("records"), diag)

    with tracking.run("perisentra-elasticity", version, tags={"model_type": "pymc-hierarchical-nb-censored"}) as r:
        mlflow.log_params({"draws": model_config()["elasticity"]["draws"], "chains": model_config()["elasticity"]["chains"],
                           "rows": len(rows), "skus_tested": len(meta["skus"]), "sampler": "nutpie"})
        metrics = {**{k: v for k, v in diag.items() if isinstance(v, (int, float))},
                   "mean_elasticity": float(family["mean"].mean()), "sampling_seconds": meta["seconds"]}
        mlflow.log_metrics(metrics)
        mlflow.log_artifacts(str(out), artifact_path="posterior")
        run_id = r.info.run_id
    tracking.promote(tracking.ELASTICITY_MODEL, run_id, "posterior",
                     description="Hierarchical Bayesian price elasticity from the randomized price test")
    (MODEL_DIR / "CHAMPION").write_text(version)
    write_json(out / "mlflow.json", {"run_id": run_id})
    return ElasticityModel.load(version)

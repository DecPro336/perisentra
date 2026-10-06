"""Global LightGBM demand model (Tweedie) with censored-demand EM and conformal intervals.

One model is trained across every store-SKU pair. Thin-history items borrow strength through family,
subfamily, store and family-store features, so a product listed three weeks ago still gets a sensible
forecast. The pipeline:

  1. weather ablation on a sample: keep weather features only for families where they lower WAPE
  2. EM on the pre-calibration window: fit on uncensored days, impute E[D | D >= sales] on stock-out
     days, refit (x em_iterations)
  3. calibrate: Mondrian split-conformal intervals + NB dispersion + path (multi-day) uncertainty on the
     last `calibration_weeks`
  4. refit on all data with imputed targets -> champion candidate, logged & registered in MLflow
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from perisentra.config import PATHS, model_config
from perisentra.features.build import FEATURES, WEATHER, FeatureContext
from perisentra.forecasting import conformal
from perisentra.forecasting.censoring import conditional_mean_at_least, dispersion_from_residuals
from perisentra.utils import get_logger, read_json, safe_div, timed, write_json

log = get_logger(__name__)
MODEL_DIR = PATHS.models / "demand"


def wape(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sum(np.abs(y - p)) / max(np.sum(y), 1e-9))


def bias(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sum(p - y) / max(np.sum(y), 1e-9))


@dataclass
class DemandModel:
    booster: lgb.Booster
    features: list[str]
    categories: dict[str, list]
    weather_mask: list[str]
    conformal_table: pd.DataFrame
    dispersion: pd.DataFrame            # family, k, path_sigma
    power: float
    version: str
    trained_until: date
    metrics: dict = field(default_factory=dict)
    importance: pd.DataFrame | None = None
    ablation: pd.DataFrame | None = None

    # ------------------------------------------------------------------------------------------
    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.clip(self.booster.predict(df[self.features], num_threads=8), 0, None)

    def intervals(self, family: np.ndarray, pred: np.ndarray, level: float) -> tuple[np.ndarray, np.ndarray]:
        return conformal.apply(self.conformal_table, family, pred, level, self.power)

    def family_params(self, family: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        d = self.dispersion.set_index("family")
        k = d["k"].reindex(family).fillna(d["k"].median()).to_numpy()
        s = d["path_sigma"].reindex(family).fillna(d["path_sigma"].median()).to_numpy()
        return k, s

    # ------------------------------------------------------------------------------------------
    def save(self, root: Path = MODEL_DIR) -> Path:
        out = root / self.version
        out.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(out / "booster.txt"))
        self.conformal_table.to_parquet(out / "conformal.parquet", index=False)
        self.dispersion.to_parquet(out / "dispersion.parquet", index=False)
        if self.importance is not None:
            self.importance.to_parquet(out / "importance.parquet", index=False)
        if self.ablation is not None:
            self.ablation.to_parquet(out / "ablation.parquet", index=False)
        write_json(out / "meta.json", {"features": self.features, "categories": self.categories,
                                       "weather_mask": self.weather_mask, "power": self.power,
                                       "version": self.version, "trained_until": self.trained_until,
                                       "metrics": self.metrics})
        return out

    @classmethod
    def load(cls, version: str | None = None, root: Path = MODEL_DIR) -> DemandModel:
        version = version or (root / "CHAMPION").read_text().strip()
        d = root / version
        meta = read_json(d / "meta.json")
        opt = lambda name: pd.read_parquet(d / name) if (d / name).exists() else None
        return cls(booster=lgb.Booster(model_file=str(d / "booster.txt")), features=meta["features"],
                   categories=meta["categories"], weather_mask=meta["weather_mask"],
                   conformal_table=pd.read_parquet(d / "conformal.parquet"),
                   dispersion=pd.read_parquet(d / "dispersion.parquet"), power=meta["power"],
                   version=meta["version"], trained_until=date.fromisoformat(meta["trained_until"]),
                   metrics=meta.get("metrics", {}), importance=opt("importance.parquet"),
                   ablation=opt("ablation.parquet"))

    @classmethod
    def load_trained_before(cls, cutoff: date, root: Path = MODEL_DIR) -> DemandModel:
        """Latest saved model trained only on data before `cutoff` (no look-ahead in simulations)."""
        versions = [(read_json(d / "meta.json")["trained_until"], d.name) for d in root.iterdir()
                    if (d / "meta.json").exists()]
        eligible = sorted(v for v in versions if date.fromisoformat(v[0]) < cutoff)
        if not eligible:
            raise FileNotFoundError(f"no demand model trained before {cutoff}")
        return cls.load(eligible[-1][1], root)

    def promote_local(self, root: Path = MODEL_DIR) -> None:
        (root / "CHAMPION").write_text(self.version)


# ----------------------------------------------------------------------------------------------
# training
# ----------------------------------------------------------------------------------------------
def _params(cfg: dict) -> dict:
    p = dict(cfg["lightgbm"])
    p["tweedie_variance_power"] = cfg["tweedie_variance_power"]
    for k in ("num_boost_round", "early_stopping_rounds"):
        p.pop(k, None)
    p["num_threads"] = 8
    p["seed"] = 7
    return p


def fit_booster(train: pd.DataFrame, y: np.ndarray, valid: pd.DataFrame | None, y_valid: np.ndarray | None,
                cfg: dict, features: list[str], rounds: int | None = None) -> lgb.Booster:
    params = _params(cfg)
    dtrain = lgb.Dataset(train[features], label=y, free_raw_data=True)
    callbacks = [lgb.log_evaluation(0)]
    valid_sets = []
    if valid is not None:
        valid_sets = [lgb.Dataset(valid[features], label=y_valid, reference=dtrain)]
        callbacks.append(lgb.early_stopping(cfg["lightgbm"]["early_stopping_rounds"], verbose=False))
    return lgb.train(params, dtrain, num_boost_round=rounds or cfg["lightgbm"]["num_boost_round"],
                     valid_sets=valid_sets, callbacks=callbacks)


def _split_valid(df: pd.DataFrame, days: int = 28) -> tuple[np.ndarray, np.ndarray]:
    cut = df["date"].max() - timedelta(days=days)
    return (df["date"] <= cut).to_numpy(), (df["date"] > cut).to_numpy()


def em_fit(df: pd.DataFrame, cfg: dict, features: list[str], k_family: dict[str, float] | None = None,
           iterations: int | None = None) -> tuple[lgb.Booster, np.ndarray, dict[str, float]]:
    """Fit with censored-demand EM. Returns (booster, imputed target, dispersion per family)."""
    iterations = cfg["em_iterations"] if iterations is None else iterations
    y_obs = df["units_sold"].to_numpy(float)
    cens = df["is_censored"].to_numpy(bool)
    tr, va = _split_valid(df)
    unc = ~cens
    booster = fit_booster(df[tr & unc], y_obs[tr & unc], df[va & unc], y_obs[va & unc], cfg, features)
    if k_family is None:
        pred = np.clip(booster.predict(df.loc[va & unc, features]), 0, None)
        fam = df.loc[va & unc, "family"].astype(str).to_numpy()
        k_family = {f: dispersion_from_residuals(y_obs[va & unc][fam == f], pred[fam == f]) for f in np.unique(fam)}
    y = y_obs.copy()
    for it in range(iterations):
        mu = np.clip(booster.predict(df.loc[cens, features]), 1e-3, None)
        k = df.loc[cens, "family"].astype(str).map(k_family).fillna(10.0).to_numpy()
        y[cens] = conditional_mean_at_least(y_obs[cens], mu, k)
        booster = fit_booster(df[tr], y[tr], df[va], y[va], cfg, features)
        log.info("    EM iteration %d: censored rows %d, mean uplift on censored days %+.1f%%",
                 it + 1, int(cens.sum()), 100 * (y[cens].sum() / max(y_obs[cens].sum(), 1) - 1))
    return booster, y, k_family


def weather_ablation(df: pd.DataFrame, cfg: dict, seed: int = 3) -> pd.DataFrame:
    """Train with and without weather features on a sample; report holdout WAPE per family."""
    acfg = cfg["weather_ablation"]
    start = df["date"].max() - timedelta(days=int(acfg["sample_months"] * 30.5))
    sample = df[df["date"] >= start]
    series = sample[["store_id", "sku_id"]].drop_duplicates().sample(frac=0.45, random_state=seed)
    sample = sample.merge(series, on=["store_id", "sku_id"])
    sample = sample[~sample["is_censored"]]
    cut = sample["date"].max() - timedelta(days=42)
    tr, te = sample[sample["date"] <= cut], sample[sample["date"] > cut]
    no_weather = [f for f in FEATURES if f not in WEATHER]
    rows = []
    preds = {}
    for name, feats in (("with_weather", FEATURES), ("without_weather", no_weather)):
        b = fit_booster(tr, tr["units_sold"].to_numpy(float), None, None, cfg, feats, rounds=350)
        preds[name] = np.clip(b.predict(te[feats]), 0, None)
    y = te["units_sold"].to_numpy(float)
    for fam, idx in te.groupby(te["family"].astype(str)).indices.items():
        w, wo = wape(y[idx], preds["with_weather"][idx]), wape(y[idx], preds["without_weather"][idx])
        rows.append({"family": fam, "wape_with": w, "wape_without": wo, "gain_pct": 100 * (wo - w) / wo,
                     "rows": len(idx)})
    out = pd.DataFrame(rows)
    out["keep_weather"] = out["gain_pct"] >= acfg["min_wape_gain_pct"]
    return out.sort_values("gain_pct", ascending=False).reset_index(drop=True)


def _path_sigma(df: pd.DataFrame, pred: np.ndarray, k_family: dict[str, float]) -> dict[str, float]:
    """Multi-day forecast-level uncertainty: variance of weekly log ratios beyond count noise."""
    tmp = df[["store_id", "sku_id", "family", "date"]].copy()
    tmp["y"], tmp["p"] = df["units_sold"].to_numpy(float), pred
    tmp["week"] = pd.to_datetime(tmp["date"]).dt.to_period("W")
    g = tmp.groupby(["family", "store_id", "sku_id", "week"], observed=True).agg(y=("y", "sum"), p=("p", "sum"),
                                                                                  n=("y", "size"))
    g = g[(g["n"] >= 5) & (g["p"] >= 3)].reset_index()
    out = {}
    for fam, gg in g.groupby(g["family"].astype(str)):
        lr = np.log((gg["y"] + 0.5) / (gg["p"] + 0.5))
        noise = np.mean(1 / gg["p"] + 1 / (gg["n"] * k_family.get(fam, 20)))
        out[fam] = float(np.sqrt(max(np.var(lr) - noise, 0.003)))
    return out


def train(df: pd.DataFrame, ctx: FeatureContext, trained_until: date, version: str | None = None,
          run_ablation: bool = True) -> tuple[DemandModel, dict]:
    cfg = model_config()["forecast"]
    version = version or f"demand-{trained_until:%Y%m%d}-{datetime.now():%H%M%S}"
    report: dict = {"version": version, "trained_until": trained_until, "rows": len(df)}
    df = df.copy()
    for c, cats in ctx.categories.items():
        df[c] = pd.Categorical(df[c].astype(object) if c != "store_id" else df[c], categories=cats)
    family_str = df["family"].astype(str)

    ablation = None
    weather_mask: list[str] = []
    if run_ablation:
        with timed(log, "Weather ablation"):
            ablation = weather_ablation(df, cfg)
        weather_mask = ablation.loc[~ablation["keep_weather"], "family"].tolist()
        log.info("  weather kept for: %s", ablation.loc[ablation["keep_weather"], "family"].tolist())
        if weather_mask:
            df.loc[family_str.isin(weather_mask).to_numpy(), WEATHER] = np.nan

    cal_start = trained_until - timedelta(weeks=cfg["calibration_weeks"]) + timedelta(days=1)
    pre = df[df["date"] < pd.Timestamp(cal_start)].reset_index(drop=True)
    cal = df[df["date"] >= pd.Timestamp(cal_start)].reset_index(drop=True)

    with timed(log, f"EM fit on {len(pre):,} rows before {cal_start}"):
        b_cal, _, k_family = em_fit(pre, cfg, FEATURES)

    # ---- calibration ------------------------------------------------------------------------
    p_cal = np.clip(b_cal.predict(cal[FEATURES]), 0, None)
    unc = ~cal["is_censored"].to_numpy(bool)
    y_cal = cal["units_sold"].to_numpy(float)
    fam_cal = cal["family"].astype(str).to_numpy()
    table = conformal.fit(fam_cal[unc], p_cal[unc], y_cal[unc], cfg["interval_levels"], cfg["tweedie_variance_power"])
    # Uncensored days are a selected sample (demand happened to fit on the shelf), which biases error and
    # dispersion estimates. Days with plenty of stock relative to the forecast are close to unconstrained.
    avail = cal["available"].to_numpy(float) if "available" in cal else np.full(len(cal), np.inf)
    free = unc & (avail >= 2 * p_cal + 3)
    k_cal = {}
    for f in np.unique(fam_cal):
        m = free & (fam_cal == f)
        m = m if m.sum() >= 500 else unc & (fam_cal == f)
        k_cal[f] = dispersion_from_residuals(y_cal[m], p_cal[m])
    sig = _path_sigma(cal[free], p_cal[free], k_cal)
    dispersion = pd.DataFrame({"family": list(k_cal), "k": list(k_cal.values()),
                               "path_sigma": [sig.get(f, 0.1) for f in k_cal]})
    metrics = {"cal_wape": wape(y_cal[unc], p_cal[unc]), "cal_bias": bias(y_cal[free], p_cal[free]),
               "cal_bias_uncensored_days": bias(y_cal[unc], p_cal[unc]), "cal_unconstrained_share": float(free.mean())}
    for level in cfg["interval_levels"]:
        lo, hi = conformal.apply(table, fam_cal[unc], p_cal[unc], level, cfg["tweedie_variance_power"])
        metrics[f"cal_coverage_{int(level * 100)}"] = float(np.mean((y_cal[unc] >= lo) & (y_cal[unc] <= hi)))
    by_family = []
    for f in np.unique(fam_cal):
        m = unc & (fam_cal == f)
        mf = free & (fam_cal == f)
        by_family.append({"family": f, "wape": wape(y_cal[m], p_cal[m]), "bias": bias(y_cal[mf], p_cal[mf]),
                          "units": float(y_cal[m].sum())})
    report["calibration_by_family"] = by_family
    log.info("  calibration: WAPE %.3f bias %+.3f coverage80 %.3f coverage95 %.3f", metrics["cal_wape"],
             metrics["cal_bias"], metrics["cal_coverage_80"], metrics["cal_coverage_95"])

    # ---- final refit on everything (censored targets imputed with the calibrated model) --------
    with timed(log, f"Final refit on {len(df):,} rows"):
        cens = df["is_censored"].to_numpy(bool)
        y = df["units_sold"].to_numpy(float)
        mu = np.clip(b_cal.predict(df.loc[cens, FEATURES]), 1e-3, None)
        k = family_str[cens].map(k_family).fillna(10).to_numpy()
        y[cens] = conditional_mean_at_least(y[cens], mu, k)
        rounds = max(150, int((b_cal.best_iteration or cfg["lightgbm"]["num_boost_round"]) * 1.1))
        booster = fit_booster(df, y, None, None, cfg, FEATURES, rounds=rounds)
    metrics["rounds"] = rounds
    metrics["censored_share"] = float(cens.mean())
    metrics["censored_uplift_pct"] = float(100 * (y[cens].sum() / max(df.loc[cens, "units_sold"].sum(), 1) - 1))

    imp = pd.DataFrame({"feature": booster.feature_name(),
                        "gain": booster.feature_importance("gain")}).sort_values("gain", ascending=False)
    imp["share"] = imp["gain"] / imp["gain"].sum()
    model = DemandModel(booster=booster, features=list(FEATURES), categories=ctx.categories, weather_mask=weather_mask,
                        conformal_table=table, dispersion=dispersion, power=cfg["tweedie_variance_power"],
                        version=version, trained_until=trained_until, metrics=metrics, importance=imp,
                        ablation=ablation)
    report["metrics"] = metrics
    report["k_family"] = k_family
    return model, report


def log_to_mlflow(model: DemandModel, report: dict, promote: bool = True) -> str | None:
    import mlflow

    from perisentra.monitoring import tracking

    cfg = model_config()["forecast"]
    out = model.save()
    with tracking.run("perisentra-demand", model.version,
                      tags={"model_type": "lightgbm-tweedie", "trained_until": str(model.trained_until)}) as r:
        mlflow.log_params({**{f"lgb_{k}": v for k, v in cfg["lightgbm"].items()},
                           "tweedie_variance_power": cfg["tweedie_variance_power"],
                           "em_iterations": cfg["em_iterations"], "calibration_weeks": cfg["calibration_weeks"],
                           "n_features": len(model.features), "weather_mask": ",".join(model.weather_mask) or "none",
                           "train_rows": report["rows"]})
        mlflow.log_metrics({k: float(v) for k, v in model.metrics.items()})
        mlflow.log_artifacts(str(out), artifact_path="model")
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "training_report.json"
            write_json(tmp, report)
            mlflow.log_artifact(str(tmp), artifact_path="report")
        run_id = r.info.run_id
    version = tracking.promote(tracking.DEMAND_MODEL, run_id, "model",
                               description="Global LightGBM Tweedie demand model (censored EM + conformal)") \
        if promote else None
    if promote:
        model.promote_local()
    write_json(out / "mlflow.json", {"run_id": run_id, "registry_version": version})
    return run_id


def forecast_frame(model: DemandModel, X: pd.DataFrame) -> pd.DataFrame:
    """Point forecast + 80/95% intervals for a scoring frame (baseline: no markdown)."""
    pred = model.predict(X)
    open_ = X["is_open"].fillna(True).astype(bool).to_numpy() if "is_open" in X else np.ones(len(X), bool)
    season = X["is_in_season"].fillna(True).astype(bool).to_numpy() if "is_in_season" in X else np.ones(len(X), bool)
    pred = np.where(open_ & season, pred, 0.0)
    fam = X["family"].astype(str).to_numpy()
    out = X[["store_id", "sku_id", "date", "horizon", "family"]].copy()
    out["store_id"] = out["store_id"].astype(int)
    out["family"] = fam
    out["p50"] = pred
    for level, (lo_n, hi_n) in ((0.80, ("p10", "p90")), (0.95, ("p025", "p975"))):
        lo, hi = model.intervals(fam, pred, level)
        out[lo_n], out[hi_n] = np.where(pred > 0, lo, 0.0), np.where(pred > 0, hi, 0.0)
    out["history_days"] = X["history_days"].to_numpy()
    out["sig_ma28"] = X["sig_ma28"].to_numpy()
    out["demand_norm"] = X["fullprice_ma28"].to_numpy() if "fullprice_ma28" in X else X["sig_ma28"].to_numpy()
    out["rel_width"] = safe_div(out["p90"] - out["p10"], np.maximum(out["p50"], 1.0))
    return out

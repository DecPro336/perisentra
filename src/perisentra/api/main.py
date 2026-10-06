"""Perisentra decision API (FastAPI).

Serves the morning recommendations with reason codes and confidence tiers, a what-if simulator, store
decision logging, model / validation / monitoring views and the business-rules editor. Interactive docs
at /docs.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from perisentra.api import store
from perisentra.config import PATHS, client_config, dbt_target_dir, model_config, warehouse_target
from perisentra.evaluation.pilot import pilot_design
from perisentra.utils import get_logger

log = get_logger(__name__)

app = FastAPI(
    title="Perisentra Decision API",
    version="1.0.0",
    description="Demand forecasting, stock-at-risk detection and constraint-aware commercial actions for fresh retail.",
)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("PERISENTRA_CORS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


STOCKOUT_ALERT = float(model_config()["risk"]["stockout_alert"])
_serving_lock = threading.Lock()      # recompute rewrites the serving tables: one at a time
NOT_READY = "No scoring run yet: the pipeline is still preparing this morning's recommendations (perisentra score)."


def _require_recs() -> pd.DataFrame:
    recs = store.recommendations()
    if recs.empty:
        raise HTTPException(503, NOT_READY)
    return recs


def _wh_query(sql: str) -> pd.DataFrame:
    from perisentra import warehouse as wh

    return wh.query(sql)


# ----------------------------------------------------------------------------------------------
# meta & overview
# ----------------------------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    meta = store.run_meta()
    return {"status": "ok" if meta else "no_run", "as_of_date": meta.get("as_of_date"), "run_id": meta.get("run_id")}


@app.get("/api/meta")
def meta() -> dict:
    m = store.run_meta()
    recs = store.recommendations()
    stores = (recs.groupby(["store_id", "store_name", "city", "region", "store_format"], as_index=False).size()
              .rename(columns={"size": "skus"})) if not recs.empty else pd.DataFrame()
    design = pilot_design()
    groups = {**{s: "pilot" for s in design.get("treatment", [])}, **{s: "control" for s in design.get("control", [])}}
    if not stores.empty:
        stores["pilot_group"] = stores["store_id"].map(groups).fillna("rollout_pending")
    # a store re-run from the rules page uses a newer rules version than the morning run: list every version in use
    in_use = recs["rules_version"].dropna().astype(int).unique().tolist() if "rules_version" in recs else []
    m["rules_versions"] = sorted(in_use) or [m.get("rules_version")]
    client = client_config()["client"]
    return {**m, "chain_name": client["name"], "currency": client["currency"],
            "warehouse": warehouse_target(),
            "stores": store.records(stores),
            "families": sorted(recs["family"].unique().tolist()) if not recs.empty else []}


def _with_net(recs: pd.DataFrame) -> pd.DataFrame:
    if "expected_net_margin" in recs:
        return recs
    return recs.assign(expected_net_margin=recs["expected_margin"] - recs["expected_waste_value"],
                       baseline_net_margin=recs["baseline_margin"] - recs["baseline_waste_value"],
                       legacy_net_margin=recs["legacy_margin"] - recs["legacy_waste_value"])


@app.get("/api/overview")
def overview() -> dict:
    recs = _with_net(_require_recs())
    md = recs["action"] == "MARKDOWN"
    kpi = {
        "stock_at_risk": float(recs["baseline_waste_value"].sum()),
        "expected_waste": float(recs["expected_waste_value"].sum()),
        "waste_avoided": float(recs["waste_avoided_value"].sum()),
        "markdowns": int(md.sum()),
        "legacy_markdowns": int((recs["legacy_action"] == "MARKDOWN").sum()),
        "legacy_waste": float(recs["legacy_waste_value"].sum()),
        "waste_vs_legacy": float(recs["legacy_waste_value"].sum() - recs["expected_waste_value"].sum()),
        "margin_vs_legacy": float(recs["expected_margin"].sum() - recs["legacy_margin"].sum()),
        "net_margin_vs_legacy": float(recs["expected_net_margin"].sum() - recs["legacy_net_margin"].sum()),
        "net_margin": float(recs["expected_net_margin"].sum()),
        "discount_cost": float(recs["expected_discount_cost"].sum()),
        "legacy_discount_cost": float(recs["legacy_discount_cost"].sum()),
        "order_changes": int((recs["order_action"] != "KEEP").sum()),
        "order_reduce": int((recs["order_action"] == "REDUCE").sum()),
        "order_increase": int((recs["order_action"] == "INCREASE").sum()),
        "donations": int((recs["donate_units"] > 0).sum()),
        "stockout_alerts": int((recs["p_stockout"] >= STOCKOUT_ALERT).sum()),
        "items": len(recs),
        "margin_delta": float((recs["expected_margin"] - recs["baseline_margin"]).sum()),
        "high_confidence_share": float((recs["confidence_tier"] == "HIGH").mean()),
    }
    recs = recs.assign(vs_legacy=recs["legacy_waste_value"] - recs["expected_waste_value"])
    by_store = recs.groupby(["store_id", "store_name", "store_format", "city"], as_index=False).agg(
        at_risk=("baseline_waste_value", "sum"), waste_avoided=("waste_avoided_value", "sum"),
        vs_legacy=("vs_legacy", "sum"),
        markdowns=("action", lambda s: int((s == "MARKDOWN").sum())),
        order_changes=("order_action", lambda s: int((s != "KEEP").sum())),
        stockout_alerts=("p_stockout", lambda s: int((s >= STOCKOUT_ALERT).sum())), items=("sku_id", "size"))
    by_family = recs.groupby("family", as_index=False).agg(
        at_risk=("baseline_waste_value", "sum"), waste_avoided=("waste_avoided_value", "sum"),
        expected_waste=("expected_waste_value", "sum"), legacy_waste=("legacy_waste_value", "sum"),
        markdowns=("action", lambda s: int((s == "MARKDOWN").sum())), items=("sku_id", "size"))
    top = recs.sort_values("baseline_waste_value", ascending=False).head(12)[
        ["store_id", "sku_id", "store_name", "product_name", "family", "action", "discount_pct", "baseline_waste_value",
         "expected_waste_value", "waste_avoided_value", "confidence_tier", "units_expiring_3d", "p_waste_baseline",
         "order_action", "order_reference", "order_recommended", "donate_units"]]
    weekly = _wh_query("""
        select week_start, sum(waste_value) as waste_value, sum(markdown_events) as markdown_events,
               sum(discount_given) as discount_given, sum(gross_margin) / nullif(sum(net_sales), 0) as margin_rate,
               sum(stockout_rate * sku_days) / sum(sku_days) as stockout_rate, sum(net_sales) as net_sales
        from marts.mart_store_family_week group by 1 order by 1""")
    weekly = weekly[weekly["week_start"] < weekly["week_start"].max()].tail(26)
    tiers = recs["confidence_tier"].value_counts().to_dict()
    design = pilot_design()
    groups = {**{s_: "pilot" for s_ in design.get("treatment", [])}, **{s_: "control" for s_ in design.get("control", [])}}
    by_store["pilot_group"] = by_store["store_id"].map(groups).fillna("rollout_pending")
    return {"kpi": kpi, "by_store": store.records(by_store.sort_values("at_risk", ascending=False)),
            "by_family": store.records(by_family.sort_values("at_risk", ascending=False)),
            "top_at_risk": store.records(top), "weekly": store.records(weekly), "confidence_tiers": tiers,
            "meta": store.run_meta(), "pilot": {"start": design.get("start"), "end": design.get("end")}}


# ----------------------------------------------------------------------------------------------
# recommendations
# ----------------------------------------------------------------------------------------------
LIST_COLS = ["store_id", "sku_id", "store_name", "product_name", "family", "subfamily", "action", "discount_pct",
             "markdown_window_days", "units_to_label", "regular_price", "new_price", "stock_on_hand",
             "units_expiring_3d", "forecast_today", "forecast_week", "baseline_waste_value", "expected_waste_value",
             "waste_avoided_value", "p_waste_baseline", "p_stockout", "order_action", "order_reference",
             "order_recommended", "donate_units", "confidence_tier", "confidence_score", "reason_codes", "explored",
             "legacy_action", "legacy_waste_value"]


@app.get("/api/recommendations")
def list_recommendations(store_id: int | None = None, family: str | None = None, action: str | None = None,
                         tier: str | None = None, q: str | None = None, only_actions: bool = False,
                         sort: str = "baseline_waste_value", limit: int = Query(500, le=5000)) -> dict:
    recs = store.recommendations()
    if recs.empty:
        return {"items": [], "total": 0}
    df = recs
    if store_id:
        df = df[df["store_id"] == store_id]
    if family:
        df = df[df["family"] == family]
    if action == "ORDER":
        df = df[df["order_action"] != "KEEP"]
    elif action == "DONATE":
        df = df[df["donate_units"] > 0]
    elif action == "STOCKOUT":
        df = df[df["p_stockout"] >= STOCKOUT_ALERT]
    elif action:
        df = df[df["action"] == action]
    if tier:
        df = df[df["confidence_tier"] == tier]
    if q:
        df = df[df["product_name"].str.contains(q, case=False, na=False)]
    if only_actions:
        df = df[(df["action"] != "NO_ACTION") | (df["order_action"] != "KEEP") | (df["donate_units"] > 0)]
    if sort in df.columns:
        df = df.sort_values(sort, ascending=False)
    out = df[LIST_COLS].head(limit).copy()
    out["reason_codes"] = out["reason_codes"].map(json.loads)
    return {"items": store.records(out), "total": len(df)}


@app.get("/api/recommendations/{store_id}/{sku_id}")
def recommendation_detail(store_id: int, sku_id: int) -> dict:
    recs = _require_recs()
    row = recs[(recs["store_id"] == store_id) & (recs["sku_id"] == sku_id)]
    if row.empty:
        raise HTTPException(404, "Unknown store / SKU")
    rec = store.records(_with_net(row))[0]
    rec["reason_codes"] = json.loads(rec["reason_codes"])
    rec["confidence_factors"] = json.loads(rec["confidence_factors"])
    cand = store.candidates()
    c = cand[(cand["store_id"] == store_id) & (cand["sku_id"] == sku_id)]
    payload = json.loads(c.iloc[0]["payload"]) if len(c) else {}
    fc = store.forecasts()
    fc = fc[(fc["store_id"] == store_id) & (fc["sku_id"] == sku_id)].sort_values("date")
    hist = store.history()
    hist = hist[(hist["store_id"] == store_id) & (hist["sku_id"] == sku_id)].sort_values("date")
    lots = store.lots()
    lots = lots[(lots["store_id"] == store_id) & (lots["sku_id"] == sku_id)].sort_values("expiry_date")
    el = _elasticity_tables()
    sku_el = el["sku"][el["sku"]["sku_id"] == sku_id] if el else pd.DataFrame()
    fam_el = el["family"][el["family"]["family"] == rec["family"]] if el else pd.DataFrame()
    from perisentra.monitoring import feedback

    as_of = str(store.run_meta().get("as_of_date") or "")
    decisions = feedback.decisions(as_of=as_of, store_id=store_id, limit=500)
    decisions = decisions[decisions["sku_id"] == sku_id].head(10)
    return {"recommendation": rec, "candidates": payload.get("candidates", []),
            "waste_hist_baseline": payload.get("waste_hist_baseline", []),
            "waste_hist_chosen": payload.get("waste_hist_chosen", []),
            "forecast": store.records(fc[["date", "horizon", "p50", "p10", "p90", "p025", "p975"]]),
            "history": store.records(hist), "lots": store.records(lots),
            "elasticity": {"sku": store.records(sku_el), "family": store.records(fam_el)},
            "decisions": store.records(decisions)}


class Decision(BaseModel):
    store_id: int
    sku_id: int
    decision: Literal["ACCEPTED", "OVERRIDDEN", "REJECTED"]
    applied_action: str | None = None
    applied_discount_pct: float | None = None
    note: str = ""
    user: str = "store-manager"


@app.post("/api/decisions")
def post_decision(d: Decision) -> dict:
    from perisentra.monitoring import feedback

    m = store.run_meta()
    recs = _require_recs()
    row = recs[(recs["store_id"] == d.store_id) & (recs["sku_id"] == d.sku_id)]
    if row.empty:
        raise HTTPException(404, "Unknown store / SKU")
    r = row.iloc[0]
    action = d.applied_action or (r["action"] if d.decision == "ACCEPTED" else "NO_ACTION")
    disc = d.applied_discount_pct if d.applied_discount_pct is not None else (
        float(r["discount_pct"]) if d.decision == "ACCEPTED" else 0.0)
    feedback.log_decision(m.get("run_id", ""), str(m.get("as_of_date")), d.store_id, d.sku_id, d.decision, action,
                          disc, d.note, d.user)
    return {"status": "logged", "decision": d.decision, "applied_action": action, "applied_discount_pct": disc}


@app.get("/api/decisions")
def get_decisions(store_id: int | None = None, limit: int = 200) -> dict:
    from perisentra.monitoring import feedback

    m = store.run_meta()
    df = feedback.decisions(as_of=str(m.get("as_of_date")) if m else None, store_id=store_id, limit=limit)
    summary = df["decision"].value_counts().to_dict() if not df.empty else {}
    return {"items": store.records(df), "summary": summary}


class WhatIf(BaseModel):
    store_id: int
    sku_id: int
    discount_pct: float = Field(ge=0, le=80)
    window_days: int = Field(1, ge=1, le=5)


@app.post("/api/simulate")
def simulate_whatif(w: WhatIf) -> dict:
    from perisentra.decision.rules import current_rules
    from perisentra.decision.whatif import evaluate

    _require_recs()
    limit = current_rules().markdown.max_days_before_expiry
    if w.window_days > limit:
        raise HTTPException(422, f"window_days must be at most {limit} (business rule)")
    try:
        return evaluate(w.store_id, w.sku_id, w.discount_pct, w.window_days)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


class Recompute(BaseModel):
    store_id: int


@app.post("/api/recommendations/recompute")
def recompute(r: Recompute) -> dict:
    from perisentra.pipeline.score import recompute_store

    _require_recs()
    try:
        with _serving_lock:
            recs = recompute_store(r.store_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"store_id": r.store_id, "items": len(recs), "markdowns": int((recs["action"] == "MARKDOWN").sum()),
            "order_changes": int((recs["order_action"] != "KEEP").sum()),
            "waste_avoided": float(recs["waste_avoided_value"].sum())}


# ----------------------------------------------------------------------------------------------
# risk, elasticity, validation
# ----------------------------------------------------------------------------------------------
@app.get("/api/risk/heatmap")
def risk_heatmap(metric: Literal["at_risk", "stockout_alerts", "markdowns"] = "at_risk") -> dict:
    recs = _require_recs()
    g = recs.groupby(["store_id", "store_name", "family"], as_index=False).agg(
        at_risk=("baseline_waste_value", "sum"), stockout_alerts=("p_stockout", lambda s: int((s >= STOCKOUT_ALERT).sum())),
        markdowns=("action", lambda s: int((s == "MARKDOWN").sum())), items=("sku_id", "size"))
    return {"metric": metric, "cells": store.records(g),
            "stores": store.records(recs[["store_id", "store_name"]].drop_duplicates().sort_values("store_id")),
            "families": sorted(recs["family"].unique().tolist())}


def _elasticity_tables() -> dict | None:
    from perisentra.elasticity.model import MODEL_DIR

    ptr = MODEL_DIR / "CHAMPION"
    if not ptr.exists():
        return None
    d = MODEL_DIR / ptr.read_text().strip()
    return {"family": store.parquet("family.parquet", d), "sku": store.parquet("sku.parquet", d),
            "meta": store.json_file(d / "meta.json")}


@app.get("/api/elasticity")
def elasticity() -> dict:
    el = _elasticity_tables()
    if not el:
        raise HTTPException(503, "No elasticity model")
    products = _wh_query("select sku_id, product_name from marts.dim_product")
    sku = el["sku"].merge(products, on="sku_id", how="left")
    return {"family": store.records(el["family"]), "sku": store.records(sku), "meta": el["meta"]}


@app.get("/api/validation/backtest")
def backtest() -> dict:
    data = store.json_file(PATHS.reports / "backtest.json")
    if not data:
        raise HTTPException(503, "Backtest not run yet")
    return data


@app.get("/api/validation/pilot")
def pilot() -> dict:
    from perisentra.monitoring import feedback

    data = store.json_file(PATHS.reports / "pilot_evaluation.json")
    if not data:
        raise HTTPException(503, "Pilot not evaluated yet")
    stores = _wh_query("select store_id, store_name, store_format from marts.dim_store")
    design = data["design"]
    compliance = feedback.task_list_compliance(design["treatment"], design["start"], design["end"])
    return {**data, "stores": store.records(stores), "compliance": compliance}


# ----------------------------------------------------------------------------------------------
# models & monitoring
# ----------------------------------------------------------------------------------------------
@app.get("/api/models")
def models() -> dict:
    from perisentra.forecasting.model import MODEL_DIR as DEMAND_DIR
    from perisentra.monitoring import tracking

    out: dict = {"demand": None, "elasticity": None}
    ptr = DEMAND_DIR / "CHAMPION"
    if ptr.exists():
        d = DEMAND_DIR / ptr.read_text().strip()
        meta = store.json_file(d / "meta.json") or {}
        conf = store.parquet("conformal.parquet", d)
        out["demand"] = {
            **{k: meta.get(k) for k in ("version", "trained_until", "metrics", "weather_mask", "power")},
            "n_features": len(meta.get("features", [])),
            "importance": store.records(store.parquet("importance.parquet", d).head(25)),
            "ablation": store.records(store.parquet("ablation.parquet", d)),
            "dispersion": store.records(store.parquet("dispersion.parquet", d)),
            "conformal": store.records(conf[conf["bucket"] == "*"]) if not conf.empty else [],
            "training_report": store.json_file(PATHS.reports / "training" / f"{meta.get('version')}.json"),
        }
    el = _elasticity_tables()
    if el:
        out["elasticity"] = el["meta"]
    try:
        out["runs"] = {"demand": tracking.list_runs("perisentra-demand"),
                       "elasticity": tracking.list_runs("perisentra-elasticity")}
        out["registry"] = {"demand": tracking.registry_versions(tracking.DEMAND_MODEL),
                           "elasticity": tracking.registry_versions(tracking.ELASTICITY_MODEL)}
    except Exception as exc:  # noqa: BLE001 - MLflow is optional for the dashboard
        log.warning("MLflow unavailable: %s", exc)
        out["runs"], out["registry"] = {}, {}
    out["mlflow_ui"] = os.environ.get("PERISENTRA_MLFLOW_UI", "http://localhost:5000")
    return out


@app.get("/api/monitoring")
def monitoring() -> dict:
    drift = store.json_file(PATHS.reports / "drift" / "summary.json")
    perf = store.json_file(PATHS.reports / "monitoring_performance.json")
    from perisentra.monitoring import feedback

    log_df = feedback.recommendation_log()
    by_source = log_df.groupby("source").size().to_dict() if not log_df.empty else {}
    explored = int(log_df["explored"].astype(str).isin(["1", "True", "true"]).sum()) if not log_df.empty else 0
    dec = feedback.decisions(limit=100000)
    return {"drift": drift, "performance": perf, "log": {"recommendations": len(log_df), "by_source": by_source,
                                                        "explored": explored, "decisions": len(dec),
                                                        "decision_mix": dec["decision"].value_counts().to_dict()
                                                        if not dec.empty else {}}}


@app.get("/api/monitoring/drift-report", response_class=HTMLResponse)
def drift_report() -> FileResponse:
    path = PATHS.reports / "drift" / "drift_report.html"
    if not path.exists():
        raise HTTPException(404, "No drift report yet")
    return FileResponse(path, media_type="text/html")


# ----------------------------------------------------------------------------------------------
# data & pipeline
# ----------------------------------------------------------------------------------------------
@app.get("/api/data-quality")
def data_quality() -> dict:
    coverage = _wh_query("select * from marts.mart_source_coverage")
    ingestion = _wh_query("""select source_table as "table", files, row_count as "rows", loaded_at
                             from raw._ingestion_log
                             qualify row_number() over (partition by source_table order by loaded_at desc) = 1
                             order by source_table""")
    target = dbt_target_dir()
    dbt = {}
    rr = store.json_file(target / "run_results.json")
    if rr:
        res = rr.get("results", [])
        status = pd.Series([r["status"] for r in res]).value_counts().to_dict()
        tests = [r for r in res if r["unique_id"].startswith("test.")]
        models = [r for r in res if r["unique_id"].startswith("model.")]
        dbt = {"generated_at": rr.get("metadata", {}).get("generated_at"), "elapsed": rr.get("elapsed_time"),
               "status": status, "tests": len(tests), "models": len(models),
               "tests_failed": [r["unique_id"].split(".")[2] for r in tests if r["status"] not in ("pass", "success")],
               "slowest_models": sorted([{"model": r["unique_id"].split(".")[-1], "seconds": r["execution_time"]}
                                         for r in models], key=lambda x: -x["seconds"])[:6]}
    lineage = _lineage(target)
    from perisentra.monitoring import feedback

    runs = feedback.pipeline_runs(30)
    return {"coverage": store.records(coverage), "ingestion": store.records(ingestion), "dbt": dbt,
            "lineage": lineage, "pipeline_runs": store.records(runs)}


def _lineage(target) -> dict:
    man = store.json_file(target / "manifest.json")
    if not man:
        return {"nodes": [], "edges": []}
    nodes, edges = [], []
    for uid, n in {**man["nodes"], **man["sources"]}.items():
        if n["resource_type"] not in ("model", "source"):
            continue
        layer = "source" if n["resource_type"] == "source" else n["fqn"][1] if len(n["fqn"]) > 2 else "model"
        nodes.append({"id": uid, "name": n["name"], "layer": layer})
        for dep in n.get("depends_on", {}).get("nodes", []):
            if dep.startswith(("model.", "source.")):
                edges.append({"source": dep, "target": uid})
    return {"nodes": nodes, "edges": edges}


# ----------------------------------------------------------------------------------------------
# business rules
# ----------------------------------------------------------------------------------------------
@app.get("/api/rules")
def get_rules() -> dict:
    from perisentra.decision.rules import current_rules, rules_history

    return {"rules": current_rules().model_dump(), "history": rules_history()}


class RulesUpdate(BaseModel):
    rules: dict
    comment: str = ""
    user: str = "dashboard"


@app.post("/api/rules/validate")
def validate_rules(u: RulesUpdate) -> dict:
    from pydantic import ValidationError

    from perisentra.decision.rules import Rules, current_rules, merge_rules, unknown_families

    try:
        candidate = Rules.model_validate(merge_rules(current_rules().model_dump(), u.rules))
        bad = unknown_families(candidate, set(_wh_query("select distinct family from marts.dim_product")["family"]))
        return {"valid": not bad, "errors": [{"loc": b, "msg": "unknown product family"} for b in bad]}
    except ValidationError as exc:
        return {"valid": False, "errors": [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]}


@app.put("/api/rules")
def put_rules(u: RulesUpdate) -> dict:
    from pydantic import ValidationError

    from perisentra.decision.rules import Rules, current_rules, merge_rules, save_rules, unknown_families

    try:
        candidate = Rules.model_validate(merge_rules(current_rules().model_dump(), u.rules))
    except ValidationError as exc:
        raise HTTPException(422, [{"loc": ".".join(map(str, e["loc"])), "msg": e["msg"]} for e in exc.errors()]) from exc
    families = set(_wh_query("select distinct family from marts.dim_product")["family"])
    bad = unknown_families(candidate, families)
    if bad:
        raise HTTPException(422, [{"loc": b, "msg": "unknown product family"} for b in bad])
    r = save_rules(candidate, u.user, u.comment)
    return {"version": r.version, "rules": r.model_dump()}

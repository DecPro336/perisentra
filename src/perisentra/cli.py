"""Command line entry point: `perisentra <command>`.

    check-inbound   has the retailer's delivery for a business day arrived (its manifest)?
    daily           what the Airflow DAG runs each morning: weather -> ingest -> dbt build -> score -> monitor
    check-warehouse which warehouse is in use (Snowflake, or the offline DuckDB copy) and whether it answers
    serve           start the API (http://localhost:8000/docs)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import date, datetime
from functools import wraps
from pathlib import Path

import typer

from perisentra.config import PATHS
from perisentra.utils import get_logger

app = typer.Typer(add_completion=False, help="Perisentra predictive decision engine")
log = get_logger("perisentra")
RUN_ID = os.environ.get("PERISENTRA_RUN_ID", f"cli-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}")


def tracked(step: str) -> Callable:
    """Record the step in the pipeline-run log (Data & pipeline page). A step may return a one-line detail."""
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from perisentra.monitoring import feedback

            PATHS.ensure()
            started = datetime.now()
            try:
                out = fn(*args, **kwargs)
            except Exception as exc:
                feedback.pipeline_run(RUN_ID, step, "failed", started, str(exc)[:500])
                raise
            feedback.pipeline_run(RUN_ID, step, "success", started, out if isinstance(out, str) else "")
            return out
        return wrapper
    return deco


@app.command("check-inbound")
def check_inbound(business_date: str = typer.Option("", "--date", help="Business day (default: yesterday)")) -> None:
    """Exit 0 when the retailer's delivery for the business day is complete, 1 otherwise (Airflow waits on it)."""
    from datetime import timedelta

    day = date.fromisoformat(business_date) if business_date else date.today() - timedelta(days=1)
    manifest = PATHS.inbound / "_manifests" / f"{day.isoformat()}.json"
    if not manifest.exists():
        typer.echo(f"Delivery for {day} not complete yet (no {manifest.name})")
        raise typer.Exit(1)
    typer.echo(f"Delivery for {day} complete")


@app.command("fetch-external")
@tracked("fetch_external")
def fetch_external() -> None:
    """Weather at every store (Open-Meteo archive, recent days and 16-day forecast) and public holidays."""
    from perisentra.external.refresh import refresh_external

    refresh_external()


@app.command()
@tracked("ingest")
def ingest() -> None:
    """Land source extracts (and the decision log) into the warehouse raw schema."""
    from perisentra.ingestion.load_raw import ingest_all

    ingest_all()


def _dbt(*args: str) -> None:
    """Run a dbt command on the warehouse selected in .env (PERISENTRA_DBT_TARGET)."""
    from perisentra.config import dbt_target_dir, warehouse_target

    env = {**os.environ, "PERISENTRA_WAREHOUSE": str(PATHS.warehouse), "PERISENTRA_DBT_TARGET": warehouse_target(),
           "DBT_TARGET_PATH": str(dbt_target_dir())}
    dbt = Path(sys.executable).with_name("dbt")          # the dbt installed in this environment
    cmd = [str(dbt) if dbt.exists() else "dbt", *args, "--project-dir", str(PATHS.dbt_project),
           "--profiles-dir", str(PATHS.dbt_project)]
    res = subprocess.run(cmd, env=env, cwd=PATHS.dbt_project, check=False)
    if res.returncode != 0:
        raise typer.Exit(res.returncode)


@app.command()
@tracked("dbt_build")
def transform(select: str = typer.Option("", help="dbt selector")) -> None:
    """Run `dbt build` (models + tests) on the warehouse."""
    _dbt("build", *(["--select", select] if select else []))


@app.command("dbt-docs")
def dbt_docs(port: int = 8081) -> None:
    """Generate the dbt docs (lineage, columns, tests) from the warehouse and serve them on localhost."""
    _dbt("docs", "generate")
    _dbt("docs", "serve", "--port", str(port), "--host", "127.0.0.1", "--no-browser")


@app.command()
@tracked("train")
def train(until: str = typer.Option("", help="Train on data up to this date (default: all)"),
          ablation: bool = typer.Option(True, help="Run the weather ablation"),
          elasticity: bool = typer.Option(True, help="Refit the elasticity model")) -> None:
    """Train the demand model (and the elasticity model), log to MLflow, promote to champion."""
    from perisentra.pipeline.train import train_demand, train_elasticity

    d = date.fromisoformat(until) if until else None
    train_demand(d, ablation)
    if elasticity:
        train_elasticity(d)


@app.command()
@tracked("backtest")
def backtest() -> None:
    """Rolling-origin backtest of the demand model vs the current process and baselines."""
    from perisentra.evaluation.backtest import run

    rep = run()
    log.info("Backtest WAPE (observed, uncensored): %s", {k: round(v["wape"], 3)
                                                         for k, v in rep["observed_uncensored"].items()})


@app.command("design-pilot")
@tracked("design_pilot")
def design_pilot() -> None:
    """Choose the pilot's treatment stores and their matched controls from pre-pilot data (client.yaml: pilot)."""
    from perisentra.evaluation.pilot import design_pilot as run

    design = run()
    log.info("Pilot: treatment %s, controls %s", design["treatment"], design["control"])


@app.command("evaluate-pilot")
@tracked("evaluate_pilot")
def evaluate_pilot() -> None:
    """Difference-in-differences readout of the pilot from warehouse data."""
    from perisentra.evaluation.pilot import evaluate

    rep = evaluate()
    log.info("Pilot DiD: %s", {k: round(v["did_pct"], 1) for k, v in rep["did"].items()})


@app.command()
@tracked("score")
def score(paths: int = typer.Option(0, help="Monte Carlo paths per action (0 = config)")) -> str:
    """Score this morning: forecasts, risk, recommendations -> serving tables and the stores' task list."""
    from perisentra.pipeline.score import score as run_score

    meta = run_score(n_paths=paths or None)
    return json.dumps({"decision_run": meta["run_id"], "series": meta["n_series"], "tasks": meta["task_items"]})


@app.command()
@tracked("monitor")
def monitor() -> None:
    """Drift report (Evidently) and live forecast accuracy from the decision log."""
    from perisentra.monitoring.drift import drift_report, live_performance

    s = drift_report()
    live_performance()
    log.info("Drift share %.2f, drifted: %s", s["drift_share"] or 0, s["drifted_columns"])


@app.command()
def daily() -> None:
    """Daily run (what Airflow schedules): weather -> ingest -> dbt build -> score + task list -> monitor."""
    fetch_external()
    ingest()
    transform(select="")
    score(paths=0)
    monitor()


@app.command("check-warehouse")
def check_warehouse() -> None:
    """Show which warehouse is in use (PERISENTRA_DBT_TARGET), check the connection and count the tables."""
    from perisentra import warehouse as wh
    from perisentra.config import warehouse_target

    target = warehouse_target()
    typer.echo(f"Warehouse target: {target}")
    if target == "snowflake":
        from perisentra import snowflake_io

        who = snowflake_io.query("select current_account() as account, current_user() as user_name, "
                                 "current_role() as role, current_warehouse() as warehouse, "
                                 "current_database() as database, current_version() as version")
        for k, v in who.iloc[0].items():
            typer.echo(f"  {k:10s} {v}")
        tables = wh.query("select lower(table_schema) as table_schema, count(*) as tables "
                          "from information_schema.tables where table_schema in "
                          "('RAW', 'STAGING', 'INTERMEDIATE', 'MARTS') group by 1 order by 1")
    else:
        typer.echo(f"  offline DuckDB copy: {PATHS.warehouse}")
        tables = wh.query("select table_schema, count(*) as tables from information_schema.tables "
                          "where table_schema in ('raw', 'staging', 'intermediate', 'marts') group by 1 order by 1")
    for r in tables.itertuples():
        typer.echo(f"  {r.table_schema:13s} {r.tables} tables")
    if tables.empty:
        typer.echo("  (empty: run `perisentra ingest` and `perisentra transform`)")


@app.command()
def serve(host: str = typer.Option("127.0.0.1", help="Use 0.0.0.0 inside containers"), port: int = 8000,
          reload: bool = False) -> None:
    """Start the decision API."""
    import uvicorn

    uvicorn.run("perisentra.api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()

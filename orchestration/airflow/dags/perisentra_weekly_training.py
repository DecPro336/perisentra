"""Weekly retraining: refresh the warehouse (including the decision/outcome log), retrain the demand model
(censored EM, conformal calibration, weather ablation), refit the price-elasticity posterior, re-run the
rolling-origin backtest and the pilot readout. New models are registered in MLflow and promoted to the
`champion` alias. Exploration decisions are logged with their propensities so price refits can use them.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

CLI = os.environ.get("PERISENTRA_CLI", "/opt/perisentra/venv/bin/perisentra")


def step(task_id: str, command: str, **kwargs) -> BashOperator:
    """One pipeline step = one CLI command. Tasks inherit the worker's environment (project paths, warehouse
    target, Snowflake settings) and tag their pipeline-run records with the Airflow run id."""
    return BashOperator(task_id=task_id, bash_command=f"{CLI} {command}",
                        env={"PERISENTRA_RUN_ID": "airflow-{{ run_id }}"}, append_env=True, **kwargs)


@dag(
    dag_id="perisentra_weekly_training",
    schedule="0 2 * * 1",
    start_date=pendulum.datetime(2026, 9, 1, tz="America/New_York"),
    catchup=False,
    max_active_runs=1,          # every run rewrites the same warehouse: never two at once
    default_args={"owner": "perisentra", "retries": 1, "retry_delay": timedelta(minutes=10)},
    tags=["perisentra", "training"],
    doc_md=__doc__,
)
def perisentra_weekly_training():
    ingest = step("ingest_sources", "ingest")
    dbt = step("dbt_build_and_test", "transform")
    train = step("train_and_register", "train", execution_timeout=timedelta(hours=1))
    backtest = step("rolling_origin_backtest", "backtest", execution_timeout=timedelta(hours=1))
    pilot = step("pilot_readout", "evaluate-pilot")
    ingest >> dbt >> train >> [backtest, pilot]


perisentra_weekly_training()

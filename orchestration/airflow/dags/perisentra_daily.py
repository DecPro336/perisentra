"""Daily decision run: wait for the retailer's delivery, land it, rebuild the warehouse (with tests), score,
publish the stores' task list, monitor.

Runs at 05:00 US Eastern so store teams see their task list when they open. The run waits for yesterday's
delivery manifest, and a failing dbt test stops it before anything is published.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.sensors.bash import BashSensor
from airflow.sdk import dag

CLI = os.environ.get("PERISENTRA_CLI", "/opt/perisentra/venv/bin/perisentra")


def step(task_id: str, command: str, **kwargs) -> BashOperator:
    """One pipeline step = one CLI command. Tasks inherit the worker's environment (project paths, warehouse
    target, Snowflake settings) and tag their pipeline-run records with the Airflow run id."""
    return BashOperator(task_id=task_id, bash_command=f"{CLI} {command}",
                        env={"PERISENTRA_RUN_ID": "airflow-{{ run_id }}"}, append_env=True, **kwargs)


default_args = {"owner": "perisentra", "retries": 2, "retry_delay": timedelta(minutes=5)}


@dag(
    dag_id="perisentra_daily",
    schedule="0 5 * * *",
    start_date=pendulum.datetime(2026, 9, 1, tz="America/New_York"),
    catchup=False,
    max_active_runs=1,          # every run rewrites the same warehouse: never two at once
    default_args=default_args,
    tags=["perisentra", "decisions"],
    doc_md=__doc__,
)
def perisentra_daily():
    delivery = BashSensor(task_id="wait_for_delivery", bash_command=f"{CLI} check-inbound",   # inherits the env
                          mode="reschedule", poke_interval=300, timeout=6 * 3600)
    fetch = step("fetch_weather_and_holidays", "fetch-external")
    ingest = step("ingest_sources", "ingest")
    dbt = step("dbt_build_and_test", "transform")
    score = step("score_recommendations", "score", execution_timeout=timedelta(minutes=30))
    monitor = step("monitor_drift_and_accuracy", "monitor")
    delivery >> fetch >> ingest >> dbt >> score >> monitor


perisentra_daily()

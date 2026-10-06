"""Fernbrook Market source systems (simulated): deliver yesterday's extracts to the exchange folder.

Not part of Perisentra. With a real retailer, the ERP, POS and WMS exports land in the exchange drop on their
own schedule; here the simulator plays out each business day (applying the task list Perisentra published that
morning in the stores that receive it) and delivers its extracts and the day's manifest at 01:00.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag

CLI = os.environ.get("FERNBROOK_CLI", "/opt/perisentra/venv/bin/fernbrook")


@dag(
    dag_id="fernbrook_source_systems",
    schedule="0 1 * * *",
    start_date=pendulum.datetime(2026, 9, 1, tz="America/New_York"),
    catchup=False,
    max_active_runs=1,          # the world advances one business day after another
    default_args={"owner": "fernbrook", "retries": 2, "retry_delay": timedelta(minutes=10)},
    tags=["simulated-retailer"],
    doc_md=__doc__,
)
def fernbrook_source_systems():
    BashOperator(task_id="deliver_business_day", bash_command=f"{CLI} advance", append_env=True,
                 execution_timeout=timedelta(hours=2))


fernbrook_source_systems()

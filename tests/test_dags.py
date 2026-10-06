"""DAG integrity (runs where Airflow is installed, e.g. inside the Airflow image)."""

from pathlib import Path

import pytest

pytest.importorskip("airflow")

DAGS = Path(__file__).resolve().parents[1] / "orchestration" / "airflow" / "dags"


def test_dags_import_without_errors():
    from airflow.models import DagBag

    bag = DagBag(str(DAGS), include_examples=False)
    assert bag.import_errors == {}
    assert set(bag.dag_ids) == {"perisentra_daily", "perisentra_weekly_training", "fernbrook_source_systems"}
    daily = bag.get_dag("perisentra_daily")
    order = [t.task_id for t in daily.topological_sort()]
    assert order[0] == "wait_for_delivery"                      # nothing runs before last night's delivery is complete
    assert order.index("dbt_build_and_test") < order.index("score_recommendations")
    for dag_id in bag.dag_ids:
        assert bag.get_dag(dag_id).max_active_runs == 1         # runs never overlap on the same warehouse / world

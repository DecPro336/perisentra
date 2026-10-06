#!/usr/bin/env bash
# Airflow on this machine (no Docker), running the DAGs in orchestration/airflow/dags against this checkout.
#
#   orchestration/airflow/local.sh install      one-time: Airflow in its own virtualenv, pinned with the official constraints
#   orchestration/airflow/local.sh start        scheduler, DAG processor, triggerer and UI on http://localhost:8080
#   orchestration/airflow/local.sh test         DAG integrity tests (tests/test_dags.py) inside Airflow's environment
#   orchestration/airflow/local.sh <command>    any airflow command with the same settings, e.g. `dags list`
#
# Airflow keeps its own virtualenv because its pinned dependencies conflict with the project's (pandas, sqlalchemy).
# Tasks call the project's CLI (.venv/bin/perisentra), which reads warehouse and Snowflake settings from .env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$ROOT/orchestration/airflow"
VENV="$HERE/.venv"
AIRFLOW_VERSION="3.1.0"
PYTHON_VERSION="3.12"

export AIRFLOW_HOME="$HERE/home"
export AIRFLOW__CORE__DAGS_FOLDER="$HERE/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"
export AIRFLOW__CORE__DEFAULT_TIMEZONE="America/New_York"
export AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION="True"
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS="True"     # no login screen: keep it on this machine
export AIRFLOW__API__HOST="${AIRFLOW_HOST:-127.0.0.1}"           # AIRFLOW_HOST=0.0.0.0: reachable from other machines
export AIRFLOW__API__PORT="8080"
export AIRFLOW__CORE__EXECUTION_API_SERVER_URL="http://127.0.0.1:8080/execution/"
export PERISENTRA_ROOT="$ROOT"
export PERISENTRA_CLI="$ROOT/.venv/bin/perisentra"
export FERNBROOK_CLI="$ROOT/.venv/bin/fernbrook"     # the simulated retailer's nightly delivery
export PATH="$VENV/bin:$PATH"                  # standalone launches its components as `airflow ...`

case "${1:-start}" in
  install)
    uv venv "$VENV" --python "$PYTHON_VERSION" --allow-existing
    uv pip install --python "$VENV/bin/python" "apache-airflow==$AIRFLOW_VERSION" pytest \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-$AIRFLOW_VERSION/constraints-$PYTHON_VERSION.txt"
    ;;
  test)
    [ -x "$VENV/bin/airflow" ] || { echo "Airflow not installed: run 'make airflow-install' first." >&2; exit 1; }
    "$VENV/bin/airflow" db migrate >/dev/null 2>&1
    exec "$VENV/bin/python" -m pytest -p no:cacheprovider "$ROOT/tests/test_dags.py"
    ;;
  start)
    [ -x "$PERISENTRA_CLI" ] && [ -x "$FERNBROOK_CLI" ] || { echo "Project CLIs not found: run 'make install' first." >&2; exit 1; }
    [ -x "$VENV/bin/airflow" ] || { echo "Airflow not installed: run 'make airflow-install' first." >&2; exit 1; }
    exec "$VENV/bin/airflow" standalone
    ;;
  *)
    exec "$VENV/bin/airflow" "$@"
    ;;
esac

.DEFAULT_GOAL := help
# Network interface the services listen on: this machine only by default. HOST=0.0.0.0 makes the API, dashboard,
# MLflow and Airflow reachable from other machines at this machine's IP (no login: for a call, then stop them).
HOST ?= 127.0.0.1
.PHONY: help install bootstrap deliver daily api dashboard dashboard-prod test lint dbt-docs mlflow airflow-install airflow \
        airflow-docker clean-cache clean

help:               ## List the commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*## /\t/' | expand -t 20

install:            ## Python (Perisentra with the Snowflake connector, and the simulator) + dashboard dependencies
	uv sync --all-packages --extra snowflake
	cd dashboard && npm ci

bootstrap:          ## A fresh environment: the retailer's history, models, the pilot through the daily loop (hours)
	scripts/bootstrap.sh

deliver:            ## The retailer's systems deliver every business day up to yesterday (Airflow: 01:00)
	uv run fernbrook advance

daily:              ## Perisentra's morning run on the latest delivery (Airflow: 05:00)
	uv run perisentra daily

api:                ## Decision API on :8000 (docs at /docs)
	uv run perisentra serve --host $(HOST) --port 8000

dashboard:          ## Dashboard on :3000 in development mode (proxies /api to :8000)
	cd dashboard && npm run dev

dashboard-prod:     ## Production build of the dashboard on :3000 (use this for presentations)
	cd dashboard && npm run build && npx next start -p 3000 -H $(HOST)

test:               ## Product, simulator and Airflow DAG tests (offline: never touch Snowflake)
	uv run pytest
	@if [ -x orchestration/airflow/.venv/bin/airflow ]; then orchestration/airflow/local.sh test; \
	else echo "DAG tests skipped (make airflow-install)"; fi

lint:               ## ruff for Python, TypeScript + ESLint for the dashboard
	uv run ruff check src tests orchestration simulator
	cd dashboard && npm run typecheck && npm run lint

dbt-docs:           ## dbt lineage & docs on :8081, from the warehouse in .env
	uv run perisentra dbt-docs --port 8081

mlflow:             ## MLflow UI on :5000 (silences a deprecation notice inside MLflow's own server)
	PYTHONWARNINGS="ignore::UserWarning:mlflow.server.fastapi_app" uv run mlflow ui --backend-store-uri sqlite:///data/mlflow/mlflow.db \
	  --host $(HOST) --port 5000 $(if $(filter-out 127.0.0.1 localhost,$(HOST)),--allowed-hosts '*' --cors-allowed-origins '*')

airflow-install:    ## One-time: Airflow in its own virtualenv (no Docker)
	orchestration/airflow/local.sh install

airflow:            ## Airflow on this machine: UI on :8080
	AIRFLOW_HOST=$(HOST) orchestration/airflow/local.sh start

airflow-docker:     ## Airflow in Docker on :8080
	docker compose --profile orchestration up --build airflow

clean-cache:        ## Remove caches and build output (keeps data, models and environments)
	find . -path ./.venv -prune -o -path ./dashboard/node_modules -prune -o -path ./orchestration/airflow/.venv -prune \
	  -o -type d -name __pycache__ -print | xargs -r rm -rf
	rm -rf .pytest_cache .ruff_cache warehouse/logs dashboard/.next dashboard/tsconfig.tsbuildinfo

clean:              ## Remove ALL generated data on both sides (keeps the weather/holiday caches); `make bootstrap` rebuilds it
	rm -rf exchange simulator/var/state simulator/var/truth simulator/var/reports
	rm -rf data/warehouse data/models data/serving data/reports data/pilot data/app data/mlflow

import os

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
# Tests are hermetic: always the local DuckDB warehouse, whatever .env selects (set before perisentra loads .env).
os.environ["PERISENTRA_DBT_TARGET"] = "duckdb"

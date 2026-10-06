"""Central configuration: paths, YAML configs and environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(os.environ.get("PERISENTRA_ROOT", Path(__file__).resolve().parents[2]))
# Local settings (warehouse backend, Snowflake account, ...) from <root>/.env; real environment variables win.
load_dotenv(ROOT / ".env", override=False)
if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH"):     # dbt does not expand "~"
    os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"] = str(Path(os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"]).expanduser())

WAREHOUSE_TARGETS = ("duckdb", "snowflake")


def warehouse_target() -> str:
    """The warehouse in use: `snowflake` (default) or `duckdb`, an offline copy in data/warehouse used by the tests
    and when Snowflake is unreachable. The same variable selects the dbt target, so ingestion, dbt and every model
    read and write the same warehouse."""
    target = os.environ.get("PERISENTRA_DBT_TARGET", "snowflake").strip().lower()
    if target not in WAREHOUSE_TARGETS:
        raise ValueError(f"PERISENTRA_DBT_TARGET must be one of {WAREHOUSE_TARGETS}, got {target!r}")
    return target


def dbt_target_dir() -> Path:
    """dbt artifacts (manifest, run results) of the warehouse in use, kept apart per warehouse."""
    return PATHS.dbt_project / "target" / warehouse_target()


def _dir(var: str, default: Path) -> Path:
    p = Path(os.environ.get(var, default))
    return p if p.is_absolute() else ROOT / p          # relative paths in .env are relative to the project root


CONFIG_DIR = _dir("PERISENTRA_CONFIG_DIR", ROOT / "configs")
DATA_DIR = _dir("PERISENTRA_DATA_DIR", ROOT / "data")
# The exchange with the retailer: source extracts arrive in inbound/, the daily store task lists go to outbound/
# (an SFTP or S3 drop in production)
EXCHANGE_DIR = _dir("PERISENTRA_EXCHANGE_DIR", ROOT / "exchange")


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    data: Path = DATA_DIR
    inbound: Path = EXCHANGE_DIR / "inbound"
    outbound: Path = EXCHANGE_DIR / "outbound"
    external: Path = DATA_DIR / "external"
    warehouse_dir: Path = DATA_DIR / "warehouse"
    warehouse: Path = DATA_DIR / "warehouse" / "perisentra.duckdb"
    models: Path = DATA_DIR / "models"
    serving: Path = DATA_DIR / "serving"
    pilot: Path = DATA_DIR / "pilot"
    reports: Path = DATA_DIR / "reports"
    app_db: Path = DATA_DIR / "app" / "perisentra.db"
    mlflow: Path = DATA_DIR / "mlflow"
    dbt_project: Path = ROOT / "warehouse"

    def ensure(self) -> Paths:
        for p in (self.external, self.warehouse_dir, self.models, self.serving, self.pilot, self.reports,
                  self.app_db.parent, self.mlflow, self.outbound):
            p.mkdir(parents=True, exist_ok=True)
        return self


PATHS = Paths()


def _load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def client_config() -> dict[str, Any]:
    """What was agreed with the retailer: name, country, currency, the current rule, the pilot, live stores."""
    return _load_yaml("client.yaml")


@lru_cache
def model_config() -> dict[str, Any]:
    return _load_yaml("model.yaml")


def default_rules() -> dict[str, Any]:
    return _load_yaml("business_rules.yaml")


def as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def mlflow_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI", f"sqlite:///{PATHS.mlflow / 'mlflow.db'}")

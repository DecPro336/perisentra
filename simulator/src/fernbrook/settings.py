"""Paths and configuration of the simulator (independent of any consuming system)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

HOME = Path(os.environ.get("FERNBROOK_HOME", Path(__file__).resolve().parents[2]))


def _dir(var: str, default: Path) -> Path:
    p = Path(os.environ.get(var, default))
    return p if p.is_absolute() else HOME / p


CONFIG_FILE = _dir("FERNBROOK_CONFIG", HOME / "config" / "world.yaml")
VAR_DIR = _dir("FERNBROOK_VAR", HOME / "var")                         # state, ground truth, caches, reports
EXCHANGE_DIR = _dir("FERNBROOK_EXCHANGE_DIR", HOME.parent / "exchange")


@dataclass(frozen=True)
class Paths:
    config: Path = CONFIG_FILE
    var: Path = VAR_DIR
    exchange: Path = EXCHANGE_DIR

    @property
    def inbound(self) -> Path:            # what the retailer delivers: source-system extracts
        return self.exchange / "inbound"

    @property
    def outbound(self) -> Path:           # what comes back: daily store task lists
        return self.exchange / "outbound"

    @property
    def state(self) -> Path:
        return self.var / "state"

    @property
    def truth(self) -> Path:
        return self.var / "truth"

    @property
    def cache(self) -> Path:
        return self.var / "cache"

    @property
    def reports(self) -> Path:
        return self.var / "reports"


PATHS = Paths()


@lru_cache
def config() -> dict[str, Any]:
    with open(PATHS.config, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def get_logger(name: str) -> logging.Logger:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=os.environ.get("FERNBROOK_LOG_LEVEL", "INFO"),
                            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", datefmt="%H:%M:%S")
        logging.getLogger("httpx").setLevel(logging.WARNING)     # one line per API call otherwise
    return logging.getLogger(name)

"""Small shared helpers: logging, timing, atomic file writes."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=os.environ.get("PERISENTRA_LOG_LEVEL", "INFO"), format=_FORMAT,
                            datefmt="%H:%M:%S")
        for noisy in ("httpx", "pytensor", "pymc", "numba", "alembic", "mlflow", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger(name)


@contextmanager
def timed(logger: logging.Logger, label: str) -> Iterator[None]:
    start = time.perf_counter()
    logger.info("%s ...", label)
    yield
    logger.info("%s done in %.1fs", label, time.perf_counter() - start)


class _Encoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (pd.Timestamp,)):
            return o.date().isoformat() if o.hour == 0 and o.minute == 0 else o.isoformat()
        if hasattr(o, "isoformat"):
            return o.isoformat()
        return super().default(o)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, cls=_Encoder, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Atomic parquet write so readers (the API) never see half-written files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def safe_div(a: Any, b: Any, default: float = 0.0) -> Any:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b != 0, a / np.where(b == 0, 1, b), default)
    return out if out.ndim else float(out)

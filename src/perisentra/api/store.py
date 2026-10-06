"""Serving-data access for the API: parquet/JSON artefacts reloaded automatically when they change."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from perisentra.config import PATHS

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def _cached(path: Path, loader: Callable[[Path], Any]) -> Any:
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    key = str(path)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    value = loader(path)
    with _lock:
        _cache[key] = (mtime, value)
    return value


def parquet(name: str, root: Path = PATHS.serving) -> pd.DataFrame:
    df = _cached(root / name, pd.read_parquet)
    return df if df is not None else pd.DataFrame()


def json_file(path: Path) -> Any:
    return _cached(path, lambda p: json.loads(p.read_text(encoding="utf-8")))


def run_meta() -> dict:
    return json_file(PATHS.serving / "run_meta.json") or {}


def recommendations() -> pd.DataFrame:
    return parquet("recommendations.parquet")


def candidates() -> pd.DataFrame:
    df = parquet("candidates.parquet")
    return df


def forecasts() -> pd.DataFrame:
    return parquet("forecasts.parquet")


def history() -> pd.DataFrame:
    return parquet("history.parquet")


def lots() -> pd.DataFrame:
    return parquet("lots.parquet")


def records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe records (NaN -> None, timestamps -> ISO dates)."""
    if df is None or df.empty:
        return []
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return json.loads(out.to_json(orient="records", date_format="iso", default_handler=str))

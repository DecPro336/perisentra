"""Mondrian split-conformal prediction intervals for count forecasts.

Scores are signed and normalised by the Tweedie scale (pred + 1)^(p/2), so intervals widen with volume
and stay asymmetric (right-skewed) like count demand. Calibration is done per (family x volume bucket)
group, which gives approximately group-conditional coverage; small groups fall back to the family and
then to the global distribution.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

VOLUME_EDGES = [0.0, 2.0, 6.0, 15.0, np.inf]
VOLUME_LABELS = ["<2", "2-6", "6-15", "15+"]
MIN_GROUP = 300


def volume_bucket(pred: np.ndarray) -> np.ndarray:
    return pd.cut(np.asarray(pred, float), VOLUME_EDGES, labels=VOLUME_LABELS, right=False).astype(str)


def _scale(pred: np.ndarray, power: float) -> np.ndarray:
    return (np.asarray(pred, float) + 1.0) ** (power / 2)


def _q(scores: np.ndarray, level: float) -> tuple[float, float]:
    n = len(scores)
    a = 1 - level
    lo_rank = np.floor((n + 1) * (a / 2)) / n
    hi_rank = min(1.0, np.ceil((n + 1) * (1 - a / 2)) / n)
    return float(np.quantile(scores, max(lo_rank, 0.0))), float(np.quantile(scores, hi_rank))


def fit(family: np.ndarray, pred: np.ndarray, y: np.ndarray, levels: list[float], power: float) -> pd.DataFrame:
    df = pd.DataFrame({"family": family, "bucket": volume_bucket(pred),
                       "score": (np.asarray(y, float) - pred) / _scale(pred, power)})
    rows = []
    groups = [("*", "*", df)]
    groups += [(f, "*", g) for f, g in df.groupby("family")]
    groups += [(f, b, g) for (f, b), g in df.groupby(["family", "bucket"])]
    for fam, bucket, g in groups:
        if len(g) < MIN_GROUP:
            continue
        for level in levels:
            lo, hi = _q(g["score"].to_numpy(), level)
            rows.append({"family": fam, "bucket": bucket, "level": level, "q_lo": lo, "q_hi": hi, "n": len(g)})
    return pd.DataFrame(rows)


def apply(table: pd.DataFrame, family: np.ndarray, pred: np.ndarray, level: float, power: float
          ) -> tuple[np.ndarray, np.ndarray]:
    t = table[table["level"] == level]
    look = {(r.family, r.bucket): (r.q_lo, r.q_hi) for r in t.itertuples()}
    buckets = volume_bucket(pred)
    q = np.array([look.get((f, b)) or look.get((f, "*")) or look[("*", "*")] for f, b in zip(family, buckets)])
    scale = _scale(pred, power)
    lo = np.maximum(0.0, pred + q[:, 0] * scale)
    hi = np.maximum(lo, pred + q[:, 1] * scale)
    return lo, hi

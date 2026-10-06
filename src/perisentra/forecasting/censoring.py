"""Censored-demand helpers (negative binomial).

On a stock-out day we only know demand D >= observed sales s. Under D ~ NB(mean mu, dispersion k):

    E[D | D >= s] = mu * P(D' >= s-1) / P(D >= s),   D' ~ NB(k + 1, p)

which follows from d * pmf(d; k, p) = mu * pmf(d - 1; k + 1, p). The EM loop replaces censored targets
with this expectation and refits the model until the imputations stabilise.
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def nb_params(mu: np.ndarray, k: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = np.maximum(np.asarray(mu, dtype=float), 1e-6)
    k = np.broadcast_to(np.asarray(k, dtype=float), mu.shape)
    p = k / (k + mu)
    return k, p


def conditional_mean_at_least(s: np.ndarray, mu: np.ndarray, k: np.ndarray) -> np.ndarray:
    s = np.asarray(s, dtype=float)
    n, p = nb_params(mu, k)
    num = stats.nbinom.sf(s - 2, n + 1, p)      # P(D' >= s-1)
    den = stats.nbinom.sf(s - 1, n, p)          # P(D >= s)
    mu = np.maximum(np.asarray(mu, dtype=float), 1e-6)
    with np.errstate(divide="ignore", invalid="ignore"):
        e = np.where(den > 1e-12, mu * num / den, s + 1.0)
    return np.maximum(e, s)


def dispersion_from_residuals(y: np.ndarray, mu: np.ndarray, lo: float = 1.0, hi: float = 80.0) -> float:
    """Method-of-moments k from Var(y - mu) = mu + mu^2 / k."""
    y, mu = np.asarray(y, float), np.asarray(mu, float)
    excess = np.sum((y - mu) ** 2 - mu)
    if excess <= 0:
        return hi
    return float(np.clip(np.sum(mu ** 2) / excess, lo, hi))

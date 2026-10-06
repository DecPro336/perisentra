import numpy as np
from scipy import stats

from perisentra.forecasting.censoring import conditional_mean_at_least, dispersion_from_residuals


def test_no_censoring_returns_mean():
    mu = np.array([0.5, 3.0, 12.0])
    assert np.allclose(conditional_mean_at_least(np.zeros(3), mu, np.full(3, 10.0)), mu, rtol=1e-6)


def test_conditional_mean_matches_monte_carlo():
    rng = np.random.default_rng(0)
    mu, k, s = 6.0, 8.0, 7
    p = k / (k + mu)
    draws = stats.nbinom.rvs(k, p, size=400_000, random_state=rng)
    mc = draws[draws >= s].mean()
    analytic = conditional_mean_at_least(np.array([s]), np.array([mu]), np.array([k]))[0]
    assert abs(analytic - mc) < 0.05


def test_conditional_mean_is_at_least_observed_and_monotone():
    s = np.arange(0, 30)
    e = conditional_mean_at_least(s, np.full(30, 5.0), np.full(30, 4.0))
    assert np.all(e >= s)
    assert np.all(np.diff(e) > 0)


def test_dispersion_recovers_k():
    rng = np.random.default_rng(1)
    mu = rng.uniform(2, 20, 200_000)
    k = 7.0
    y = rng.negative_binomial(k, k / (k + mu))
    assert abs(dispersion_from_residuals(y, mu) - k) < 0.5

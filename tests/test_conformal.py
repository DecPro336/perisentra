import numpy as np

from perisentra.forecasting import conformal


def test_split_conformal_coverage_holds_out_of_sample():
    rng = np.random.default_rng(2)
    n = 60_000
    fam = rng.choice(["A", "B"], n)
    mu = rng.uniform(0.5, 30, n) * np.where(fam == "A", 1.0, 2.0)
    y = rng.negative_binomial(5, 5 / (5 + mu))
    pred = mu * rng.lognormal(0, 0.1, n)
    cal, test = slice(0, n // 2), slice(n // 2, n)
    table = conformal.fit(fam[cal], pred[cal], y[cal], [0.8, 0.95], power=1.25)
    for level in (0.8, 0.95):
        lo, hi = conformal.apply(table, fam[test], pred[test], level, 1.25)
        cov = np.mean((y[test] >= lo) & (y[test] <= hi))
        assert abs(cov - level) < 0.02, (level, cov)


def test_intervals_are_non_negative_and_ordered():
    rng = np.random.default_rng(3)
    pred = rng.uniform(0, 10, 5000)
    y = rng.poisson(pred)
    table = conformal.fit(np.array(["X"] * 5000), pred, y, [0.8], power=1.2)
    lo, hi = conformal.apply(table, np.array(["X"] * 5000), pred, 0.8, 1.2)
    assert np.all(lo >= 0) and np.all(hi >= lo)

import numpy as np

from perisentra.risk.montecarlo import ActionSet, RiskBatch, _fifo, simulate


def _batch(lots, mu, elasticity=1.8, price=4.0, cost=2.0, H=7):
    n = lots.shape[0]
    return RiskBatch(lots=lots.astype(float), incoming=np.zeros((n, H)), shelf=np.full(n, 5), mu=np.full((n, H), mu),
                     price=np.full((n, H), price), cost=np.full(n, cost), k=np.full(n, 20.0), path_sigma=np.full(n, 0.05),
                     elasticity=np.full((n, 50), elasticity), next_delivery=np.full(n, 1), cover_end=np.full(n, 2))


def test_fifo_takes_oldest_first():
    stock = np.array([[3.0, 2.0, 5.0]])
    _fifo(stock, np.array([4.0]))
    assert stock.tolist() == [[0.0, 1.0, 5.0]]


def test_markdown_reduces_waste_of_expiring_stock():
    lots = np.zeros((1, 21)); lots[0, 0] = 12          # 12 units expire tonight, demand ~4
    b = _batch(lots, mu=4.0)
    res = simulate(b, ActionSet(discount=np.array([[0.0, 0.4]]), window=np.array([-1, 0])), n_paths=2000, seed=1)
    assert res.waste_units[0, 1] < res.waste_units[0, 0] - 1.0
    assert res.discount_given[0, 0] == 0
    assert res.p_waste[0, 0] > 0.9


def test_conservation_of_units():
    lots = np.zeros((1, 21)); lots[0, 1] = 10; lots[0, 4] = 6
    b = _batch(lots, mu=3.0)
    res = simulate(b, ActionSet(discount=np.zeros((1, 1)), window=np.array([-1])), n_paths=500, seed=2)
    # every unit on hand is either sold or wasted within the horizon (all lots expire inside it here)
    assert np.isclose(res.sold[0, 0] + res.waste_units[0, 0], 16, atol=1e-4)


def test_empty_shelf_means_stockout_and_no_waste():
    b = _batch(np.zeros((1, 21)), mu=5.0)
    res = simulate(b, ActionSet(discount=np.zeros((1, 1)), window=np.array([-1])), n_paths=500, seed=3)
    assert res.waste_units[0, 0] == 0
    assert res.p_stockout[0, 0] > 0.95

import copy
from datetime import date

import numpy as np
from worlds import make_world


def test_stock_is_conserved(world):
    w = copy.deepcopy(world)
    for _ in range(60):
        before = w.lots.sum()
        r = w.step(record=False)
        flows = r.received.sum() - r.units_sold.sum() - (r.waste_recorded + r.waste_unrecorded + r.damaged + r.donated).sum()
        shrink = before + flows - w.lots.sum()
        assert 0 <= shrink <= 0.02 * max(before, 1)   # only unrecorded shrink is unaccounted


def test_same_random_numbers_whatever_the_stores_decide(world):
    """Common random numbers: a different course of action never changes the demand draws."""
    a, b = copy.deepcopy(world), copy.deepcopy(world)
    for _ in range(20):
        a.step(record=False)
        b.step(record=False)
    from fernbrook.world import Actions

    md = np.full(b.N, np.nan)
    md[: b.N // 2] = 0.3
    ra = a.step(record=False)
    rb = b.step(lambda w, t: Actions(markdown_pct=md, markdown_window=np.full(b.N, 1)), record=False)
    assert np.array_equal(ra.true_demand, rb.true_demand)


def test_saved_state_resumes_exactly(world):
    a = copy.deepcopy(world)
    for _ in range(30):
        a.step(record=False)
    b = make_world(world.horizon_end)
    b.load_state(a.state())
    assert b.today == a.today
    ra, rb = a.step(record=False), b.step(record=False)
    for field in ("units_sold", "received", "waste_recorded", "md_pct", "counted"):
        assert np.array_equal(getattr(ra, field), getattr(rb, field)), field


def test_a_longer_calendar_never_changes_earlier_days(world):
    longer = make_world(date(2025, 9, 30))
    n = world.n_days - 8
    for name in ("promo_pct", "flyer", "store_open", "active_mat"):
        assert np.array_equal(getattr(world, name)[..., :n], getattr(longer, name)[..., :n]), name
    assert np.array_equal(world.test_stores, longer.test_stores)
    assert len(longer.promotions) > len(world.promotions)


def test_erp_view_of_the_world(world):
    schedule = world.delivery_schedule()
    assert set(schedule.unique()) <= {"daily", "mon_wed_fri", "in_store_bake"}
    fams = world.catalog.products.set_index("sku_id")["family"]
    assert (schedule[fams[fams == "Bakery"].index] == "in_store_bake").all()
    closures = world.closures()
    assert set(closures["closure_date"]) == {date(2024, 11, 28), date(2024, 12, 25)}
    assert not world.store_open[:, world.index_of(date(2024, 12, 25))].any()

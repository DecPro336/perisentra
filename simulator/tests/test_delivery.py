"""Task lists in, daily extracts out: the exchange contract with a decision system."""

import copy
import json

import numpy as np
import pandas as pd
import pytest
from fernbrook import exporter, stores
from fernbrook.settings import Paths


@pytest.fixture
def paths(tmp_path, monkeypatch):
    p = Paths(config=Paths().config, var=tmp_path / "var", exchange=tmp_path / "exchange")
    for module in (exporter, stores):
        monkeypatch.setattr(module, "PATHS", p)
    return p


def _tasks(world, n=8):
    s = world.series.iloc[:n]
    return pd.DataFrame({"store_id": s["store_id"], "sku_id": s["sku_id"],
                         "action": ["MARKDOWN", "NO_ACTION"] * (n // 2), "discount_pct": [30.0, 0.0] * (n // 2),
                         "markdown_window_days": [2, 0] * (n // 2), "order_qty": [7] * n, "donate_units": [3, 0] * (n // 2),
                         "run_id": "run-test"})


def test_task_list_becomes_store_actions(world):
    tasks = _tasks(world)
    policy = stores.TaskListPolicy(world, tasks)
    act = policy(world, world.t)
    assert np.allclose(act.markdown_pct[:8], [0.3, 0.0] * 4)          # "no markdown" overrides the store's rule
    assert np.isnan(act.markdown_pct[8:]).all()                        # no task: the store's rule applies
    assert (act.markdown_window[:8] == [1, -1] * 4).all()
    assert (act.order_override[:8] == 7).all() and (act.order_override[8:] == -1).all()
    assert act.donate[:8].tolist() == [True, False] * 4


def test_unknown_items_are_ignored(world):
    tasks = pd.concat([_tasks(world), _tasks(world).assign(sku_id=999_999)], ignore_index=True)
    assert len(stores.TaskListPolicy(world, tasks).tasks) == 8


def test_store_app_reports_what_was_done(world):
    w = copy.deepcopy(world)
    policy = stores.TaskListPolicy(w, _tasks(w))
    rec = w.step(policy, record=False)
    dec = policy.decisions(rec, w.dates[rec.t], "2025-01-01T06:00:00")
    assert list(dec.columns) == stores.DECISION_COLUMNS
    assert set(dec["decision"]) <= {"ACCEPTED", "NOT_APPLIED"}
    assert (dec["decision"] == "ACCEPTED").sum() == int((rec.source[:8] == 1).sum())


def test_daily_delivery_writes_extracts_and_manifest(world, paths):
    w = copy.deepcopy(world)
    for _ in range(40):
        w.step(record=False)
    day = w.today
    rec = w.step()
    writer = exporter.Writer(paths.inbound)
    exporter.export_records(w, [rec], day.isoformat(), writer, daily=True)
    exporter.export_masters(w, writer)
    manifest = exporter.write_manifest(writer, day, kind="daily")
    body = json.loads(manifest.read_text())
    assert body["business_date"] == day.isoformat()
    for rel in body["files"]:
        assert (paths.inbound / rel).exists(), rel
    pos = pd.read_parquet(paths.inbound / "pos" / f"pos_daily_sales_{day.isoformat()}.parquet")
    assert set(pos["business_date"]) == {day}
    products = pd.read_csv(paths.inbound / "erp" / "products.csv")
    assert "delivery_schedule" in products.columns
    assert pd.read_csv(paths.inbound / "erp" / "assortment.csv")["listed_to"].isna().all()
    assert (paths.truth / f"truth_{day.isoformat()}.parquet").exists()
    assert not list(paths.inbound.rglob("*.part"))                   # files are published atomically

"""The exchange with the retailer: delivery manifests in, store task lists out, store-app decisions back."""

import json
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from perisentra import cli
from perisentra.config import PATHS
from perisentra.decision.inputs import delivery_offsets
from perisentra.ingestion import load_raw
from perisentra.monitoring import feedback
from perisentra.pipeline import score


@pytest.fixture
def paths(tmp_path, monkeypatch):
    p = replace(PATHS, inbound=tmp_path / "exchange" / "inbound", outbound=tmp_path / "exchange" / "outbound",
                app_db=tmp_path / "app" / "perisentra.db")
    for module in (cli, score, feedback, load_raw):
        monkeypatch.setattr(module, "PATHS", p)
    return p


def _recs(store_ids, discount=30.0):
    rows = []
    for s in store_ids:
        for k in (1001, 1002):
            rows.append({"store_id": s, "sku_id": k, "product_name": f"P{k}", "action": "MARKDOWN" if k == 1001 else "NO_ACTION",
                         "discount_pct": discount if k == 1001 else 0.0, "markdown_window_days": 2, "new_price": 2.79,
                         "order_model": 12, "order_recommended": 10, "donate_units": 0, "confidence_tier": "HIGH",
                         "run_id": "run-test"})
    return pd.DataFrame(rows)


def test_task_list_goes_to_live_stores_only(paths, monkeypatch):
    monkeypatch.setattr(score, "live_stores", lambda: [1, 2])
    n = score.publish_task_list(_recs([1, 2, 3]), date(2026, 10, 5))
    tasks = pd.read_csv(score.task_list_path(date(2026, 10, 5)))
    assert n == 4 and set(tasks["store_id"]) == {1, 2}
    assert list(tasks.columns) == score.TASK_COLUMNS
    assert (tasks["order_qty"] == 12).all()                  # the engine's own order, not the display reference
    assert not list(paths.outbound.rglob("*.part"))


def test_a_store_rerun_replaces_only_that_store(paths, monkeypatch):
    monkeypatch.setattr(score, "live_stores", lambda: [1, 2])
    day = date(2026, 10, 5)
    score.publish_task_list(_recs([1, 2]), day)
    score.publish_task_list(_recs([2], discount=40.0), day, stores=[2])
    tasks = pd.read_csv(score.task_list_path(day)).set_index(["store_id", "sku_id"])
    assert tasks.loc[(1, 1001), "discount_pct"] == 30.0 and tasks.loc[(2, 1001), "discount_pct"] == 40.0
    assert len(tasks) == 4


def test_check_inbound_waits_for_the_manifest(paths):
    runner = CliRunner()
    assert runner.invoke(cli.app, ["check-inbound", "--date", "2026-10-04"]).exit_code == 1
    manifest = paths.inbound / "_manifests" / "2026-10-04.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"business_date": "2026-10-04", "files": {}}))
    assert runner.invoke(cli.app, ["check-inbound", "--date", "2026-10-04"]).exit_code == 0


def test_ingestion_skips_a_delivery_in_progress(paths):
    pos = paths.inbound / "pos"
    pos.mkdir(parents=True)
    for day in ("2026-10-03", "2026-10-04"):
        pd.DataFrame({"sale_date": [day], "units": [1]}).to_parquet(pos / f"pos_daily_sales_{day}.parquet")
    manifest = paths.inbound / "_manifests" / "2026-10-03.json"          # the 4th has no manifest yet
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"business_date": "2026-10-03", "files": {"pos/pos_daily_sales_2026-10-03.parquet": 1}}))
    feeds = {table: files for table, _, files in load_raw._source_files()}
    assert [f.name for f in feeds["pos_daily_sales"]] == ["pos_daily_sales_2026-10-03.parquet"]


def test_store_app_decisions_are_imported_once(paths, tmp_path):
    f = tmp_path / "decisions_2026-10-04.csv"
    pd.DataFrame({"run_id": ["r"] * 3, "as_of_date": ["2026-10-04"] * 3, "store_id": [1, 1, 2], "sku_id": [1001, 1002, 1001],
                  "decision": ["ACCEPTED", "NOT_APPLIED", "ACCEPTED"], "applied_action": ["MARKDOWN", "STORE_RULE", "NO_ACTION"],
                  "applied_discount_pct": [30.0, 30.0, 0.0], "note": "", "user": "store-app",
                  "recorded_at": "2026-10-05T01:00:00"}).to_csv(f, index=False)
    assert feedback.import_store_app([f]) == 3
    assert feedback.import_store_app([f]) == 0
    assert feedback.task_list_compliance([1, 2], "2026-10-01", "2026-10-31") == pytest.approx(2 / 3)


def test_delivery_days_follow_the_erp_schedule_and_closures():
    as_of = date(2026, 11, 25)                          # Wednesday; Thanksgiving (26th) is a closure
    days = pd.date_range("2026-11-26", periods=10).date
    cal = pd.DataFrame({"store_id": 1, "date_day": days, "is_open": [d != date(2026, 11, 26) for d in days]})
    nxt, end = delivery_offsets(as_of, np.array(["daily", "mon_wed_fri", "in_store_bake"]), np.array([1, 1, 1]), cal)
    assert (nxt[0], end[0]) == (2, 3)       # Friday, Saturday (Thursday closed)
    assert (nxt[1], end[1]) == (2, 5)       # Friday, Monday
    assert (nxt[2], end[2]) == (2, 3)       # baked every open day

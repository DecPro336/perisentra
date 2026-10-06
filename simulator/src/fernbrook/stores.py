"""How stores use a daily task list published by a decision system (the outbound exchange folder).

Each morning, a store with a task list for the day applies it item by item: put the stickers on (discount and
which lots), place tonight's order for the quantity given, donate what is left at close. About 90% of items are
carried out (`stores_behaviour.task_compliance`); for the rest the store falls back on its current rule. The
store app then reports, per item, whether it was done.

Task list columns: store_id, sku_id, action (MARKDOWN / NO_ACTION), discount_pct, markdown_window_days,
order_qty, donate_units, run_id.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from fernbrook.settings import PATHS, get_logger
from fernbrook.world import Actions, DayRecord, World

log = get_logger(__name__)
REQUIRED = ["store_id", "sku_id", "action", "discount_pct", "markdown_window_days", "order_qty", "donate_units",
            "run_id"]
DECISION_COLUMNS = ["run_id", "as_of_date", "store_id", "sku_id", "decision", "applied_action",
                    "applied_discount_pct", "note", "user", "recorded_at"]


def task_list_path(day: date, outbound: Path | None = None) -> Path:
    return (outbound or PATHS.outbound) / "store_tasks" / f"tasks_{day.isoformat()}.csv"


def load_task_list(day: date, outbound: Path | None = None) -> pd.DataFrame | None:
    path = task_list_path(day, outbound)
    if not path.exists():
        return None
    tasks = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in tasks.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    return tasks


class TaskListPolicy:
    """Turns one day's task list into the stores' actions for that morning and evening."""

    def __init__(self, world: World, tasks: pd.DataFrame):
        key = {(int(s), int(k)): i for i, (s, k) in enumerate(zip(world.series["store_id"], world.series["sku_id"]))}
        idx = np.array([key.get((int(s), int(k)), -1) for s, k in zip(tasks["store_id"], tasks["sku_id"])])
        unknown = int((idx < 0).sum())
        if unknown:
            log.warning("Task list: %d items for products not listed in their store were ignored", unknown)
        self.tasks = tasks[idx >= 0].reset_index(drop=True)
        self.idx = idx[idx >= 0]

    def __call__(self, world: World, t: int) -> Actions:
        N = world.N
        is_md = (self.tasks["action"] == "MARKDOWN").to_numpy()
        md = np.full(N, np.nan)
        win = np.full(N, -1)
        order = np.full(N, -1)
        donate = np.zeros(N, dtype=bool)
        # a task without a markdown means "no sticker today", which overrides the store's flat rule
        md[self.idx] = np.where(is_md, self.tasks["discount_pct"].to_numpy(float) / 100, 0.0)
        win[self.idx] = np.where(is_md, self.tasks["markdown_window_days"].fillna(1).to_numpy(int) - 1, -1)
        order[self.idx] = self.tasks["order_qty"].fillna(-1).to_numpy(int)
        donate[self.idx] = self.tasks["donate_units"].fillna(0).to_numpy(float) > 0
        return Actions(markdown_pct=md, markdown_window=win, order_override=order, donate=donate)

    def decisions(self, rec: DayRecord, day: date, recorded_at: str) -> pd.DataFrame:
        """What the store app reports: each item done (ACCEPTED) or not (NOT_APPLIED)."""
        done = rec.source[self.idx] == 1
        d = self.tasks[["run_id", "store_id", "sku_id", "action", "discount_pct"]].copy()
        d["as_of_date"] = day.isoformat()
        d["decision"] = np.where(done, "ACCEPTED", "NOT_APPLIED")
        d["applied_action"] = np.where(done, d["action"], "STORE_RULE")
        d["applied_discount_pct"] = np.where(done, d["discount_pct"], np.round(rec.md_pct[self.idx] * 100, 1))
        d["note"] = ""
        d["user"] = "store-app"
        d["recorded_at"] = recorded_at
        return d[DECISION_COLUMNS]

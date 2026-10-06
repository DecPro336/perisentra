"""Run the world: build the history once (backfill), then deliver one business day at a time (advance)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np

from fernbrook.catalog import build_catalog
from fernbrook.exporter import Writer, export_masters, export_records, write_manifest
from fernbrook.external import public_holidays, weather
from fernbrook.settings import PATHS, as_date, config, get_logger
from fernbrook.stores import TaskListPolicy, load_task_list
from fernbrook.world import World

log = get_logger(__name__)
STATE_FILE = "world.npz"
HORIZON_AHEAD_DAYS = 60        # calendar built beyond the last simulated day (promo calendar, closures, orders)


def _locations(cfg: dict) -> list[dict]:
    return [{"location_id": s["id"], "lat": s["lat"], "lon": s["lon"]} for s in cfg["stores"]]


def build_world(horizon_end: date) -> World:
    """The world with its calendar up to `horizon_end`. Everything is derived from the config and the seed, so
    rebuilding it reproduces every earlier day exactly; only the dynamic state comes from the saved file."""
    cfg = config()
    cal = cfg["calendar"]
    t0 = as_date(cal["start_date"]) - timedelta(days=int(cal["warmup_days"]))
    wx = weather(_locations(cfg), t0, horizon_end)
    hol = public_holidays(list(range(t0.year, horizon_end.year + 1)), cfg["country"])
    rng = np.random.default_rng(cfg["seed"])
    catalog = build_catalog(cfg, rng)
    return World(cfg=cfg, catalog=catalog, weather=wx, holidays=hol, seed=int(cfg["seed"]), horizon_end=horizon_end)


def save_state(world: World, name: str = STATE_FILE) -> None:
    PATHS.state.mkdir(parents=True, exist_ok=True)
    tmp = PATHS.state / f"{name}.part.npz"
    np.savez_compressed(tmp, **world.state())
    tmp.replace(PATHS.state / name)
    meta = {"next_day": world.today.isoformat(), "saved_at": datetime.now().isoformat(timespec="seconds")}
    (PATHS.state / f"{name}.json").write_text(json.dumps(meta, indent=2))


def next_day(name: str = STATE_FILE) -> date | None:
    """The next business day to be played, or None before the history has been built."""
    meta = PATHS.state / f"{name}.json"
    return date.fromisoformat(json.loads(meta.read_text())["next_day"]) if meta.exists() else None


def load_world(until: date, name: str = STATE_FILE) -> World:
    day = next_day(name)
    if day is None:
        raise FileNotFoundError("no saved world: run `fernbrook backfill` first")
    world = build_world(max(until, day) + timedelta(days=HORIZON_AHEAD_DAYS))
    with np.load(PATHS.state / name) as state:
        world.load_state(dict(state))
    if world.today != day:
        raise RuntimeError(f"saved state is for {day}, rebuilt world is at {world.today}")
    return world


def backfill(until: date, force: bool = False) -> dict:
    """The chain's history up to `until`, under the stores' current rule (and the spring price test)."""
    if next_day() is not None and not force:
        raise FileExistsError("the history already exists (use --force to rebuild it from scratch)")
    world = build_world(until + timedelta(days=HORIZON_AHEAD_DAYS))
    log.info("World: %d stores, %d SKUs, %d store-SKU series; price-test stores %s",
             world.S, len(world.catalog.products), world.N, list(world.test_stores))
    end_t = world.index_of(until)
    while world.t <= end_t:
        world.step()
        if world.t % 90 == 0:
            log.info("  simulated through %s", world.dates[world.t - 1])
    writer = Writer(PATHS.inbound)
    export_records(world, world.records, "history", writer, daily=False, first_batch=True)
    export_masters(world, writer)
    write_manifest(writer, until, kind="history")
    world.records = []
    save_state(world)
    log.info("History delivered: %s -> %s (%d files)", world.start, until, len(writer.files))
    return writer.files


def advance(until: date | None = None) -> list[date]:
    """Play every missing day up to `until` (default: yesterday) and deliver each day's extracts.

    For each day: if a task list was published for it, the stores apply it; otherwise they follow their rule.
    State is saved after every day, so an interrupted run resumes where it stopped."""
    until = until or date.today() - timedelta(days=1)
    first = next_day()
    if first is None:
        raise FileNotFoundError("no saved world: run `fernbrook backfill` first")
    if first > until:
        log.info("Up to date: the next business day to play is %s", first)
        return []
    world = load_world(until)
    delivered = []
    while world.today <= until:
        day = world.today
        tasks = load_task_list(day)
        policy = TaskListPolicy(world, tasks) if tasks is not None else None
        if policy is not None and load_task_list(day - timedelta(days=1)) is None:
            # the first morning with a task list: keep the state so the period can be replayed (validation)
            save_state(world, name=f"checkpoint_{day.isoformat()}.npz")
        rec = world.step(policy)
        writer = Writer(PATHS.inbound)
        export_records(world, [rec], day.isoformat(), writer, daily=True)
        export_masters(world, writer)
        if policy is not None:
            dec = policy.decisions(rec, day, datetime.now().isoformat(timespec="seconds"))
            writer.frame(dec, f"storeapp/decisions_{day.isoformat()}.csv")
        write_manifest(writer, day, kind="daily")
        world.records = []
        save_state(world)
        delivered.append(day)
        log.info("Delivered %s: %d files%s", day, len(writer.files),
                 f", task list applied in stores {sorted(policy.tasks['store_id'].unique().tolist())}"
                 if policy is not None else ", no task list (stores followed their rule)")
    return delivered


def status() -> dict:
    day = next_day()
    manifests = sorted((PATHS.inbound / "_manifests").glob("*.json")) if (PATHS.inbound / "_manifests").exists() else []
    last = json.loads(manifests[-1].read_text()) if manifests else None
    yesterday = date.today() - timedelta(days=1)
    return {"next_business_day": day.isoformat() if day else None,
            "days_behind": max(0, (yesterday - day).days + 1) if day else None,
            "last_delivery": last["business_date"] if last else None,
            "last_delivery_files": len(last["files"]) if last else 0,
            "exchange": str(PATHS.exchange)}


"""Command line: `fernbrook <command>`.

    backfill   build the chain's history up to a date (once)
    advance    play every missing business day up to yesterday and deliver its extracts (nightly)
    status     where the world is, and the last delivery
    validate   grade a decision system's published outputs against the ground truth
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from fernbrook.settings import HOME, get_logger

app = typer.Typer(add_completion=False, help="Fernbrook Market source systems (simulated)")
log = get_logger("fernbrook")


def _date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


@app.command()
def backfill(until: str = typer.Option(..., help="Last day of the history (YYYY-MM-DD)"),
             force: bool = typer.Option(False, help="Rebuild from scratch even if a history exists")) -> None:
    """Simulate and deliver the history up to UNTIL, with every store on its current rule."""
    from fernbrook.runner import backfill as run

    run(_date(until), force=force)


@app.command()
def advance(until: str = typer.Option("", help="Last business day to deliver (default: yesterday)")) -> None:
    """Play and deliver every business day not delivered yet, applying published task lists."""
    from fernbrook.runner import advance as run

    days = run(_date(until))
    log.info("Delivered %d business day(s)%s", len(days), f": {days[0]} -> {days[-1]}" if days else "")


@app.command()
def status() -> None:
    """Next business day to play, days behind, last delivery."""
    from fernbrook.runner import status as run

    typer.echo(json.dumps(run(), indent=2))


@app.command()
def validate(product_data: str = typer.Option("", help="The decision system's data folder (default: ../data)")) -> None:
    """Grade the published forecasts, price response and pilot readout against the ground truth."""
    from fernbrook.validation import report

    out = report(Path(product_data) if product_data else HOME.parent / "data")
    log.info("Validation report written (%s)", ", ".join(k for k in out if k != "generated_at"))


if __name__ == "__main__":
    app()

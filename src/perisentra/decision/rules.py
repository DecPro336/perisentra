"""Business rules: schema validation, versioned storage and price helpers.

Rules live in configs/business_rules.yaml (the default) and every edit made from the dashboard is
saved as a new version in the app database, so each recommendation can be traced to the exact rule
set that produced it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from perisentra.config import PATHS, default_rules


class Objective(BaseModel):
    primary: str = "min_expected_waste_value"
    tie_tolerance_pct: float = Field(6, ge=0, le=50)
    min_waste_gain: float = Field(0.4, ge=0)
    markdown_must_pay_for_itself: bool = True      # stock is already bought: a markdown must raise expected revenue
    min_revenue_gain: float = Field(0.0, ge=0)


class Markdown(BaseModel):
    ladder_pct: list[int] = [10, 20, 30, 40, 50]
    max_days_before_expiry: int = Field(3, ge=1, le=7)
    max_discount_pct: dict[str, float] = {"default": 50}
    price_endings: list[float] = [0.99, 0.79, 0.49, 0.29]
    min_price: float = Field(0.29, ge=0)

    @field_validator("ladder_pct")
    @classmethod
    def _ladder(cls, v: list[int]) -> list[int]:
        if not v or any(x <= 0 or x >= 90 for x in v):
            raise ValueError("ladder values must be between 1 and 89 percent")
        return sorted(set(v))

    @field_validator("price_endings")
    @classmethod
    def _endings(cls, v: list[float]) -> list[float]:
        if any(not 0 <= x < 1 for x in v):
            raise ValueError("price endings are cents, e.g. 0.99")
        return v


class Margin(BaseModel):
    unit_floor_pct: dict[str, float] = {"default": -25}
    window_floor_pct: dict[str, float] = {"default": 8}


class Promotions(BaseModel):
    lock_markdowns_during_promo: bool = True


class Replenishment(BaseModel):
    enabled: bool = True
    min_change_units: int = 3
    min_change_pct: float = 30
    max_change_pct: float = 60
    service_level_bounds: tuple[float, float] = (0.80, 0.97)


class Donation(BaseModel):
    enabled: bool = True
    min_units: int = 3
    tax_benefit_pct: float = 50


class Exploration(BaseModel):
    rate: float = Field(0.08, ge=0, le=0.5)


class LegacyRule(BaseModel):
    """The store's current rule, evaluated alongside every decision as the reference point."""
    markdown_pct: float = 30
    days_before_expiry: int = 2


class Confidence(BaseModel):
    high_min_score: float = Field(0.70, ge=0, le=1)
    medium_min_score: float = Field(0.45, ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> Confidence:
        if self.medium_min_score >= self.high_min_score:
            raise ValueError("medium_min_score must be below high_min_score")
        return self


class Rules(BaseModel):
    version: int = 1
    objective: Objective = Objective()
    markdown: Markdown = Markdown()
    margin: Margin = Margin()
    promotions: Promotions = Promotions()
    replenishment: Replenishment = Replenishment()
    donation: Donation = Donation()
    exploration: Exploration = Exploration()
    confidence: Confidence = Confidence()
    legacy: LegacyRule = LegacyRule()

    @model_validator(mode="after")
    def _defaults_present(self) -> Rules:
        for name, d in (("max_discount_pct", self.markdown.max_discount_pct),
                        ("unit_floor_pct", self.margin.unit_floor_pct),
                        ("window_floor_pct", self.margin.window_floor_pct)):
            if "default" not in d:
                raise ValueError(f"{name} needs a 'default' entry")
        return self

    # -------------------------------------------------------------------------------------------
    @staticmethod
    def _by_family(d: dict[str, float], family: str) -> float:
        return float(d.get(family, d["default"]))

    def max_discount(self, family: str) -> float:
        return self._by_family(self.markdown.max_discount_pct, family) / 100

    def unit_floor(self, family: str) -> float:
        return self._by_family(self.margin.unit_floor_pct, family) / 100

    def window_floor(self, family: str) -> float:
        return self._by_family(self.margin.window_floor_pct, family) / 100

    def snap_price(self, price: float, floor: float | None = None) -> float:
        """Nearest price ending in one of the allowed endings (e.g. 6.24 -> 6.29, 5.31 -> 5.29). `floor` is the lowest
        price the family's maximum discount allows: only endings at or above it qualify, so rounding to a price
        ending never pushes a discount past the cap (3.99 at a 30% cap: 2.99, not 2.79)."""
        lowest = max(self.markdown.min_price, floor if floor is not None else 0.0)
        best, best_gap = None, None
        base = np.floor(price)
        for whole in (base - 1, base, base + 1):
            for e in self.markdown.price_endings:
                cand = round(whole + e, 2)
                if cand < lowest - 1e-9:
                    continue
                gap = abs(cand - price)
                if best_gap is None or gap < best_gap - 1e-9 or (abs(gap - best_gap) < 1e-9 and cand < best):
                    best, best_gap = cand, gap
        return float(best if best is not None else max(lowest, round(price, 2)))


# ----------------------------------------------------------------------------------------------
# versioned storage (SQLite app DB)
# ----------------------------------------------------------------------------------------------
def _db() -> sqlite3.Connection:
    PATHS.app_db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(PATHS.app_db)
    con.execute("""create table if not exists rules_versions (
        version integer primary key, saved_at text, saved_by text, comment text, body text)""")
    return con


FAMILY_MAPS = (("markdown", "max_discount_pct"), ("margin", "unit_floor_pct"), ("margin", "window_floor_pct"))


def _yaml_hash() -> str:
    return hashlib.sha1(json.dumps(default_rules(), sort_keys=True, default=str).encode()).hexdigest()


def current_rules() -> Rules:
    """Latest saved version. When configs/business_rules.yaml changes, it becomes a new version."""
    h = _yaml_hash()
    with _db() as con:
        con.execute("create table if not exists rules_seed (hash text)")
        seed = con.execute("select hash from rules_seed").fetchone()
        row = con.execute("select body from rules_versions order by version desc limit 1").fetchone()
    if row and seed and seed[0] == h:
        return Rules.model_validate(json.loads(row[0]))
    rules = save_rules(Rules.model_validate(default_rules()), "system",
                       "Rules loaded from configs/business_rules.yaml", merge=False)
    with _db() as con:
        con.execute("delete from rules_seed")
        con.execute("insert into rules_seed values (?)", (h,))
    return rules


def merge_rules(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial update section by section; per-family maps are replaced as a whole (a removed family
    override must go back to the default)."""
    out = json.loads(json.dumps(base))
    for section, fields in update.items():
        if isinstance(fields, dict) and isinstance(out.get(section), dict):
            out[section].update(fields)
        else:
            out[section] = fields
    return out


def unknown_families(rules: Rules, families: set[str]) -> list[str]:
    bad = []
    for section, field in FAMILY_MAPS:
        for fam in getattr(getattr(rules, section), field):
            if fam != "default" and fam not in families:
                bad.append(f"{section}.{field}.{fam}")
    return bad


def save_rules(rules: Rules | dict[str, Any], user: str = "dashboard", comment: str = "", merge: bool = True) -> Rules:
    if isinstance(rules, Rules):
        r = rules
    else:
        r = Rules.model_validate(merge_rules(current_rules().model_dump(), rules) if merge else rules)
    with _db() as con:
        last = con.execute("select max(version) from rules_versions").fetchone()[0] or 0
        r.version = last + 1
        con.execute("insert into rules_versions values (?, ?, ?, ?, ?)",
                    (r.version, datetime.now().isoformat(timespec="seconds"), user, comment, r.model_dump_json()))
    return r


def rules_history() -> list[dict]:
    with _db() as con:
        rows = con.execute("select version, saved_at, saved_by, comment from rules_versions order by version desc").fetchall()
    return [{"version": v, "saved_at": s, "saved_by": u, "comment": c} for v, s, u, c in rows]

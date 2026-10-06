#!/usr/bin/env bash
# Bootstrap a fresh environment, the way it happened in production:
#
#   1. the retailer delivers its history (simulated up to the day before the pilot)
#   2. Perisentra's first run on it: weather, warehouse, models trained on pre-pilot data, pilot design
#   3. the pilot through the real daily loop, up to yesterday: every morning Perisentra scores and publishes
#      the task list, every night the stores play the day and deliver it
#   4. readouts and the champion models on all data, today's decisions, ground-truth validation
#
# The daily loop runs on the offline DuckDB copy (BOOTSTRAP_TARGET, faster); the configured warehouse
# (PERISENTRA_DBT_TARGET, Snowflake by default) is loaded once at the end. At full scale (two years, 20 stores,
# 220 products, a 12-week pilot) expect a few hours.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PERISENTRA=(uv run --no-sync perisentra)
FERNBROOK=(uv run --no-sync fernbrook)
LOOP_TARGET="${BOOTSTRAP_TARGET:-duckdb}"
CONFIGURED_TARGET="${PERISENTRA_DBT_TARGET-}"      # restored for step 4 (empty: the value in .env)

PILOT_START=$(uv run --no-sync python -c "from perisentra.config import client_config; print(client_config()['pilot']['start'])")
HISTORY_END=$(date -d "$PILOT_START -1 day" +%F)
TODAY=$(date +%F)
step() { printf '\n== %s\n' "$*"; }

step "1. The retailer's history up to $HISTORY_END"
"${FERNBROOK[@]}" backfill --until "$HISTORY_END"

step "2. Perisentra's first run (warehouse: $LOOP_TARGET)"
export PERISENTRA_DBT_TARGET="$LOOP_TARGET"
"${PERISENTRA[@]}" fetch-external
"${PERISENTRA[@]}" ingest
"${PERISENTRA[@]}" transform
"${PERISENTRA[@]}" train --until "$HISTORY_END"
"${PERISENTRA[@]}" design-pilot

step "3. The pilot through the daily loop: $PILOT_START -> yesterday"
day="$PILOT_START"
while [[ "$day" < "$TODAY" ]]; do
  echo "-- $day"
  "${PERISENTRA[@]}" ingest
  "${PERISENTRA[@]}" transform
  "${PERISENTRA[@]}" score                    # this morning's decisions and the stores' task list
  "${FERNBROOK[@]}" advance --until "$day"   # the stores play the day and deliver it
  day=$(date -d "$day +1 day" +%F)
done

step "4. Readouts, champion models, today's decisions"
if [[ -n "$CONFIGURED_TARGET" ]]; then export PERISENTRA_DBT_TARGET="$CONFIGURED_TARGET"; else unset PERISENTRA_DBT_TARGET; fi
"${PERISENTRA[@]}" fetch-external
"${PERISENTRA[@]}" ingest
"${PERISENTRA[@]}" transform
"${PERISENTRA[@]}" backtest
"${PERISENTRA[@]}" evaluate-pilot
"${PERISENTRA[@]}" train
"${PERISENTRA[@]}" score
"${PERISENTRA[@]}" monitor
"${FERNBROOK[@]}" validate --product-data "${PERISENTRA_DATA_DIR:-$ROOT/data}"
WAREHOUSE=$(uv run --no-sync python -c "from perisentra.config import warehouse_target; print(warehouse_target())")
if [[ "$WAREHOUSE" != "duckdb" ]]; then         # keep the offline copy in step with the warehouse
  PERISENTRA_DBT_TARGET=duckdb "${PERISENTRA[@]}" ingest
  PERISENTRA_DBT_TARGET=duckdb "${PERISENTRA[@]}" transform
fi
step "Done: start the API (make api) and the dashboard (make dashboard-prod)"

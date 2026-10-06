# Perisentra — predictive decision engine for fresh retail

Perisentra forecasts demand for every product in every store, flags stock at risk of waste or stock-out,
and recommends one commercial action per product each morning: a targeted markdown, an order
adjustment, a donation, or no action. Every recommendation comes with reason codes and a confidence tier.
The stores where Perisentra is live receive it as a daily task list.

> **Data.** The retailer in this repository is simulated: Fernbrook Market, a fictional US regional grocery
> chain (20 stores in Ohio, Michigan, Indiana, Illinois and Wisconsin, 220 fresh products, prices in USD). Its
> source systems live in [`simulator/`](simulator/README.md), a separate package. Every night they deliver the day's
> ERP, POS and WMS extracts to an exchange folder, exactly as a real retailer's systems would. Perisentra only
> reads those extracts and never imports the simulator. Weather (Open-Meteo) and US public holidays (Nager.Date)
> are real.

---

## Two systems, one exchange

```
 Fernbrook Market (simulated source systems)                          Perisentra
 ───────────────────────────────────────────                          ───────────────────────────────────────────
 01:00  play out yesterday in 20 stores ──► exchange/inbound/   ──►  05:00  wait for the manifest, ingest
        ERP · POS · WMS · waste log ·        erp/ pos/ wms/ ...              ─► Snowflake raw (PUT + COPY INTO)
        promotions · footfall · labels ·     _manifests/<day>.json            ─► dbt staging → intermediate → marts
        store-app task reports                                                ─► forecasts · price response · risk
                                                                              ─► decisions + dashboard
 morning: the live stores apply the  ◄──── exchange/outbound/   ◄────        ─► the live stores' task list
 task list (~90% of items carried out)     store_tasks/tasks_<day>.csv       ─► monitoring
```

The contract between the two is only that folder: one manifest per business day (written last), source extracts in
the retailer's own formats, and a task list per morning. In production the folder is an SFTP or S3 drop.

## What Perisentra does

| Layer | Implementation |
|---|---|
| **Source systems** | POS (daily, by POS store code + UPC, with re-sent batches), ERP (stores, products with delivery schedules, assortment, price history, holiday closures, deliveries with lot expiry for ~60% of lots, open orders), WMS stock ledger and cycle counts, manual waste log, promo calendar (weekly ad, chain-wide or by state), footfall counters, markdown label log, randomized price-test log, store-app task reports |
| **Ingestion** | `perisentra ingest` waits for complete deliveries (manifests) and lands every extract in a `raw` schema with lineage columns; on Snowflake each table is staged as Parquet and loaded with `COPY INTO`. Store-app reports join the decision log |
| **Warehouse** | dbt project (`warehouse/`): staging → intermediate → marts (35 models, 49 tests). Rebuilds daily stock on hand from the ledger, flags stock-outs as **censored demand**, imputes missing expiry dates, builds store calendars from the ERP closures, the modelling panel, the lot snapshot and a data-discovery scorecard. Runs on **Snowflake** through a key-pair service user on a capped X-Small warehouse ([setup](warehouse/snowflake/README.md)); an offline DuckDB copy builds the same models for the tests and for working without a network |
| **Demand model** | One global LightGBM model (Tweedie objective) across all store-SKU pairs, direct multi-horizon (1–7 days). Thin-history items borrow strength through family / store features. **Censored-demand EM** replaces stock-out days by E[D \| D ≥ sales]. **Mondrian split-conformal** 80/95% intervals. Weather features kept per family only where an **ablation** shows they help |
| **Price response** | Hierarchical Bayesian elasticity in **PyMC** (NUTS via nutpie), SKU → family → chain, fitted on the chain's **randomized discount test**, with the demand forecast as offset, censored likelihood on stock-out days and controls for cannibalisation and residual weather. A naive historical regression is computed alongside to show the confounding bias |
| **Risk layer** | **Monte Carlo** per store-SKU: demand paths (multi-day level shock + day-level overdispersion + elasticity posterior draws) played against the actual lots on the shelf, FIFO, stickers on near-expiry lots, common random numbers across actions |
| **Decision engine** | Separate from the models; reads `configs/business_rules.yaml` (or the latest version saved from the dashboard). Picks the action with the **lowest expected waste that breaks no constraint**: max discount per family (hard limit, price endings included), unit and window margin floors, promo lock, "markdown must pay for itself". Ties go to the best margin. Adds order quantities (newsvendor on simulated paths, the ERP delivery schedule and store calendar), donations, 4-factor confidence, reason codes, and logged **exploration** (propensities) for unbiased future learning |
| **Delivery to stores** | The morning task list for the live stores (`configs/client.yaml: deployment`): stickers, tonight's order, donations. A re-run from the rules page republishes that store's items |
| **Validation** | Rolling-origin backtest vs the stores' current rule and baselines; pilot in 6 stores vs matched controls (difference-in-differences, matched-pair bootstrap CIs, measured task-list compliance) |
| **MLOps** | MLflow tracking + model registry (champion alias), Evidently drift reports, recommendation / decision / outcome log fed back into training |
| **Serving** | FastAPI (`/docs`), Next.js dashboard (light/dark) |
| **Orchestration** | Airflow 3.1: `perisentra_daily` (05:00 US Eastern, waits for the delivery), `perisentra_weekly_training`, and `fernbrook_source_systems` (01:00, the simulated retailer). Runs locally with `make airflow` (no Docker) or in Docker |

## Quick start

Requirements: Python via [uv](https://docs.astral.sh/uv/), Node 20+, ~8 GB RAM.

```bash
make install                          # Perisentra (with the Snowflake connector), the simulator, the dashboard
cp .env.example .env                  # then the one-time Snowflake setup: warehouse/snowflake/README.md
uv run perisentra check-warehouse     # account, user, role and warehouse in use
make bootstrap                        # a fresh environment: history, models, the pilot through the daily loop
```

Every day after that (Airflow does it at 01:00 and 05:00 with `make airflow`):

```bash
make deliver      # the retailer's systems deliver every business day up to yesterday
make daily        # Perisentra: weather, ingest, dbt build and tests, decisions + task list, monitoring
```

Services:

```bash
make api                              # http://localhost:8000/docs
make dashboard-prod                   # http://localhost:3000   (make dashboard: development mode)
make airflow-install && make airflow  # http://localhost:8080
make mlflow                           # http://localhost:5000
make test                             # product, simulator and DAG tests (offline)
make lint                             # ruff + dashboard type-check + ESLint
```

CLI: `uv run perisentra --help` (`check-inbound`, `fetch-external`, `ingest`, `transform`, `train`, `backtest`,
`design-pilot`, `evaluate-pilot`, `score`, `monitor`, `daily`, `check-warehouse`, `dbt-docs`, `serve`) and
`uv run fernbrook --help` (`backfill`, `advance`, `status`, `validate`).

## Docker

```bash
docker compose up --build             # API :8000, dashboard :3000, MLflow :5000 (reads the warehouse in .env)
make airflow-docker                   # + Airflow :8080 with all three DAGs
```

## Results

What a retailer can measure (backtest January–June 2026, pilot July–August 2026):

| | Result |
|---|---|
| Forecast accuracy (rolling-origin backtest, 4 origins × 4 weeks × lead 1–7) | WAPE **0.349** vs 0.370 for the stores' current rule, 0.383 for a 28-day average, 0.471 for seasonal naive |
| Interval coverage (out of sample) | 79.0% for the 80% interval, 94.6% for the 95% interval |
| Stock-out days (sales are a lower bound on demand) | forecasts fall short of what sold by 11.8%, against 24.4% for the current rule |
| Price elasticity (randomized test, 195 SKUs in 3 stores) | R-hat 1.002, 0 divergences; a naive regression on markdown history is confounded by when stores mark down (Bakery: −0.04 against 1.54) |
| Pilot, 6 stores × 8 weeks vs matched controls (DiD, 95% CI) | waste value **−25%** (−34% to −13%), markdown events **−23%** (−33% to −11%), stock-out rate **−17%**, gross margin **+2.9%** (+1.0% to +6.3%); 90% of task-list items carried out |
| An example morning (Monday 5 October 2026) vs the stores' current flat markdown rule | expected waste **−11%** ($6,276 → $5,585), margin after waste **+$3.0k**, **457** markdowns instead of 870, 1,302 order adjustments |

What only the simulator can measure (`uv run fernbrook validate`, from its ground truth):

| | Result |
|---|---|
| Bias vs true demand | −4.3% (current rule −6.6%); on chronically censored items −5.2% (current rule −7.6%) |
| Price elasticity vs the truth | family estimates within 0.12 of the true value on average (naive regression: 0.66) |
| Pilot true effect (same period replayed with the current rule) | waste value −28%, markdown events −25%, gross margin +6.5%, net sales +3.1% |

The ground truth also shows the readout's limit. The DiD recovers the waste and markdown effects (the true values
fall inside the confidence intervals) but understates the margin and sales uplift (gross margin +2.9% measured vs
+6.5% true). Eight weeks and six store pairs are not enough to separate a few percent of sales from store-level
noise and regional summer seasonality, which argues for more control stores or a longer pilot before a rollout
decision based on sales.

## Repository layout

```
src/perisentra/          the product
  ingestion/             delivery manifests, raw landing (DuckDB or Snowflake COPY INTO), store-app reports
  external/              Open-Meteo weather store and Nager.Date holidays (fetched by Perisentra itself)
  features/              feature library shared by training, backtest and scoring
  forecasting/           LightGBM model, censored-demand EM, conformal intervals
  elasticity/            hierarchical Bayesian price elasticity (PyMC)
  risk/                  Monte Carlo risk layer
  decision/              business rules, decision engine, engine inputs, what-if
  evaluation/            rolling-origin backtest, pilot design and DiD readout
  monitoring/            MLflow helpers, Evidently drift, decision & outcome log
  pipeline/              training, daily scoring and the stores' task list
  api/                   FastAPI service
  warehouse.py           warehouse reads (Snowflake, or the offline DuckDB copy)
  snowflake_io.py        Snowflake session (key-pair auth), Arrow reads, PUT + COPY INTO loads
  cli.py · config.py     `perisentra` command line, paths and settings (.env)
configs/                 client.yaml (the retailer, the pilot, live stores), business rules, model settings
warehouse/               dbt project: staging → intermediate → marts, cross-database macros, tests
  snowflake/             one-time Snowflake setup (setup.sql) and guide
dashboard/               Next.js dashboard
orchestration/airflow/   DAGs, local runner (local.sh) and Airflow image
simulator/               the simulated retailer (separate package `fernbrook`, its own config and tests)
scripts/bootstrap.sh     a fresh environment through the real daily loop
tests/                   product tests
docs/                    architecture notes and demo script
exchange/                (generated) the drop between the retailer and Perisentra
data/                    (generated) Perisentra's warehouse copy, models, serving tables, logs
```

## Plugging in a real retailer

1. Point the exchange at the retailer's drop (`PERISENTRA_EXCHANGE_DIR`) and adapt the staging models to its
   formats: they are the only place that knows source-system formats.
2. Run `perisentra ingest` and `perisentra transform`, then review the **Data & pipeline** page (history length,
   gaps, expiry coverage, censoring share). That page is the discovery phase in one screen.
3. Put the client's details, current rule and pilot in `configs/client.yaml`, and its commercial rules in
   `configs/business_rules.yaml` (or edit them in the dashboard).
4. Train, backtest against the current process, then pilot with matched control stores before rollout.

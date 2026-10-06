# Demo script (about 25 minutes)

## Before the call

```bash
uv run perisentra check-warehouse   # confirms the Snowflake connection (account, user, role, warehouse)
uv run fernbrook status             # the retailer's systems: last business day delivered
make api          # terminal 1  -> http://localhost:8000/docs
make dashboard-prod   # terminal 2  -> http://localhost:3000 (production build: faster, no dev overlay)
make airflow      # terminal 3  -> http://localhost:8080   (both systems' nightly and morning runs)
make mlflow       # terminal 4  -> http://localhost:5000   (optional)
```

With Airflow running, the retailer delivers at 01:00 and Perisentra runs at 05:00, so the dashboard shows that
morning's decisions. Without it, run `make deliver && make daily` before the call.

The figures change every morning. The ones below are from Monday 5 October 2026. On the day, pick the two
examples for section 1 the same way:

- **A markdown:** in the Overview's top waste-risk table, the first line where the current rule does something
  different.
- **A blocked line:** in Morning actions, a product with no markdown despite stock at risk.

Open these tabs in advance:

- the dashboard Overview
- one markdown item (Morning actions → pick a line with a markdown)
- the API docs (`/docs`)
- MLflow
- Airflow: the DAG list (`fernbrook_source_systems`, `perisentra_daily`), then `perisentra_daily` in Graph view
  for the latest run
- a file browser on `exchange/`
- Snowflake (Snowsight): database `PERISENTRA` with schemas `RAW`, `STAGING`, `INTERMEDIATE`, `MARTS`, and
  *Monitoring → Query History* filtered on the `TRANSFORMER` role

## Opening (2 minutes)

> "What you'll see is Perisentra running in production against a retailer, Fernbrook Market: twenty stores in the
> Midwest, 220 fresh products. Fernbrook is simulated, so no client information is in here, but it behaves like a
> real retailer. Every night its ERP, POS and warehouse systems drop the day's extracts into an exchange folder.
> Perisentra picks them up at five, rebuilds the warehouse in Snowflake, scores every product in every store, and
> sends the live stores their task list for the morning. The stores carry out about nine in ten of the items. Weather and
> US holidays come from public APIs. The architecture, the models and the decision logic are the approach I
> described in my proposal."

Show the `exchange/` folder briefly:

- `inbound/`: one folder per source system, and a manifest per business day, written last
- `outbound/store_tasks/`: this morning's task list

## 1. Overview: the morning view (3 min)

- **Headline tile.** It compares expected waste today *with the stores' current rule* (a flat 30% "manager's special"
  on units that must sell by tomorrow), not with doing nothing: −11% ($6,276 → $5,585), margin after waste +$3.0k.
- **Markdowns.** 457 targeted markdowns instead of 870 under the flat rule. The engine only discounts where a
  markdown actually saves units, and never discounts stock that would sell anyway.
- **Top waste-risk table.** The first line, Italian Sausage at Bloomington Kirkwood, is one where the engine agrees
  with the current rule: a 30% sticker, and the next order cut from 11 to 3. The second line shows the difference:
  - Sandwich White Loaf at Grand Rapids Eastown: 84 loaves from this morning's in-store bake must sell today.
  - The current rule never stickers same-day bakery.
  - Perisentra stickers them at 20% ($4.99 → $3.99), cutting expected waste from $53 to $25.
  - Deeper stickers would clear more loaves but bring in less money than they save. A markdown must pay for itself,
    because the stock is already bought.
- **Constraints are respected.** Open *Morning actions* and search for "Thick-Cut Bacon" at Naperville Riverwalk.
  24 packs expire within three days, about $32 of waste at full price, yet it gets *no* markdown. Every action
  evaluated is listed with the rule that blocked it:
  - stickers of 9–30% would cut waste but bring in less money than full price (a markdown must pay for itself)
  - 41% and 50% break the margin floor over the markdown window

  The engine cuts the next order from 8 to 0 instead.
- **Order adjustments and stock-out alerts.** The same engine corrects 1,302 orders, raises 188 stock-out alerts
  and proposes 110 donations.
- **Chain trend.** The shaded area is the 8-week pilot in 6 stores.

## 2. Morning actions → one product (6 min)

1. Filter on a store and turn on "only lines with an action". Each line shows the action, the price change, the
   waste risk, the next order and the confidence tier.
2. Open a markdown line:
   - **Why**: reason codes in plain language (units expiring, chance of waste, expected lift, waste avoided).
   - **Comparison** with the current rule and with doing nothing: waste and *margin after waste*.
   - **Forecast chart**: stock-out days are marked as censored demand, so they never count as low demand.
     The forecast comes with 80% and 95% intervals.
   - **Stock by expiry**, and the **Monte Carlo distribution** of units wasted.
   - **Every action evaluated**, and which business rule blocked which one.
   - **What-if**: move the discount slider and simulate (2,000 paths), then show a scenario that breaks a margin floor.
   - **Store decision**: Apply / Override / Reject. It is logged and feeds retraining. In the live stores the store
     app reports the same thing back every night with the delivery.

## 3. Price response: why past markdowns can't be trusted (3 min)

- Past markdowns all happened the day before expiry, on stock left over *because* demand was weak. A regression
  on that history makes discounts look ineffective. Point to bakery: the naive estimate is close to zero, against
  about 1.5 from the test.
- A small randomized discount test in 3 stores gives clean price variation. The hierarchical Bayesian model (PyMC)
  shares strength SKU → family → chain and handles stock-outs as censored.
- The precision chart shows how tightly each tested SKU is measured. The SKUs outside the test borrow their
  family's distribution.

## 4. Validation (4 min)

- **Backtest**: rolling origins, each retrained on the data before it. WAPE 0.349 vs 0.370 for the stores' current
  rule (0.383 for a 28-day average). The 80/95% intervals cover 79.0% / 94.6%. On stock-out days sales are only a
  lower bound on demand. There, Perisentra's forecasts fall short of what sold by 11.8%, against 24.4% for the
  current rule, which learns from capped sales.
- **Pilot**: 6 stores against matched control stores, difference-in-differences with confidence intervals.
  Waste value −25%, markdown events −23%, stock-out rate −17%, gross margin +2.9%, and 90% of task-list items
  carried out by the stores.
- **What only a simulated retailer can show** (`simulator/var/reports/validation.md`). The simulator knows the
  true demand and the true effect, because it replays the pilot period with the old rule.
  - Family elasticities land within 0.12 of the true values on average (naive regression: 0.66).
  - On chronically censored items, the bias against true demand is −5.2%, against −7.6% for the store rule.
  - The pilot readout has the right direction on all six metrics, and the true waste and markdown effects (−28%,
    −25%) fall inside the CI. The margin uplift is understated (+2.9% vs +6.5% true).

  Say so openly: eight weeks and six pairs cannot separate a few percent of sales from store noise and regional
  summer seasonality. That is why controls are matched on last year's seasonal profile, and why you'd use more
  control stores or a longer pilot before rollout.

## 5. Models, monitoring, data and operations (4 min)

- **Models**:
  - one global LightGBM (Tweedie) with censored-demand EM and conformal intervals
  - the weather ablation result: weather is kept only where it helps
  - the MLflow registry with its champion alias
- **Monitoring**: Evidently drift report, live forecast accuracy from the decision log, and the exploration share
  (logged propensities).
- **Data & pipeline**:
  - the discovery scorecard: share of lots with an expiry date, POS duplicates removed, stock-out share, sensor gaps
  - dbt lineage and tests
  - pipeline runs
- **Airflow.** Two DAGs, two systems:
  - `fernbrook_source_systems` at 01:00 is the retailer's side: it delivers yesterday.
  - `perisentra_daily` at 05:00 waits for that delivery's manifest, then runs fetch weather and holidays → ingest →
    dbt build and test → score → monitor.

  A failing dbt test stops the run before anything is published. Open the dbt task log to show the 35 models and
  49 tests passing on the Snowflake adapter.
- **Snowflake**: the `RAW` tables loaded by `COPY INTO` and the dbt marts (`MARTS.FCT_STORE_SKU_DAILY`, 2.8 M rows).
  The query history shows the service user running the pipeline on an X-Small warehouse that suspends after
  60 seconds idle.

## 6. Business rules: change without retraining (2 min)

Change a margin floor or the max discount for a family, save it as a new version, then click "Apply without
retraining" for a store. Only the decision layer re-runs, in a few seconds. If the store is live, its items in
this morning's task list are replaced. The footer shows the rules versions behind the decisions on screen.

## Close: how this maps to your customers (2 min)

1. Fixed-price discovery: what the customer's systems hold. The Data & pipeline page is that deliverable.
2. Define the decision: allowed actions, success metrics, rules that can never be broken (this is the YAML / rules page).
3. Pipeline with rebuilt stock and censored demand.
4. Forecast and risk layer.
5. Decision layer, separate from the models.
6. Backtest against the current process, then a pilot with control stores, with every decision logged.

## Likely questions

- **"Is this the client's system?"** No. It is a rebuild of the same approach running against a simulated retailer.
  No client code or data is in it.
- **"What would change with a real retailer?"** The exchange folder becomes their SFTP or S3 drop, and the staging
  models are adapted to their file formats. Everything downstream stays as it is.
- **"How do you avoid learning from biased past actions?"** Randomized tests plus logged exploration with
  propensities, and the engine never treats its own past markdowns as clean evidence.
- **"What if a customer has no expiry dates?"** Expiry is imputed from delivery date and shelf life, flagged, and
  confidence drops for those products (see the reason codes).
- **"What if a delivery is late?"** The morning run waits for the manifest (up to six hours) and publishes nothing
  until the delivery is complete and the dbt tests pass.
- **"Snowflake?"** The warehouse runs on Snowflake. Ingestion stages the extracts and loads them with `COPY INTO`,
  dbt builds the 35 models and 49 tests there, and the models read the marts from Snowflake. One setting switches
  to a local DuckDB copy, which produces identical tables and recommendations (useful offline).
- **"How long to adapt to a new retailer?"** Staging models are the only source-specific code. Rules live in config.

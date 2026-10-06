# Architecture and method notes

## 0. Two systems and the exchange between them

Perisentra and the retailer are separate systems that share one folder (`exchange/`, in production an SFTP or
S3 drop). The retailer here is simulated (`simulator/`, package `fernbrook`), and Perisentra never imports it.

- **Inbound.** Every night the retailer's systems deliver the previous business day: event extracts (POS, WMS
  movements, deliveries, waste log, markdown labels, footfall, store-app task reports) and fresh master files
  (stores, products with delivery schedules, assortment, prices, closures, promotions, open orders). Each file is
  written atomically, and the day's manifest (`inbound/_manifests/<day>.json`, with the files and row counts) is
  written last. A delivery without a manifest is incomplete. The morning run waits for it, and ingestion skips its
  files.
- **Outbound.** After scoring, Perisentra writes the morning task list for the live stores
  (`outbound/store_tasks/tasks_<day>.csv`: sticker, window, new price, tonight's order, donations). A re-run for one
  store from the rules page replaces only that store's items.
- **Back again.** That night the stores play the day. In the live stores about 90% of the items are carried out
  (`stores_behaviour.task_compliance`); the others follow the store's own rule. The store app reports each item as
  `ACCEPTED` or `NOT_APPLIED`. Perisentra imports those reports into its decision log once per file, and they feed
  the pilot readout's compliance figure and retraining.

The simulator's world is reproducible. Every random draw comes from a seeded stream (common random numbers), and
its state is saved after every delivered day, so it can resume where it stopped. On the first morning with a task
list it also keeps a checkpoint, which lets its validation replay the period under the old rule and compare the
true effect with Perisentra's own readout. The ground truth (true demand, true elasticities, true effects) stays in
`simulator/var/` and never reaches the exchange.

`scripts/bootstrap.sh` builds a fresh environment the way it would happen in production:

1. the retailer delivers its history
2. Perisentra trains and designs the pilot
3. the pilot runs through the real daily loop (score → task list → the stores play the day → delivery)
4. the readouts and the simulator's validation report

## 1. Data and the warehouse

**Sources are kept separate on purpose.** Each folder in `exchange/inbound/` is one system with its own keys and
quirks. POS is keyed by POS store code and UPC and re-sends whole batches after outages. Deliveries carry a lot
expiry date only for expiry-tracked products. The waste log uses free-text reasons. Footfall sensors have
outages. The dbt staging layer is the only place that knows those formats.

**Store calendars and delivery schedules come from the ERP.** Holiday closures (`erp/store_closures.csv`) and each
store's Sunday opening define its open days. Each product's delivery schedule (`daily`, `mon_wed_fri`,
`in_store_bake`) defines when the next order arrives and how many days it must cover.

**Stock on hand is rebuilt, not read.** `int_stock_daily` takes the cumulative sum of the WMS ledger (opening
balance, receipts, sales, write-offs, cycle-count adjustments). Unrecorded shrink and missed waste entries make
book stock drift until the next count; `mart_source_coverage` reports the count variance.

**Stock-outs are censored demand.** A day is censored when the shelf was empty right after the day's sales
(`stock_after_sales <= 0`) or had nothing to sell (`opening + receipts <= 0`). On those days sales are a lower bound
on demand. Days that sold out exactly at demand cannot be told apart from real stock-outs and are treated as
censored, which is the conservative choice.

**Expiry dates are imputed where missing** (`delivery date + specified shelf life - 1`) and flagged. The flag
lowers the confidence tier of the affected recommendations.

**The warehouse is Snowflake.** Ingestion stages each extract as Parquet in its table stage and runs
`COPY INTO raw.*`. dbt builds staging → intermediate → marts there, with tests, and the models read the marts back
through Arrow. Everything runs as a key-pair service user (no password) on an X-Small warehouse that suspends after
60 seconds idle and is capped by a resource monitor (`warehouse/snowflake/`).

The SQL uses dbt cross-database macros (`macros/cross_db.sql`), so the same models also build an offline DuckDB
copy in `data/warehouse/`. The tests always use it, and it serves as a fallback without network.
`PERISENTRA_DBT_TARGET` (in `.env`) selects the warehouse for ingestion, dbt and the Python code alike. Both
warehouses produce identical tables and recommendations.

## 2. Demand forecasting

- **One global model** (LightGBM, Tweedie objective) across all store-SKU pairs. Categorical store, family,
  subfamily, format and region, plus family-store level statistics, let a product with three weeks of history
  borrow from similar products.
- **Direct multi-horizon.** Each training row gets a random lead time k ∈ 1..7. History features are computed as of
  the origin (day − k), and known-in-advance features (calendar, promotions, weather) at the target day. One model
  serves all horizons with no recursion.
- **Censored-demand EM.** First fit on uncensored days. Then replace each stock-out day by
  `E[D | D ≥ sales]` under a negative binomial with the model's mean and the family's dispersion
  (closed form: `μ · P(D' ≥ s−1) / P(D ≥ s)` with `D' ~ NB(k+1, p)`), and refit.
- **Markdown days stay in training** with the sticker discount and its stock coverage as features. Predicting with
  those set to zero gives the baseline demand at regular price, without the selection bias of dropping those days.
- **Weather ablation.** The model is trained with and without weather features on a sample, and weather is kept
  only for families where it lowers WAPE (`model.yaml: weather_ablation.min_wape_gain_pct`).
- **Uncertainty.** Mondrian split-conformal intervals by family × volume bucket, with signed scores normalised by
  `(ŷ+1)^(p/2)`. For the Monte Carlo layer, the negative-binomial dispersion and a multi-day level shock are
  estimated per family on the calibration window.

## 3. Price response

Historical markdowns are confounded: they happen on stock left over *because* demand was weak, so a regression
of sales on price over history underestimates the price response (the dashboard shows the naive estimate next to the
Bayesian one). The model is therefore fitted on a **small randomized discount test** (3 stores, 6 weeks, a share of
store-SKU-days given a random whole-shelf discount):

```
D ~ NegBinomial(mu, alpha_family);  sales = min(D, available)          (stock-out days: P(D ≥ sales))
log mu = log(baseline forecast) + a_family − e_sku · log(1 − discount) + b_sib · sibling_promo + b_temp · temp_anomaly
e_sku ~ Normal(e_family, sigma_sku);  e_family ~ Normal(mu_e, tau)
```

The censored term is computed exactly as `log(1 − Σ_{d<s} pmf(d))` on small integer grids bucketed by sales level,
which is much faster in NUTS than the incomplete-beta CDF. SKUs outside the test get draws from their family's
predictive distribution. The engine logs the propensity of each decision, and a small exploration rate randomises
between near-equivalent actions, so later refits can learn from live decisions without confounding.

## 4. Risk layer and decision engine

For each store-SKU and each candidate action (no action, or a sticker of d% on lots expiring within w days), the
engine simulates 600 demand paths over 7 days against the lots actually on the shelf:

- base demand `Poisson(μ_h · e^η · G_h)`, with η a path-level shock and G day-level overdispersion
- extra demand from a sticker `Poisson(λ · ((1−d)^−e − 1))`, which only buys stickered units; e is drawn from the posterior
- stickered (oldest) units sell first, FIFO by expiry; unsold units on their expiry day are waste
- the same base-demand draws are used for every action (common random numbers)

**Selection.**

1. Drop actions that break a rule: promo lock, max discount, price endings, unit margin floor, margin floor over
   the markdown window, and "a markdown must pay for itself" (expected revenue must rise, because the stock is
   already bought).
2. Among the rest, take the lowest expected waste.
3. Within a tolerance of that, take the best margin.
4. A markdown must save at least `min_waste_gain`.

**Secondary actions.**
- **Order quantity** for the next delivery: the service-level quantile of simulated `demand over cover − stock left at
  delivery − units already on order for that delivery`. Several evenings can feed the same delivery (for example
  Monday, Wednesday and Friday deliveries), so open orders are always netted out.
- **Donation** of units still unsold at close.

**Confidence tier.** It combines four factors: forecast interval width, history length, expiry-data quality, and
price-response evidence (tested SKU vs borrowed from family).

The engine also evaluates the store's current rule (a flat sticker in the last days of shelf life) for every product, so
each saving is reported against today's process, not against doing nothing.

## 5. Validation

- **Rolling-origin backtest** (`perisentra backtest`). For each origin, the model is retrained on data before it and
  every lead time is evaluated over the following four weeks. It is compared with the stores' current rule, seasonal
  naive and a 28-day average. Accuracy uses uncensored days only. On stock-out days sales are only a lower bound on
  demand, so the report adds how far each method falls short of what sold on those days.
- **Pilot** (`perisentra design-pilot`, `perisentra evaluate-pilot`). Six treatment stores are stratified by format,
  and each is matched to the most similar remaining store of the same format. The match uses pre-period sales,
  waste rate, markdown rate and last summer's seasonal profile. That last term protects parallel trends against
  regional summer effects: college towns empty out and lake towns fill up.

  During the pilot the treatment stores receive the daily task list like any live store. Effects are
  difference-in-differences on weekly store outcomes from the warehouse, with matched-pair bootstrap confidence
  intervals. Task-list compliance is measured from the store-app reports.
- **Ground truth** (`fernbrook validate`, simulator only). The simulator compares Perisentra's outputs with what it
  knows and a retailer never does:
  - backtest forecasts against true demand, including chronically censored items
  - estimated elasticities against the true ones
  - the pilot readout against the true effect: the same period replayed from the checkpoint with the old rule and
    identical random numbers, measured with the warehouse's waste definition

  The report is `simulator/var/reports/validation.md`.

## 6. Operations

- **Airflow.** Three DAGs:
  - `perisentra_daily` (05:00 US Eastern): wait for yesterday's manifest (up to six hours) → fetch weather/holidays →
    ingest → dbt build with tests → score and publish the task list → monitor
  - `perisentra_weekly_training`: ingest → dbt → train and register → backtest, pilot readout
  - `fernbrook_source_systems` (01:00): the simulated retailer delivers yesterday. It is not part of Perisentra.

  A failing dbt test stops the run before anything is published. Each task calls one CLI command and inherits the
  worker's environment, so the DAGs run against the warehouse selected in `.env` (Snowflake by default). `max_active_runs=1` keeps two runs from
  rewriting the warehouse at once. `make airflow` runs Airflow locally (scheduler, DAG processor, triggerer, UI on
  :8080); `make airflow-docker` runs the same DAGs in a container.
- **MLflow.** Experiments `perisentra-demand` and `perisentra-elasticity`, with registered models carrying a
  `champion` alias.
- **Evidently.** Drift of key features and of predictions (`data/reports/drift/`).
- **Feedback.** Store-app reports from the exchange and decisions entered in the dashboard go to the decision log
  (SQLite app DB). `recommendation_log` and `store_decisions` are copied into `raw.app_*` at each ingestion.
- **Rules.** Business rules are versioned in the app DB. Each recommendation stores the rules version and model
  versions that produced it.

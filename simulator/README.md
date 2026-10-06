# Fernbrook Market source systems (simulated)

Fernbrook Market is a fictional US regional grocery chain: 20 stores in Ohio, Michigan, Indiana, Illinois and
Wisconsin, 220 fresh products. This package simulates the chain and the systems a decision product would connect
to. Perisentra never imports it. The two only exchange files, exactly as with a real retailer:

```
exchange/
  inbound/      what the retailer delivers every night (this simulator writes it, Perisentra reads it)
    erp/ pos/ wms/ quality/ marketing/ footfall/ pricing/ storeapp/
    _manifests/<business date>.json      written last: the day's delivery is complete
  outbound/     what Perisentra sends back (Perisentra writes it, this simulator reads it)
    store_tasks/tasks_<date>.csv         the stores' task list for that morning
```

## The world

- **Demand.** Each store × product has a hidden demand process: weekday and seasonal patterns, real weather and
  public holidays (Open-Meteo, Nager.Date), promotions and the weekly ad, cannibalisation, regional summer effects,
  competitor openings, a persistent demand shock and Gamma-Poisson day-to-day noise.
- **Stock.** It is tracked lot by lot, with expiry dates. Sales deplete the oldest lots first, unsold units expire,
  some are damaged, and some shrink goes unrecorded until a cycle count finds it.
- **Store behaviour.**
  - Without a task list, stores follow their current rule: a flat 30% "manager's special" on units that must sell by
    tomorrow, and orders from a same-weekday and 2-week sales average.
  - With a task list, they apply about 90% of its items (`stores_behaviour.task_compliance`) and report each item
    through the store app.
- **Source systems.** Each system has its own keys and quirks: POS by store code and UPC with re-sent batches, lot
  expiry only for expiry-tracked products, free-text waste reasons, door-counter outages.
- **Ground truth.** True demand, true price elasticities and the true effect of any change stay in `var/truth/`.

Every day draws the same random numbers whatever the stores decide (common random numbers), so a period can be
replayed with a different course of action and the difference is the true effect.

## Commands

```bash
uv run fernbrook backfill --until 2026-07-05   # build and deliver the history once
uv run fernbrook advance                       # deliver every missing business day up to yesterday (nightly)
uv run fernbrook status                        # next business day, days behind, last delivery
uv run fernbrook validate                      # grade the consumer's outputs against the ground truth
```

`advance` saves the world after every day, so an interrupted run resumes where it stopped. In production this
role is played by the retailer's own systems. Here, the Airflow DAG `fernbrook_source_systems` runs it every night
at 01:00.

## Ground-truth validation

`fernbrook validate` reads the consumer's published outputs (backtest predictions, elasticity estimates, pilot
readout) and writes `var/reports/validation.md`:
- forecast bias against true demand
- estimated vs true price elasticities
- the measured pilot effect vs its true effect

None of this can be measured with a real retailer, which is why it lives here and not in the product.

## Configuration

`config/world.yaml` holds everything: stores, product families and their true demand parameters, the stores'
current rule, the spring 2026 price test, and source-system error rates. Paths can be overridden with
`FERNBROOK_CONFIG`, `FERNBROOK_VAR` and `FERNBROOK_EXCHANGE_DIR`.

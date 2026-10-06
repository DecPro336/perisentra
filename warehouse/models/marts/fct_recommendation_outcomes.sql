-- Closes the loop: every logged recommendation joined to what happened next (sales that day, waste and
-- markdown units over the following 7 days). Feeds monitoring and retraining.
with recs as (
    select
        cast(as_of_date as date)                        as as_of_date,
        source,
        cast(store_id as integer)                       as store_id,
        cast(sku_id as integer)                         as sku_id,
        action,
        cast(discount_pct as double)                    as discount_pct,
        cast(markdown_window_days as integer)           as markdown_window_days,
        order_action,
        cast(order_recommended as double)               as order_recommended,
        cast(expected_waste_value as double)            as expected_waste_value,
        cast(baseline_waste_value as double)            as baseline_waste_value,
        cast(p_waste as double)                         as p_waste,
        cast(p_stockout as double)                      as p_stockout,
        cast(forecast_today as double)                  as forecast_today,
        lower(cast(explored as varchar)) in ('1', 'true') as explored,
        cast(propensity as double)                      as propensity,
        confidence_tier,
        demand_model,
        cast(rules_version as integer)                  as rules_version
    from {{ source('raw', 'app_recommendation_log') }}
),
outcomes as (
    select
        r.as_of_date, r.source, r.store_id, r.sku_id,
        max(case when f.date = r.as_of_date then f.units_sold end)                       as units_sold_on_day,
        max(case when f.date = r.as_of_date and f.is_censored then 1 else 0 end) = 1      as stockout_on_day,
        sum(f.waste_expired + f.waste_damaged)                                           as waste_units_7d,
        sum(f.waste_value)                                                               as waste_value_7d,
        sum(f.units_markdown)                                                            as markdown_units_7d,
        sum(f.net_sales)                                                                 as net_sales_7d
    from recs r
    join {{ ref('fct_store_sku_daily') }} f
      on f.store_id = r.store_id and f.sku_id = r.sku_id
     and f.date between r.as_of_date and {{ add_days('r.as_of_date', 6) }}
    group by 1, 2, 3, 4
)
select
    r.*,
    o.units_sold_on_day, o.stockout_on_day, o.waste_units_7d, o.waste_value_7d, o.markdown_units_7d, o.net_sales_7d
from recs r
left join outcomes o
  on o.as_of_date = r.as_of_date and o.source = r.source and o.store_id = r.store_id and o.sku_id = r.sku_id

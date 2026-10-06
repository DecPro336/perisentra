-- Weekly business KPIs per store and family (waste, markdowns, margin, availability).
select
    f.store_id,
    f.family,
    {{ week_start('f.date') }}                                              as week_start,
    count(*)                                                                as sku_days,
    sum(f.units_sold)                                                       as units_sold,
    sum(f.net_sales)                                                        as net_sales,
    sum(f.discount_given)                                                   as discount_given,
    sum(f.units_markdown)                                                   as units_markdown,
    sum(case when f.is_markdown then 1 else 0 end)                          as markdown_events,
    sum(f.waste_expired + f.waste_damaged)                                  as waste_units,
    sum(f.waste_value)                                                      as waste_value,
    sum(f.donated)                                                          as donated_units,
    sum(f.units_sold * p.unit_cost)                                         as cogs,
    sum(f.net_sales) - sum(f.units_sold * p.unit_cost)                      as gross_margin,
    avg(case when f.is_censored then cast(1 as double) else 0 end)                      as stockout_rate
from {{ ref('fct_store_sku_daily') }} f
join {{ ref('stg_products') }} p on p.sku_id = f.sku_id
where f.is_open and f.is_in_season
group by 1, 2, 3

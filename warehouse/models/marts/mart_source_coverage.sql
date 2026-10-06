-- Data-discovery scorecard: what each source system really contains.
with pos_raw as (select count(*) as n from {{ source('raw', 'pos_daily_sales') }}),
pos as (select count(*) as n,
               sum(case when store_id is null then 1 else 0 end) as unmapped_store,
               sum(case when sku_id is null then 1 else 0 end) as unmapped_upc,
               min(sale_date) as d0, max(sale_date) as d1
        from {{ ref('stg_pos_sales') }}),
deliv as (select count(*) as n, avg(case when expiry_date is not null then cast(1 as double) else 0 end) as expiry_share
          from {{ ref('stg_deliveries') }} where qty_received > 0),
prod as (select avg(case when is_expiry_tracked then cast(1 as double) else 0 end) as tracked from {{ ref('stg_products') }}),
counts as (select count(*) as n, avg(abs(count_variance)) as mean_abs_var,
                  avg(case when count_variance <> 0 then cast(1 as double) else 0 end) as share_var
           from {{ ref('stg_cycle_counts') }}),
waste as (select count(*) as n, count(distinct reason_raw) as raw_labels,
                 avg(case when is_value_imputed then cast(1 as double) else 0 end) as imputed
          from {{ ref('stg_waste_log') }}),
foot as (select count(*) as n from {{ ref('stg_footfall') }}),
foot_exp as (select count(*) as n from {{ ref('int_store_calendar') }} sc
             join {{ ref('int_bounds') }} b on sc.date_day between b.data_start and b.data_end where sc.is_open),
promo as (select count(*) as n, avg(case when scope_type = 'REGIONAL' then cast(1 as double) else 0 end) as regional,
                 avg(case when in_flyer then cast(1 as double) else 0 end) as flyer from {{ ref('stg_promotions') }}),
wx as (select weather_source, count(*) as n from {{ ref('stg_weather') }} group by 1),
panel as (select count(*) as n,
                 avg(case when is_censored then cast(1 as double) else 0 end) as censored,
                 avg(case when stockout_type = 'FULL_DAY' then cast(1 as double) else 0 end) as full_day,
                 avg(case when is_markdown then cast(1 as double) else 0 end) as markdown
          from {{ ref('fct_store_sku_daily') }} where is_open and is_in_season),
pt as (select count(*) as n, count(distinct store_id) as stores,
              avg(case when assigned_discount_pct > 0 then cast(1 as double) else 0 end) as treated
       from {{ ref('stg_price_tests') }})

select 'POS sales' as source, 'raw rows' as metric, cast(pos_raw.n as double) as value, 'rows' as unit from pos_raw
union all select 'POS sales', 'duplicate rows removed (re-sent batches)', cast(pos_raw.n - pos.n as double), 'rows' from pos_raw, pos
union all select 'POS sales', 'unmapped store codes', cast(pos.unmapped_store as double), 'rows' from pos
union all select 'POS sales', 'unmapped UPCs', cast(pos.unmapped_upc as double), 'rows' from pos
union all select 'POS sales', 'history length', cast(pos.d1 - pos.d0 + 1 as double), 'days' from pos
union all select 'ERP deliveries', 'lots received', cast(deliv.n as double), 'rows' from deliv
union all select 'ERP deliveries', 'lots with an expiry date', deliv.expiry_share, 'share' from deliv
union all select 'ERP products', 'SKUs with expiry tracking', prod.tracked, 'share' from prod
union all select 'WMS cycle counts', 'counts', cast(counts.n as double), 'rows' from counts
union all select 'WMS cycle counts', 'counts with a book variance', counts.share_var, 'share' from counts
union all select 'WMS cycle counts', 'mean absolute variance', counts.mean_abs_var, 'units' from counts
union all select 'Waste log', 'entries', cast(waste.n as double), 'rows' from waste
union all select 'Waste log', 'distinct free-text reasons (mapped to 3)', cast(waste.raw_labels as double), 'labels' from waste
union all select 'Waste log', 'value missing, imputed at cost', waste.imputed, 'share' from waste
union all select 'Footfall counters', 'store-days received', cast(foot.n as double), 'rows' from foot
union all select 'Footfall counters', 'store-days missing (sensor outages)', 1 - cast(foot.n as double) / nullif(foot_exp.n, 0), 'share' from foot, foot_exp
union all select 'Promo calendar', 'promotions', cast(promo.n as double), 'rows' from promo
union all select 'Promo calendar', 'state-level promotions', promo.regional, 'share' from promo
union all select 'Promo calendar', 'promotions in the weekly ad', promo.flyer, 'share' from promo
union all select 'Weather (Open-Meteo)', 'location-days from ' || wx.weather_source, cast(wx.n as double), 'rows' from wx
union all select 'Price test', 'store-SKU-days in randomized test', cast(pt.n as double), 'rows' from pt
union all select 'Price test', 'share assigned a discount', pt.treated, 'share' from pt
union all select 'Modelling panel', 'open store-SKU-days', cast(panel.n as double), 'rows' from panel
union all select 'Modelling panel', 'censored days (stock-outs)', panel.censored, 'share' from panel
union all select 'Modelling panel', 'full-day stock-outs', panel.full_day, 'share' from panel
union all select 'Modelling panel', 'days with markdown stickers', panel.markdown, 'share' from panel

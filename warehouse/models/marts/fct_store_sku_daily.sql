-- The modelling panel: one row per store x SKU x day while listed, with sales, prices, stock,
-- censoring flags, waste, promotions, footfall and weather. Stock-outs are flagged as censored
-- demand (sales are a lower bound), never treated as zero demand.
with base as (
    select
        sc.store_id,
        sc.sku_id,
        sc.date_day                                         as date,
        sc.is_open,
        sc.is_in_season,
        coalesce(s.units_sold, 0)                           as units_sold,
        coalesce(s.units_markdown, 0)                       as units_markdown,
        coalesce(s.units_promo, 0)                          as units_promo,
        coalesce(s.gross_sales, 0)                          as gross_sales,
        coalesce(s.discount_given, 0)                       as discount_given,
        coalesce(s.net_sales, 0)                            as net_sales,
        ph.regular_price,
        coalesce(pr.promo_pct, 0)                           as promo_pct,
        coalesce(pr.in_flyer, false)                        as in_flyer,
        pr.promo_id,
        coalesce(md.markdown_pct, 0)                        as markdown_pct,
        coalesce(md.units_labelled, 0)                      as markdown_units_labelled,
        md.label_source                                     as markdown_source,
        stk.opening_stock,
        stk.receipts,
        stk.write_offs,
        stk.adjustments,
        stk.closing_stock,
        stk.stock_after_sales,
        coalesce(w.waste_expired, 0)                        as waste_expired,
        coalesce(w.waste_damaged, 0)                        as waste_damaged,
        coalesce(w.donated, 0)                              as donated,
        coalesce(w.waste_value, 0)                          as waste_value,
        ff.entries                                          as footfall,
        pt.assigned_discount_pct                            as test_discount_pct
    from {{ ref('int_series_calendar') }} sc
    left join {{ ref('int_sales_daily') }} s
      on s.store_id = sc.store_id and s.sku_id = sc.sku_id and s.sale_date = sc.date_day
    left join {{ ref('stg_price_history') }} ph
      on ph.sku_id = sc.sku_id and sc.date_day between ph.valid_from and ph.valid_to
    left join {{ ref('int_promo_daily') }} pr
      on pr.store_id = sc.store_id and pr.sku_id = sc.sku_id and pr.date_day = sc.date_day
    left join {{ ref('int_markdowns_daily') }} md
      on md.store_id = sc.store_id and md.sku_id = sc.sku_id and md.date_day = sc.date_day
    left join {{ ref('int_stock_daily') }} stk
      on stk.store_id = sc.store_id and stk.sku_id = sc.sku_id and stk.date_day = sc.date_day
    left join {{ ref('int_waste_daily') }} w
      on w.store_id = sc.store_id and w.sku_id = sc.sku_id and w.date_day = sc.date_day
    left join {{ ref('stg_footfall') }} ff
      on ff.store_id = sc.store_id and ff.count_date = sc.date_day
    left join {{ ref('stg_price_tests') }} pt
      on pt.store_id = sc.store_id and pt.sku_id = sc.sku_id and pt.test_date = sc.date_day
),
enriched as (
    select
        b.*,
        p.family,
        p.subfamily,
        b.promo_pct > 0                                                     as is_promo,
        b.markdown_pct > 0 and b.markdown_units_labelled > 0                as is_markdown,
        b.test_discount_pct is not null                                     as in_price_test,
        case when b.gross_sales > 0 then b.net_sales / nullif(b.gross_sales, 0)
             when b.promo_pct > 0 then 1 - b.promo_pct
             else 1.0 end                                                   as price_ratio,
        -- censored demand: the shelf emptied during the day, or there was nothing to sell all day
        b.is_open and b.is_in_season and (
            (b.units_sold > 0 and b.stock_after_sales <= 0)
            or (b.opening_stock + b.receipts <= 0)
        )                                                                   as is_censored,
        case
            when not (b.is_open and b.is_in_season) then null
            when b.opening_stock + b.receipts <= 0 then 'FULL_DAY'
            when b.units_sold > 0 and b.stock_after_sales <= 0 then 'INTRADAY'
        end                                                                 as stockout_type
    from base b
    join {{ ref('stg_products') }} p on p.sku_id = b.sku_id
)

select
    e.*,
    -- cannibalisation pressure: share of the other SKUs in the same store-subfamily on promotion
    case when count(*) over (partition by e.store_id, e.subfamily, e.date) > 1
         then (sum(case when e.is_promo then 1 else 0 end) over (partition by e.store_id, e.subfamily, e.date)
               - case when e.is_promo then 1 else 0 end) * cast(1 as double)
              / nullif(count(*) over (partition by e.store_id, e.subfamily, e.date) - 1, 0)
         else 0 end                                                         as sibling_promo_share,
    wx.temp_max,
    wx.temp_min,
    wx.precipitation,
    wx.weather_source
from enriched e
left join {{ ref('stg_weather') }} wx on wx.store_id = e.store_id and wx.weather_date = e.date

-- Known-in-advance covariates for the forecast horizon (opening hours, promos, flyers, weather forecast).
with b as (select * from {{ ref('int_bounds') }}),
future as (
    select a.store_id, a.sku_id, c.date_day as date, sc.is_open,
           (p.season_months is null
             or (',' || p.season_months || ',') like ('%,' || cast(c.month as varchar) || ',%')) as is_in_season,
           p.family, p.subfamily
    from {{ ref('stg_assortment') }} a
    join {{ ref('stg_products') }} p on p.sku_id = a.sku_id
    join {{ ref('int_calendar') }} c
      on c.date_day >= a.listed_from and (a.listed_to is null or c.date_day <= a.listed_to)
    join b on c.date_day > b.data_end and c.date_day <= b.horizon_end
    join {{ ref('int_store_calendar') }} sc on sc.store_id = a.store_id and sc.date_day = c.date_day
),
promo as (
    select f.*,
           coalesce(pr.promo_pct, 0)       as promo_pct,
           coalesce(pr.in_flyer, false)    as in_flyer,
           coalesce(pr.promo_pct, 0) > 0   as is_promo
    from future f
    left join {{ ref('int_promo_daily') }} pr
      on pr.store_id = f.store_id and pr.sku_id = f.sku_id and pr.date_day = f.date
)
select
    p.*,
    case when count(*) over (partition by p.store_id, p.subfamily, p.date) > 1
         then (sum(case when p.is_promo then 1 else 0 end) over (partition by p.store_id, p.subfamily, p.date)
               - case when p.is_promo then 1 else 0 end) * cast(1 as double)
              / nullif(count(*) over (partition by p.store_id, p.subfamily, p.date) - 1, 0)
         else 0 end as sibling_promo_share,
    ph.regular_price,
    wx.temp_max, wx.temp_min, wx.precipitation, wx.weather_source
from promo p
left join {{ ref('stg_price_history') }} ph on ph.sku_id = p.sku_id and p.date between ph.valid_from and ph.valid_to
left join {{ ref('stg_weather') }} wx on wx.store_id = p.store_id and wx.weather_date = p.date

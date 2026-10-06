-- One row per store x SKU x day while the SKU is listed in the store (data window only).
select
    a.store_id,
    a.sku_id,
    c.date_day,
    sc.is_open,
    (p.season_months is null
        or (',' || p.season_months || ',') like ('%,' || cast(c.month as varchar) || ',%')) as is_in_season
from {{ ref('stg_assortment') }} a
join {{ ref('stg_products') }} p on p.sku_id = a.sku_id
join {{ ref('int_calendar') }} c
  on c.date_day >= a.listed_from and (a.listed_to is null or c.date_day <= a.listed_to)
join {{ ref('int_bounds') }} b on c.date_day between b.data_start and b.data_end
join {{ ref('int_store_calendar') }} sc on sc.store_id = a.store_id and sc.date_day = c.date_day

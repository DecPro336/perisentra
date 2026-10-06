select
    pc.promo_id,
    p.sku_id,
    lpad(cast(pc.upc as varchar), 12, '0')      as upc,
    cast(pc.start_date as date)                 as start_date,
    cast(pc.end_date as date)                   as end_date,
    cast(pc.discount_pct as double) / 100.0     as promo_pct,
    cast(pc.promo_price as double)              as promo_price,
    pc.in_flyer = 'Y'                           as in_flyer,
    case when pc.scope = 'NATIONAL' then 'NATIONAL' else 'REGIONAL' end as scope_type,
    case when pc.scope like 'REGION:%' then substr(pc.scope, 8) end    as scope_region
from {{ source('raw', 'marketing_promo_calendar') }} pc
left join {{ ref('stg_products') }} p on p.upc = lpad(cast(pc.upc as varchar), 12, '0')

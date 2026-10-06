-- Free-text reasons from store staff are mapped to three canonical reasons.
select
    cast(w.log_date as date)        as waste_date,
    cast(w.store_id as integer)     as store_id,
    cast(w.sku_id as integer)       as sku_id,
    cast(w.quantity as integer)     as quantity,
    w.reason                        as reason_raw,
    case
        when upper(trim(w.reason)) in ('EXPIRED', 'OUT OF DATE', 'PAST SELL-BY') then 'EXPIRED'
        when upper(trim(w.reason)) in ('DAMAGED', 'DMG') then 'DAMAGED'
        when upper(trim(w.reason)) in ('DONATED', 'FOOD BANK') then 'DONATED'
        else 'OTHER'
    end                             as reason,
    coalesce(cast(w.value_at_cost as double), cast(w.quantity as integer) * p.unit_cost) as value_at_cost,
    w.value_at_cost is null         as is_value_imputed
from {{ source('raw', 'quality_waste_log') }} w
left join {{ ref('stg_products') }} p on p.sku_id = cast(w.sku_id as integer)

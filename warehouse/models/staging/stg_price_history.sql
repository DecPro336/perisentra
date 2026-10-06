select
    cast(sku_id as integer)                     as sku_id,
    cast(valid_from as date)                    as valid_from,
    coalesce(
        lead(cast(valid_from as date)) over (partition by sku_id order by valid_from) - 1,
        cast('2099-12-31' as date)
    )                                           as valid_to,
    cast(regular_price as double)               as regular_price
from {{ source('raw', 'erp_price_history') }}

select
    test_id,
    cast(store_id as integer)                       as store_id,
    cast(sku_id as integer)                         as sku_id,
    cast(test_date as date)                         as test_date,
    cast(assigned_discount_pct as double) / 100.0   as assigned_discount_pct
from {{ source('raw', 'pricing_price_tests') }}

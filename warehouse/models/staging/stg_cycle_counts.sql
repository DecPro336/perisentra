select
    cast(count_date as date)        as count_date,
    cast(store_id as integer)       as store_id,
    cast(sku_id as integer)         as sku_id,
    cast(counted_qty as integer)    as counted_qty,
    cast(book_qty as integer)       as book_qty,
    cast(counted_qty as integer) - cast(book_qty as integer) as count_variance
from {{ source('raw', 'wms_cycle_counts') }}

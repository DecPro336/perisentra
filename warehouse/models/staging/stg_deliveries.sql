select
    lot_id,
    cast(delivery_date as date)     as delivery_date,
    cast(store_id as integer)       as store_id,
    cast(sku_id as integer)         as sku_id,
    cast(qty_ordered as integer)    as qty_ordered,
    cast(qty_received as integer)   as qty_received,
    cast(expiry_date as date)       as expiry_date
from {{ source('raw', 'erp_deliveries') }}

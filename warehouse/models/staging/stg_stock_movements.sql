select
    cast(movement_date as date)     as movement_date,
    cast(store_id as integer)       as store_id,
    cast(sku_id as integer)         as sku_id,
    upper(movement_type)            as movement_type,
    cast(quantity as integer)       as quantity
from {{ source('raw', 'wms_stock_movements') }}

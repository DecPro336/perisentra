select
    cast(store_id as integer)   as store_id,
    cast(sku_id as integer)     as sku_id,
    cast(listed_from as date)   as listed_from,
    cast(listed_to as date)     as listed_to
from {{ source('raw', 'erp_assortment') }}

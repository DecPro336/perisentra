select
    cast(store_id as integer)       as store_id,
    cast(closure_date as date)      as closure_date,
    cast(reason as varchar)         as reason
from {{ source('raw', 'erp_store_closures') }}

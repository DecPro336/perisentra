select
    cast(store_id as integer)   as store_id,
    cast(date as date)        as count_date,
    cast(entries as integer)    as entries,
    sensor
from {{ source('raw', 'footfall_counts') }}

select
    cast(store_id as integer)        as store_id,
    cast(pos_code as varchar)        as pos_code,
    name                             as store_name,
    city,
    region,
    format                           as store_format,
    cast(lat as double)              as latitude,
    cast(lon as double)              as longitude,
    cast(surface_sqft as integer)    as surface_sqft,
    cast(opened as date)             as opened_on,
    cast(sunday_open as boolean)     as is_sunday_open
from {{ source('raw', 'erp_stores') }}

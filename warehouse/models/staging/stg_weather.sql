select
    cast(location_id as integer)        as store_id,
    cast(date as date)                as weather_date,
    cast(temp_max as double)            as temp_max,
    cast(temp_min as double)            as temp_min,
    cast(precipitation as double)       as precipitation,
    source                              as weather_source
from {{ source('raw', 'ext_weather') }}

select distinct
    cast(date as date)    as holiday_date,
    name                    as holiday_name,
    local_name              as holiday_local_name,
    source                  as holiday_source
from {{ source('raw', 'ext_holidays') }}

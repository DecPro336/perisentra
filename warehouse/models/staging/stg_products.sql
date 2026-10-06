select
    cast(sku_id as integer)                       as sku_id,
    lpad(cast(upc as varchar), 12, '0')           as upc,
    name                                          as product_name,
    family,
    subfamily,
    cast(regular_price as double)                 as current_regular_price,
    cast(unit_cost as double)                     as unit_cost,
    cast(shelf_life_days as integer)              as shelf_life_days,
    cast(expiry_tracked as boolean)               as is_expiry_tracked,
    cast(case_pack as integer)                    as case_pack,
    cast(launch_date as date)                     as launch_date,
    nullif(cast(season_months as varchar), '')    as season_months,
    cast(delivery_schedule as varchar)            as delivery_schedule
from {{ source('raw', 'erp_products') }}

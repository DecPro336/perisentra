select
    store_id, sku_id, waste_date as date_day,
    cast(sum(case when reason = 'EXPIRED' then quantity else 0 end) as integer)  as waste_expired,
    cast(sum(case when reason = 'DAMAGED' then quantity else 0 end) as integer)  as waste_damaged,
    cast(sum(case when reason = 'DONATED' then quantity else 0 end) as integer)  as donated,
    sum(case when reason in ('EXPIRED', 'DAMAGED') then value_at_cost else 0 end) as waste_value
from {{ ref('stg_waste_log') }}
group by 1, 2, 3

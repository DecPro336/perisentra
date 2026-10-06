select
    store_id,
    sku_id,
    sale_date,
    cast(sum(units) as integer)                                     as units_sold,
    cast(sum(case when price_type = 'MD' then units else 0 end) as integer)    as units_markdown,
    cast(sum(case when price_type = 'PROMO' then units else 0 end) as integer) as units_promo,
    sum(gross_amount)                                               as gross_sales,
    sum(discount_amount)                                            as discount_given,
    sum(net_amount)                                                 as net_sales
from {{ ref('stg_pos_sales') }}
where store_id is not null and sku_id is not null
group by 1, 2, 3

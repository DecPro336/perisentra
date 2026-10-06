-- POS re-sends whole batches after outages: keep one row per business key, preferring the original batch.
with ranked as (
    select
        *,
        row_number() over (
            partition by business_date, store_code, upc, price_type
            order by case when batch_id like '%-001' then 0 else 1 end, _loaded_at
        ) as batch_rank
    from {{ source('raw', 'pos_daily_sales') }}
)

select
    cast(r.business_date as date)       as sale_date,
    s.store_id,
    p.sku_id,
    r.store_code,
    lpad(cast(r.upc as varchar), 12, '0') as upc,
    r.price_type,
    cast(r.units as integer)            as units,
    cast(r.gross_amount as double)      as gross_amount,
    cast(r.discount_amount as double)   as discount_amount,
    cast(r.net_amount as double)        as net_amount,
    r.batch_id,
    r._source_file
from ranked r
left join {{ ref('stg_stores') }} s on s.pos_code = r.store_code
left join {{ ref('stg_products') }} p on p.upc = lpad(cast(r.upc as varchar), 12, '0')
where r.batch_rank = 1

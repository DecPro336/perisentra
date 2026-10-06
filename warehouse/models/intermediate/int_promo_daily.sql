-- Promotions exploded to store x SKU x day, respecting national / regional scope.
with exploded as (
    select
        st.store_id,
        pr.sku_id,
        c.date_day,
        pr.promo_id,
        pr.promo_pct,
        pr.in_flyer
    from {{ ref('stg_promotions') }} pr
    join {{ ref('int_calendar') }} c on c.date_day between pr.start_date and pr.end_date
    join {{ ref('stg_stores') }} st on pr.scope_type = 'NATIONAL' or st.region = pr.scope_region
    where pr.sku_id is not null
)

select
    store_id, sku_id, date_day,
    max(promo_pct)                  as promo_pct,
    max(case when in_flyer then 1 else 0 end) = 1 as in_flyer,
    min(promo_id)                   as promo_id
from exploded
group by 1, 2, 3

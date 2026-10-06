-- Stock on hand this morning, split by lot and expiry. Book stock after the last business day is
-- allocated to the newest lots first (FIFO selling leaves the most recent deliveries on the shelf);
-- today's inbound deliveries come from open orders.
with b as (select * from {{ ref('int_bounds') }}),
last_stock as (
    select s.store_id, s.sku_id, greatest(s.closing_stock, 0) as book_stock
    from {{ ref('int_stock_daily') }} s
    join b on s.date_day = b.data_end
),
lots as (
    select l.*,
           sum(l.qty_received) over (partition by l.store_id, l.sku_id
                                     order by l.delivery_date desc, l.lot_id desc
                                     rows unbounded preceding) as cum_newest
    from {{ ref('int_lots') }} l
    join b on l.delivery_date <= b.data_end and l.expiry_date > b.data_end
),
on_hand as (
    select
        l.store_id, l.sku_id, l.lot_id, l.delivery_date, l.expiry_date, l.is_expiry_imputed,
        least(l.qty_received, greatest(0, ls.book_stock - (l.cum_newest - l.qty_received))) as qty_on_hand,
        false as is_inbound
    from lots l
    join last_stock ls on ls.store_id = l.store_id and ls.sku_id = l.sku_id
),
inbound as (
    select
        o.store_id, o.sku_id,
        'OPEN-' || cast(o.store_id as varchar) || '-' || cast(o.sku_id as varchar) as lot_id,
        o.delivery_date,
        {{ add_days('o.delivery_date', 'p.shelf_life_days - 1') }} as expiry_date,
        not p.is_expiry_tracked as is_expiry_imputed,
        o.qty_ordered as qty_on_hand,
        true as is_inbound
    from {{ ref('stg_open_orders') }} o
    join {{ ref('stg_products') }} p on p.sku_id = o.sku_id
    join b on o.delivery_date = {{ add_days('b.data_end', 1) }}
)
select *, (select {{ add_days('data_end', 1) }} from b) as as_of_date
from (
    select * from on_hand where qty_on_hand > 0
    union all
    select * from inbound
) x

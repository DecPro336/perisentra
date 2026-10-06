-- Rebuild daily book stock on hand from the movement ledger (anchored by the OPENING balance and
-- corrected by cycle-count ADJUST movements).
with mv as (
    select
        store_id, sku_id, movement_date,
        sum(case when movement_type = 'OPENING' then quantity else 0 end)    as opening_balance,
        sum(case when movement_type = 'RECEIPT' then quantity else 0 end)    as receipts,
        -sum(case when movement_type = 'SALE' then quantity else 0 end)      as sales_out,
        -sum(case when movement_type = 'WRITE_OFF' then quantity else 0 end) as write_offs,
        sum(case when movement_type = 'ADJUST' then quantity else 0 end)     as adjustments,
        sum(quantity)                                                        as net_movement
    from {{ ref('stg_stock_movements') }}
    group by 1, 2, 3
),
series as (
    select
        sc.store_id, sc.sku_id, sc.date_day,
        coalesce(mv.opening_balance, 0) as opening_balance,
        coalesce(mv.receipts, 0)        as receipts,
        coalesce(mv.sales_out, 0)       as sales_out,
        coalesce(mv.write_offs, 0)      as write_offs,
        coalesce(mv.adjustments, 0)     as adjustments,
        coalesce(mv.net_movement, 0)    as net_movement
    from {{ ref('int_series_calendar') }} sc
    left join mv on mv.store_id = sc.store_id and mv.sku_id = sc.sku_id and mv.movement_date = sc.date_day
)

select
    store_id, sku_id, date_day,
    cast(receipts as integer) as receipts, cast(sales_out as integer) as sales_out,
    cast(write_offs as integer) as write_offs, cast(adjustments as integer) as adjustments,
    cast(sum(net_movement) over (partition by store_id, sku_id order by date_day rows unbounded preceding)
        - (net_movement - opening_balance) as integer)                             as opening_stock,
    cast(sum(net_movement) over (partition by store_id, sku_id order by date_day rows unbounded preceding)
        as integer)                                                                 as closing_stock,
    -- stock left on the shelf right after the day's sales (before evening write-offs / count adjustments)
    cast(sum(net_movement) over (partition by store_id, sku_id order by date_day rows unbounded preceding)
        + write_offs - adjustments as integer)                                      as stock_after_sales
from series

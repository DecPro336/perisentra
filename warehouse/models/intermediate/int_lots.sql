-- Lots with an expiry date: actual when the SKU is expiry-tracked, otherwise imputed from the
-- delivery date and the product's specified shelf life.
select
    d.lot_id,
    d.store_id,
    d.sku_id,
    d.delivery_date,
    d.qty_received,
    coalesce(d.expiry_date, {{ add_days('d.delivery_date', 'p.shelf_life_days - 1') }}) as expiry_date,
    d.expiry_date is null                                                            as is_expiry_imputed
from {{ ref('stg_deliveries') }} d
join {{ ref('stg_products') }} p on p.sku_id = d.sku_id
where d.qty_received > 0

select
    p.*,
    ph.regular_price                                    as regular_price,
    round(1 - p.unit_cost / nullif(ph.regular_price, 0), 4) as regular_margin_rate
from {{ ref('stg_products') }} p
left join {{ ref('stg_price_history') }} ph
  on ph.sku_id = p.sku_id
 and (select data_end from {{ ref('int_bounds') }}) between ph.valid_from and ph.valid_to

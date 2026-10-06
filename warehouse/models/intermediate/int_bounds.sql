-- Data window: first and last POS business day, plus the forward horizon for known future covariates.
select
    min(sale_date)                                                       as data_start,
    max(sale_date)                                                       as data_end,
    {{ add_days('max(sale_date)', var('future_horizon_days')) }}          as horizon_end
from {{ ref('stg_pos_sales') }}

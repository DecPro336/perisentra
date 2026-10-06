select
    s.*,
    (select count(*) from {{ ref('stg_assortment') }} a where a.store_id = s.store_id) as listed_skus
from {{ ref('stg_stores') }} s

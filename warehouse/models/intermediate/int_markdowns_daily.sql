select
    store_id, sku_id, label_date as date_day,
    max(markdown_pct)       as markdown_pct,
    cast(sum(units_labelled) as integer) as units_labelled,
    min(label_source)       as label_source
from {{ ref('stg_markdown_labels') }}
group by 1, 2, 3

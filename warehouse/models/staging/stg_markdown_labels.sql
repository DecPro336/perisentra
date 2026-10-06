select
    cast(label_date as date)                    as label_date,
    cast(store_id as integer)                   as store_id,
    cast(sku_id as integer)                     as sku_id,
    cast(discount_pct as double) / 100.0        as markdown_pct,
    cast(units_labelled as integer)             as units_labelled,
    label_source
from {{ source('raw', 'pricing_markdown_labels') }}

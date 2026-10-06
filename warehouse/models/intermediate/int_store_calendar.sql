-- Opening calendar per store: closed on the holiday closures the ERP publishes, and on Sundays for stores that
-- do not open on Sundays.
select
    st.store_id,
    c.date_day,
    not (cl.closure_date is not null or (c.weekday = 6 and not st.is_sunday_open)) as is_open
from {{ ref('stg_stores') }} st
cross join {{ ref('int_calendar') }} c
left join {{ ref('stg_store_closures') }} cl
  on cl.store_id = st.store_id and cl.closure_date = c.date_day

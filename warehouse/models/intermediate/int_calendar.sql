with spine as (
    {{ date_spine(ref('int_bounds'), 'data_start', 'horizon_end') }}
),
hol as (
    select holiday_date, min(holiday_name) as holiday_name from {{ ref('stg_holidays') }} group by 1
),
days as (
    select
        s.date_day,
        h.holiday_name,
        h.holiday_date is not null                                                   as is_holiday,
        hn.holiday_date is not null                                                  as is_pre_holiday
    from spine s
    left join hol h  on h.holiday_date = s.date_day
    left join hol hn on hn.holiday_date = {{ add_days('s.date_day', 1) }}
),
-- distances to the nearest holidays with window functions (portable; no correlated subqueries)
nearest as (
    select
        d.*,
        min(case when d.is_holiday then d.date_day end)
            over (order by d.date_day rows between current row and unbounded following) as next_holiday,
        max(case when d.is_holiday then d.date_day end)
            over (order by d.date_day rows between unbounded preceding and current row) as prev_holiday
    from days d
)

select
    n.date_day,
    {{ iso_weekday0('n.date_day') }}                           as weekday,
    extract(day from n.date_day)                               as day_of_month,
    extract(month from n.date_day)                             as month,
    extract(year from n.date_day)                              as year,
    extract(dayofyear from n.date_day)                             as day_of_year,
    {{ week_start('n.date_day') }}                             as week_start,
    n.is_holiday,
    n.holiday_name,
    n.is_pre_holiday,
    {{ dbt.datediff('n.date_day', 'n.next_holiday', 'day') }}  as days_to_next_holiday,
    {{ dbt.datediff('n.prev_holiday', 'n.date_day', 'day') }}  as days_since_holiday
from nearest n

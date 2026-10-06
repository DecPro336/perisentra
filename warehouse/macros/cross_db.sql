{# Small cross-database helpers so the same models build on Snowflake and on the offline DuckDB copy. #}

{% macro date_spine(bounds_relation, start_col, end_col) %}
  {% if target.type == 'snowflake' %}
    select dateadd(day, g.seq, b.{{ start_col }})::date as date_day
    from {{ bounds_relation }} b
    cross join (select row_number() over (order by seq4()) - 1 as seq from table(generator(rowcount => 5000))) g
    where dateadd(day, g.seq, b.{{ start_col }}) <= b.{{ end_col }}
  {% else %}
    select cast(unnest(generate_series(cast(b.{{ start_col }} as timestamp),
                                       cast(b.{{ end_col }} as timestamp), interval 1 day)) as date) as date_day
    from {{ bounds_relation }} b
  {% endif %}
{% endmacro %}

{% macro iso_weekday0(col) %}
  {# Monday = 0 ... Sunday = 6 #}
  {% if target.type == 'snowflake' %}(dayofweekiso({{ col }}) - 1){% else %}(isodow({{ col }}) - 1){% endif %}
{% endmacro %}

{% macro week_start(col) %}
  {% if target.type == 'snowflake' %}date_trunc('week', {{ col }})::date{% else %}cast(date_trunc('week', {{ col }}) as date){% endif %}
{% endmacro %}

{% macro add_days(col, n) %}{{ dbt.dateadd('day', n, col) }}{% endmacro %}

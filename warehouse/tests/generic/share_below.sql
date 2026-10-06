{# Fails when more than `max_share` of rows match `condition` (data-quality guardrail). #}
{% test share_below(model, condition, max_share) %}
select share from (
  select avg(case when {{ condition }} then 1.0 else 0.0 end) as share from {{ model }}
) where share > {{ max_share }}
{% endtest %}

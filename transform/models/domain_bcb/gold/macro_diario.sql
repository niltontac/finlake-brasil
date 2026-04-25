{{
    config(
        materialized='table'
    )
}}

-- macro_diario não recalcula métricas: delega ao macro_mensal via ref().
-- acumulado_12m é carry forward: todos os dias de março/2026 têm acumulado_12m = 4.1428.
-- Join condition: date_trunc('month', s.date) = m.date vincula cada dia ao mês correto.
select
    s.date,
    s.taxa_anual,
    p.taxa_cambio,
    p.variacao_diaria_pct,
    m.acumulado_12m,
    (s.taxa_anual - m.acumulado_12m)::numeric(8, 4)                         as selic_real,
    current_timestamp                                                         as transformed_at
from {{ ref('macro_mensal') }} m
join {{ ref('selic_daily') }} s
    on date_trunc('month', s.date) = m.date
join {{ ref('ptax_daily') }} p
    on p.date = s.date

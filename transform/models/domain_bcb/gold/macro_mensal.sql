{{
    config(
        materialized='table'
    )
}}

-- SELIC real = taxa_anual (SELIC média mensal) - acumulado_12m (IPCA acumulado 12 meses)
-- Validação março/2026: AVG(14.6499) - MAX(4.1428) = 10.5071%
-- CTE para GROUP BY primeiro, LAG na query externa — PostgreSQL não suporta window dentro de aggregate
with monthly as (
    select
        date_trunc('month', s.date)::date           as date,
        avg(s.taxa_anual)::numeric(8, 4)            as taxa_anual,
        max(i.acumulado_12m)::numeric(8, 4)         as acumulado_12m,
        avg(p.taxa_cambio)::numeric(8, 4)           as ptax_media
    from {{ ref('selic_daily') }} s
    join {{ ref('ipca_monthly') }} i
        on date_trunc('month', s.date) = i.date
    join {{ ref('ptax_daily') }} p
        on p.date = s.date
    where i.acumulado_12m is not null
    group by date_trunc('month', s.date)
)

select
    date,
    taxa_anual,
    acumulado_12m,
    (taxa_anual - acumulado_12m)::numeric(8, 4)                             as selic_real,
    ptax_media,
    ((ptax_media / lag(ptax_media) over (order by date) - 1) * 100)
        ::numeric(8, 4)                                                     as ptax_variacao_mensal_pct,
    current_timestamp                                                        as transformed_at
from monthly

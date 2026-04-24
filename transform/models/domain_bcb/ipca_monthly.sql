{{
    config(
        materialized='table'
    )
}}

-- Produto encadeado via EXP(SUM(LN())) — fórmula exata de composição para % acumulado
-- CTE com row_number() para identificar os primeiros 11 meses (janela incompleta → NULL)
-- IPCA historicamente positivo desde 1994-07-01 — LN(valor positivo) não gera erros matemáticos

with base as (
    select
        date,
        valor,
        source_api,
        row_number() over (order by date) as rn
    from {{ source('bronze_bcb', 'ipca_monthly') }}
)

select
    date::date                                                          as date,
    valor::numeric(6, 4)                                               as variacao_mensal,
    case
        when rn >= 12
        then (
            (
                exp(
                    sum(ln(1 + valor / 100.0))
                    over (order by date rows between 11 preceding and current row)
                ) - 1
            ) * 100
        )::numeric(8, 4)
        else null
    end                                                                 as acumulado_12m,
    source_api::varchar(50)                                            as source_api,
    current_timestamp                                                   as transformed_at
from base

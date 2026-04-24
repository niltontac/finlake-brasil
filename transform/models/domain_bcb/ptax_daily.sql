{{
    config(
        materialized='table'
    )
}}

-- LAG(taxa_cambio) opera sobre dias úteis naturalmente
-- Bronze contém apenas dias úteis — fins de semana e feriados não existem na tabela
-- NULL apenas no primeiro registro histórico (1999-01-04)

select
    date::date                                                          as date,
    valor::numeric(10, 4)                                              as taxa_cambio,
    (
        (valor / lag(valor, 1) over (order by date) - 1) * 100
    )::numeric(8, 4)                                                   as variacao_diaria_pct,
    source_api::varchar(50)                                            as source_api,
    current_timestamp                                                   as transformed_at
from {{ source('bronze_bcb', 'ptax_daily') }}

{{
    config(
        materialized='table'
    )
}}

-- Convenção BCB: 252 dias úteis/ano
-- Fórmula: (power(1 + taxa_diaria / 100.0, 252) - 1) * 100
-- Exemplo: taxa_diaria = 0.054266 → taxa_anual ≈ 14.65% a.a.

select
    date::date                                                          as date,
    valor::numeric(10, 6)                                               as taxa_diaria,
    ((power(1 + valor / 100.0, 252) - 1) * 100)::numeric(8, 4)         as taxa_anual,
    source_api::varchar(50)                                             as source_api,
    current_timestamp                                                   as transformed_at
from {{ source('bronze_bcb', 'selic_daily') }}

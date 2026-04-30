{{
    config(
        materialized='table',
        schema='gold_cvm',
    )
}}

with daily as (
    select
        cnpj_fundo,
        dt_comptc,
        tp_fundo,
        vl_quota,
        lag(vl_quota) over (
            partition by cnpj_fundo
            order by dt_comptc
        )                       as vl_quota_anterior,
        vl_patrim_liq,
        captacao_liquida,
        current_timestamp       as transformed_at
    from {{ ref('informe_diario') }}
)

select
    cnpj_fundo,
    dt_comptc,
    tp_fundo,
    vl_quota::numeric(22, 8)                                             as vl_quota,
    vl_quota_anterior::numeric(22, 8)                                    as vl_quota_anterior,
    vl_patrim_liq::numeric(22, 6)                                        as vl_patrim_liq,
    captacao_liquida::numeric(22, 6)                                     as captacao_liquida,
    case
        when nullif(vl_quota_anterior, 0) is not null
            then ((vl_quota - vl_quota_anterior)
                  / nullif(vl_quota_anterior, 0) * 100)::numeric(20, 6)
        else null
    end                                                                  as rentabilidade_diaria_pct,
    transformed_at
from daily

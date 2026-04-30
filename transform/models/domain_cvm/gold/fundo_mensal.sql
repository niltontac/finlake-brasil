{{
    config(
        materialized='table',
        schema='gold_cvm',
    )
}}

-- Pré-agrega meses distintos por fundo: COUNT(DISTINCT) não é suportado
-- como window function no PostgreSQL — calculado como aggregate separado.
with meses_por_fundo as (
    select
        cnpj_fundo,
        count(distinct date_trunc('month', dt_comptc)::date)::integer    as meses_com_dados
    from {{ ref('informe_diario') }}
    group by cnpj_fundo
),

-- Estágio 1: window functions por row
-- PostgreSQL não permite window function aninhada dentro de aggregate.
-- Padrão idêntico ao macro_mensal.sql do Gold BCB.
monthly_base as (
    select
        cnpj_fundo,
        date_trunc('month', dt_comptc)::date                             as ano_mes,
        tp_fundo,
        vl_quota,
        captacao_liquida,
        vl_patrim_liq,
        nr_cotst,
        first_value(vl_quota) over (
            partition by cnpj_fundo, date_trunc('month', dt_comptc)
            order by dt_comptc
            rows between unbounded preceding and unbounded following
        )                                                                as vl_quota_inicial,
        last_value(vl_quota) over (
            partition by cnpj_fundo, date_trunc('month', dt_comptc)
            order by dt_comptc
            rows between unbounded preceding and unbounded following
        )                                                                as vl_quota_final
    from {{ ref('informe_diario') }}
),

-- Estágio 2: aggregate por (cnpj_fundo, ano_mes)
-- tp_fundo fora do GROUP BY: alguns CNPJs mudam de tipo no mesmo mês (dado CVM).
-- MAX() garante grain único e valor determinístico.
monthly_agg as (
    select
        b.cnpj_fundo,
        b.ano_mes,
        max(b.tp_fundo)                                                  as tp_fundo,
        max(b.vl_quota_inicial)::numeric(22, 8)                          as vl_quota_inicial,
        max(b.vl_quota_final)::numeric(22, 8)                            as vl_quota_final,
        sum(b.captacao_liquida)::numeric(22, 6)                          as captacao_liquida_acumulada,
        avg(b.vl_patrim_liq)::numeric(22, 6)                             as vl_patrim_liq_medio,
        avg(b.nr_cotst)::numeric(10, 2)                                  as nr_cotst_medio,
        m.meses_com_dados
    from monthly_base b
    join meses_por_fundo m on m.cnpj_fundo = b.cnpj_fundo
    group by b.cnpj_fundo, b.ano_mes, m.meses_com_dados
),

-- Estágio 3: enriquecer com atributos de fundos e cross-domain BCB
enriched as (
    select
        a.cnpj_fundo,
        a.ano_mes,
        a.tp_fundo,
        f.gestor,
        a.vl_quota_inicial,
        a.vl_quota_final,
        case
            when nullif(a.vl_quota_inicial, 0) is not null
                then ((a.vl_quota_final - a.vl_quota_inicial)
                      / nullif(a.vl_quota_inicial, 0) * 100)::numeric(20, 6)
            else null
        end                                                              as rentabilidade_mes_pct,
        a.captacao_liquida_acumulada,
        a.vl_patrim_liq_medio,
        a.nr_cotst_medio,
        a.meses_com_dados,
        m.taxa_anual                                                     as taxa_anual_bcb,
        m.acumulado_12m                                                  as acumulado_12m_ipca
    from monthly_agg a
    left join {{ ref('fundos') }} f
        on f.cnpj_fundo = a.cnpj_fundo
    left join {{ ref('macro_mensal') }} m
        on a.ano_mes = m.date
)

select
    cnpj_fundo,
    ano_mes,
    tp_fundo,
    gestor,
    vl_quota_inicial,
    vl_quota_final,
    rentabilidade_mes_pct,
    captacao_liquida_acumulada,
    vl_patrim_liq_medio,
    nr_cotst_medio,
    meses_com_dados,
    taxa_anual_bcb,
    acumulado_12m_ipca,
    case
        when rentabilidade_mes_pct is not null and taxa_anual_bcb is not null
            then (rentabilidade_mes_pct - taxa_anual_bcb / 12)::numeric(20, 6)
        else null
    end                                                                  as alpha_selic,
    case
        when rentabilidade_mes_pct is not null and acumulado_12m_ipca is not null
            then (rentabilidade_mes_pct - acumulado_12m_ipca / 12)::numeric(20, 6)
        else null
    end                                                                  as alpha_ipca,
    current_timestamp                                                    as transformed_at
from enriched

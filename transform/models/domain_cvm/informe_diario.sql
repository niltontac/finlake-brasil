{{
    config(
        materialized='incremental',
        schema='silver_cvm',
        unique_key=['cnpj_fundo', 'dt_comptc'],
        incremental_strategy='delete+insert',
    )
}}

select
    cnpj_fundo::varchar(18)                                              as cnpj_fundo,
    dt_comptc::date                                                      as dt_comptc,
    tp_fundo::varchar(50)                                                as tp_fundo,
    vl_total::numeric(22, 6)                                             as vl_total,
    vl_quota::numeric(22, 8)                                             as vl_quota,
    vl_patrim_liq::numeric(22, 6)                                        as vl_patrim_liq,
    captc_dia::numeric(22, 6)                                            as captc_dia,
    resg_dia::numeric(22, 6)                                             as resg_dia,
    (captc_dia::numeric(22, 6) - resg_dia::numeric(22, 6))              as captacao_liquida,
    nr_cotst::integer                                                    as nr_cotst,
    current_timestamp                                                    as transformed_at
from {{ source('bronze_cvm', 'informe_diario') }}

{% if is_incremental() %}
    where dt_comptc >= (
        select max(dt_comptc) - interval '30 days'
        from {{ this }}
    )
{% endif %}

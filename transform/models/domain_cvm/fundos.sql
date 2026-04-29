{{
    config(
        materialized='table',
        schema='silver_cvm',
    )
}}

select
    cnpj_fundo::varchar(18)      as cnpj_fundo,
    tp_fundo::varchar(100)       as tp_fundo,
    denom_social::text           as denom_social,
    sit::varchar(80)             as sit,
    classe::varchar(100)         as classe,
    classe_anbima::varchar(100)  as classe_anbima,
    publico_alvo::text           as publico_alvo,
    fundo_exclusivo::varchar(1)  as fundo_exclusivo,
    taxa_adm::numeric(10, 4)     as taxa_adm,
    taxa_perfm::numeric(10, 4)   as taxa_perfm,
    dt_ini_ativ::date            as dt_ini_ativ,
    dt_fim_ativ::date            as dt_fim_ativ,
    admin::text                  as admin,
    gestor::text                 as gestor,
    current_timestamp            as transformed_at
from {{ source('bronze_cvm', 'cadastro') }}
where sit in ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')

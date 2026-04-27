-- Domínio CVM — schema e tabelas Bronze
-- Execute: psql -U postgres -d finlake -f docker/postgres/migrations/004_bronze_cvm.sql
-- Idempotente: IF NOT EXISTS em todas as operações

CREATE SCHEMA IF NOT EXISTS bronze_cvm;

COMMENT ON SCHEMA bronze_cvm IS
    'Bronze layer — domínio CVM (Comissão de Valores Mobiliários). '
    'Dados brutos sem transformação. Espelho do estado atual da fonte.';

-- ---------------------------------------------------------------------------
-- CADASTRO DE FUNDOS — cad_fi.csv (SCD Tipo 1)
-- 40 colunas da fonte + 3 colunas de auditoria
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_cvm.cadastro (
    -- Identificação principal
    cnpj_fundo           VARCHAR(18)   NOT NULL,
    tp_fundo             VARCHAR(100),
    denom_social         TEXT,
    cd_cvm               VARCHAR(20),

    -- Ciclo de vida do fundo
    dt_reg               DATE,
    dt_const             DATE,
    dt_cancel            DATE,
    dt_ini_ativ          DATE,
    dt_fim_ativ          DATE,
    dt_ini_sit           DATE,
    dt_ini_exerc         DATE,
    dt_fim_exerc         DATE,

    -- Situação, classificação e público
    sit                  VARCHAR(80),
    classe               VARCHAR(100),
    classe_anbima        VARCHAR(100),
    rentab_fundo         TEXT,
    publico_alvo         TEXT,

    -- Estrutura e características
    condom               VARCHAR(20),
    fundo_cotas          VARCHAR(1),
    fundo_exclusivo      VARCHAR(1),
    trib_lprazo          VARCHAR(1),
    entid_invest         VARCHAR(1),
    invest_cempr_exter   VARCHAR(1),

    -- Taxas e informações complementares
    taxa_perfm           NUMERIC(10,4),
    inf_taxa_perfm       TEXT,
    taxa_adm             NUMERIC(10,4),
    inf_taxa_adm         TEXT,

    -- Patrimônio líquido
    vl_patrim_liq        NUMERIC(18,6),
    dt_patrim_liq        DATE,

    -- Administrador
    cnpj_admin           VARCHAR(18),
    admin                TEXT,
    diretor              TEXT,

    -- Gestor
    pf_pj_gestor         VARCHAR(2),
    cpf_cnpj_gestor      VARCHAR(18),
    gestor               TEXT,

    -- Auditor
    cnpj_auditor         VARCHAR(18),
    auditor              TEXT,

    -- Custodiante
    cnpj_custodiante     VARCHAR(18),
    custodiante          TEXT,

    -- Controlador
    cnpj_controlador     VARCHAR(18),
    controlador          TEXT,

    -- Auditoria (geradas na ingestão — não presentes no CSV)
    ingested_at          TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_url           VARCHAR(300)  NOT NULL,

    CONSTRAINT cadastro_pkey PRIMARY KEY (cnpj_fundo)
);

COMMENT ON TABLE  bronze_cvm.cadastro              IS 'Cadastro de fundos — cad_fi.csv. SCD Tipo 1.';
COMMENT ON COLUMN bronze_cvm.cadastro.cnpj_fundo   IS 'CNPJ do fundo (PK). Formato: XX.XXX.XXX/XXXX-XX';
COMMENT ON COLUMN bronze_cvm.cadastro.updated_at   IS 'Timestamp da última atualização via ON CONFLICT DO UPDATE';
COMMENT ON COLUMN bronze_cvm.cadastro.source_url   IS 'URL do arquivo de origem (CADASTRO_URL)';

-- ---------------------------------------------------------------------------
-- INFORME DIÁRIO — inf_diario_fi_YYYYMM.zip (particionado por ano)
-- 9 colunas da fonte + 2 colunas de auditoria
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario (
    tp_fundo        VARCHAR(10),
    cnpj_fundo      VARCHAR(18)    NOT NULL,
    dt_comptc       DATE           NOT NULL,
    vl_total        NUMERIC(18,6),
    vl_quota        NUMERIC(18,8),
    vl_patrim_liq   NUMERIC(18,6),
    captc_dia       NUMERIC(18,6),
    resg_dia        NUMERIC(18,6),
    nr_cotst        INTEGER,
    ingested_at     TIMESTAMP      NOT NULL DEFAULT NOW(),
    source_url      VARCHAR(300)   NOT NULL,
    CONSTRAINT informe_diario_pkey PRIMARY KEY (cnpj_fundo, dt_comptc)
) PARTITION BY RANGE (dt_comptc);

COMMENT ON TABLE  bronze_cvm.informe_diario            IS 'Informe diário de fundos — inf_diario_fi_YYYYMM.zip. Particionado por ano.';
COMMENT ON COLUMN bronze_cvm.informe_diario.dt_comptc  IS 'Data de competência (chave de partição + PK)';
COMMENT ON COLUMN bronze_cvm.informe_diario.cnpj_fundo IS 'FK lógica para bronze_cvm.cadastro';

-- Bloco histórico imutável 2000–2020 (arquivos anuais HIST/)
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_hist
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2000-01-01') TO ('2021-01-01');

-- Partições anuais para dados incrementais (2021+)
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2021
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2022
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2023
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2024
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2025
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2026
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

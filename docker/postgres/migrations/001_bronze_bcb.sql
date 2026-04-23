-- Domínio BCB — schema e tabelas Bronze
-- Execute: psql -U postgres -d finlake -f docker/postgres/migrations/001_bronze_bcb.sql
-- Idempotente: IF NOT EXISTS em todas as operações

CREATE SCHEMA IF NOT EXISTS bronze_bcb;

COMMENT ON SCHEMA bronze_bcb IS
    'Bronze layer — domínio BCB (Banco Central do Brasil). '
    'Dados brutos sem transformação, particionados por data de referência.';

-- ---------------------------------------------------------------------------
-- SELIC diária — série BCB SGS 11
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_bcb.selic_daily (
    date        DATE          NOT NULL,
    valor       NUMERIC(10,6) NOT NULL,
    ingested_at TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_api  VARCHAR(50)   NOT NULL DEFAULT 'BCB_SGS',
    CONSTRAINT selic_daily_pkey PRIMARY KEY (date)
);

COMMENT ON TABLE  bronze_bcb.selic_daily        IS 'SELIC over (diária) — série BCB SGS 11';
COMMENT ON COLUMN bronze_bcb.selic_daily.date   IS 'Data de referência (apenas dias úteis)';
COMMENT ON COLUMN bronze_bcb.selic_daily.valor  IS 'Taxa SELIC (% a.d., 6 casas decimais)';

-- ---------------------------------------------------------------------------
-- IPCA mensal — série BCB SGS 433
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_bcb.ipca_monthly (
    date        DATE         NOT NULL,
    valor       NUMERIC(6,4) NOT NULL,
    ingested_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    source_api  VARCHAR(50)  NOT NULL DEFAULT 'BCB_SGS',
    CONSTRAINT ipca_monthly_pkey PRIMARY KEY (date)
);

COMMENT ON TABLE  bronze_bcb.ipca_monthly        IS 'IPCA (mensal) — série BCB SGS 433';
COMMENT ON COLUMN bronze_bcb.ipca_monthly.date   IS 'Primeiro dia do mês de referência';
COMMENT ON COLUMN bronze_bcb.ipca_monthly.valor  IS 'Variação mensal do IPCA (%, 4 casas decimais)';

-- ---------------------------------------------------------------------------
-- PTAX venda USD/BRL diária — série BCB SGS 1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_bcb.ptax_daily (
    date        DATE          NOT NULL,
    valor       NUMERIC(10,4) NOT NULL,
    ingested_at TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_api  VARCHAR(50)   NOT NULL DEFAULT 'BCB_SGS',
    CONSTRAINT ptax_daily_pkey PRIMARY KEY (date)
);

COMMENT ON TABLE  bronze_bcb.ptax_daily        IS 'PTAX venda USD/BRL (diária) — série BCB SGS 1';
COMMENT ON COLUMN bronze_bcb.ptax_daily.date   IS 'Data de referência (apenas dias úteis)';
COMMENT ON COLUMN bronze_bcb.ptax_daily.valor  IS 'Taxa PTAX venda (R$/USD, 4 casas decimais)';

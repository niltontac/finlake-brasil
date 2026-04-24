-- Domínio BCB — schema Silver
-- Execute: make migrate (ou psql -U postgres -d finlake -f docker/postgres/migrations/002_silver_bcb.sql)
-- Idempotente: IF NOT EXISTS — dbt cria as tabelas; migration cria apenas o schema

CREATE SCHEMA IF NOT EXISTS silver_bcb;

COMMENT ON SCHEMA silver_bcb IS
    'Silver layer — domínio BCB (Banco Central do Brasil). '
    'Dados transformados, validados e com indicadores derivados. '
    'Tabelas criadas e mantidas pelo dbt-core.';

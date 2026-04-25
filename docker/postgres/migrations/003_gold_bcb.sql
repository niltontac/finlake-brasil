-- Domínio BCB — schema Gold
-- Execute: make migrate (ou psql -U postgres -d finlake -f docker/postgres/migrations/003_gold_bcb.sql)
-- Idempotente: IF NOT EXISTS — dbt cria as tabelas; migration cria apenas o schema

CREATE SCHEMA IF NOT EXISTS gold_bcb;

COMMENT ON SCHEMA gold_bcb IS
    'Gold layer — domínio BCB (Banco Central do Brasil). '
    'Métricas analíticas cross-série: SELIC real, câmbio médio mensal e variação cambial. '
    'Tabelas criadas e mantidas pelo dbt-core.';

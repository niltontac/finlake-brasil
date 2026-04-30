-- 006_gold_cvm.sql
-- Provisiona o schema gold_cvm para os modelos dbt do domínio Fundos (CVM).
-- As tabelas são criadas pelo dbt; esta migration apenas cria o schema.
-- Idempotente: pode ser executada múltiplas vezes sem erro.

CREATE SCHEMA IF NOT EXISTS gold_cvm;

COMMENT ON SCHEMA gold_cvm IS
    'Camada Gold do domínio Fundos (CVM): métricas de performance, cross-domain BCB×CVM. Tabelas gerenciadas pelo dbt.';

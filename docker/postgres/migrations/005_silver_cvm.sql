-- 005_silver_cvm.sql
-- Provisiona o schema silver_cvm para os modelos dbt do domínio Fundos (CVM).
-- As tabelas são criadas pelo dbt; esta migration apenas cria o schema.
-- Idempotente: pode ser executada múltiplas vezes sem erro.

CREATE SCHEMA IF NOT EXISTS silver_cvm;

COMMENT ON SCHEMA silver_cvm IS
    'Camada Silver do domínio Fundos (CVM): dados filtrados, tipados e validados. Tabelas gerenciadas pelo dbt.';

-- Cria database de metadados do Airflow (finlake já é criado via POSTGRES_DB env var)
SELECT 'CREATE DATABASE airflow_metadata'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'airflow_metadata'
)\gexec

-- Schemas da plataforma FinLake (Medallion Architecture)
\c finlake;

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

COMMENT ON SCHEMA bronze IS 'Dados brutos sem transformação, particionados por data de ingestão';
COMMENT ON SCHEMA silver IS 'Dados limpos, validados, tipados e normalizados por domínio';
COMMENT ON SCHEMA gold IS 'Métricas agregadas e cruzamentos prontos para consumo';

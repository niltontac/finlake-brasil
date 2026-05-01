-include .env
export

.PHONY: up down logs ps reset test init-db cvm-hist-load help

PROFILE ?= full

help: ## Exibe esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Sobe os serviços (PROFILE=core|orchestration|full, padrão: full)
	docker compose --profile $(PROFILE) up -d

init-db: ## Inicializa databases e schemas (executar após 'make up')
	@echo "→ Criando database airflow_metadata..."
	@docker exec finlake-postgres psql -U $(POSTGRES_USER) -c \
		"CREATE DATABASE airflow_metadata;" 2>/dev/null || echo "  (já existe, ok)"
	@echo "→ Criando schemas Medallion em finlake..."
	@docker exec finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -c \
		"CREATE SCHEMA IF NOT EXISTS bronze; CREATE SCHEMA IF NOT EXISTS silver; CREATE SCHEMA IF NOT EXISTS gold;"
	@echo "✓ Databases e schemas criados."

down: ## Para todos os containers
	docker compose down

logs: ## Stream de logs de todos os serviços
	docker compose logs -f

ps: ## Status dos serviços
	docker compose ps

migrate: ## Executa migrations do PostgreSQL (requer 'make up PROFILE=core')
	@echo "→ Executando migration 001_bronze_bcb (schema bronze_bcb + tabelas)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/001_bronze_bcb.sql
	@echo "✓ Migration 001_bronze_bcb executada."
	@echo "→ Executando migration 002_silver_bcb (schema silver_bcb)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/002_silver_bcb.sql
	@echo "✓ Migration 002_silver_bcb executada."
	@echo "→ Executando migration 003_gold_bcb (schema gold_bcb)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/003_gold_bcb.sql
	@echo "✓ Migration 003_gold_bcb executada."
	@echo "→ Executando migration 004_bronze_cvm (schema bronze_cvm + tabelas + partições)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/004_bronze_cvm.sql
	@echo "✓ Migration 004_bronze_cvm executada."
	@echo "→ Executando migration 005_silver_cvm (schema silver_cvm)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/005_silver_cvm.sql
	@echo "✓ Migration 005_silver_cvm executada."
	@echo "→ Executando migration 006_gold_cvm (schema gold_cvm)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/006_gold_cvm.sql
	@echo "✓ Migration 006_gold_cvm executada."

cvm-hist-load: ## Carga histórica CVM via PySpark (START_YEAR=XXXX END_YEAR=XXXX SPARK_JDBC_JAR=/path/to/postgresql.jar)
	@set -a && . ./.env && set +a && \
		spark-submit \
		--jars $(SPARK_JDBC_JAR) \
		scripts/spark/historical_load_cvm.py \
		--start-year $(START_YEAR) \
		--end-year $(END_YEAR)

metabase-export: ## Exporta dashboard "BCB Macro" para docs/metabase/
	@set -a && . ./.env && set +a && bash scripts/export_metabase.sh

metabase-export-cvm: ## Exporta 3 dashboards CVM para docs/metabase/ (requer 'make up PROFILE=full' e .env)
	@set -a && . ./.env && set +a && bash scripts/export_metabase_cvm.sh

metabase-export-all: ## Exporta todos os dashboards BCB + CVM (requer 'make up PROFILE=full' e .env)
	@set -a && . ./.env && set +a && bash scripts/export_metabase.sh
	@set -a && . ./.env && set +a && bash scripts/export_metabase_cvm.sh

reset: ## Para containers e remove volumes nomeados (dados do PostgreSQL são perdidos)
	@echo "ATENÇÃO: Este comando remove todos os dados do PostgreSQL."
	@read -p "Confirma? [y/N] " ans && [ "$$ans" = "y" ] || exit 1
	docker compose down -v

test: ## Executa smoke tests nos serviços (requer 'make up' anterior)
	@echo "→ Testando conectividade PostgreSQL..."
	@docker exec finlake-postgres pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB)
	@echo "→ Verificando schemas bronze/silver/gold..."
	@docker exec finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		-c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('bronze','silver','gold') ORDER BY schema_name;" \
		| grep -E "bronze|silver|gold"
	@echo "→ Testando Airflow health..."
	@curl -sf http://localhost:$(AIRFLOW_PORT)/health | python3 -m json.tool
	@echo "→ Testando Metabase health..."
	@curl -sf http://localhost:$(METABASE_PORT)/api/health
	@echo "✓ Todos os smoke tests passaram."

.DEFAULT_GOAL := help
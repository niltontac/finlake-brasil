-include .env
export

.PHONY: up down logs ps reset test help

PROFILE ?= full

help: ## Exibe esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Sobe os serviços (PROFILE=core|orchestration|full, padrão: full)
	docker compose --profile $(PROFILE) up -d

down: ## Para todos os containers
	docker compose down

logs: ## Stream de logs de todos os serviços
	docker compose logs -f

ps: ## Status dos serviços
	docker compose ps

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

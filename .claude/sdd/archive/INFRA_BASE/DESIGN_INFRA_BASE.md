# DESIGN: Infrastructure Base

> Especificação técnica da infraestrutura local containerizada com Docker Compose Modular + Profiles para o FinLake Brasil

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | INFRA_BASE |
| **Date** | 2026-04-21 |
| **Author** | design-agent |
| **DEFINE** | [DEFINE_INFRA_BASE.md](./DEFINE_INFRA_BASE.md) |
| **Status** | Ready for Build |

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│                      Docker Network: finlake-net                     │
│                                                                     │
│  ┌─────────────────┐   ┌──────────────────┐   ┌─────────────────┐  │
│  │   postgres:5432  │   │  airflow:8080    │   │ metabase:3030   │  │
│  │  PostgreSQL 15   │◄──│  standalone mode │   │  (H2 embedded)  │  │
│  │                  │   │  webserver +     │   │                 │  │
│  │  DB: finlake     │   │  scheduler       │   │  reads from PG  │  │
│  │  DB: airflow_meta│   │  (LocalExecutor) │   │  (via UI config)│  │
│  │                  │   │                  │   │                 │  │
│  │  named volume:   │   │  bind mounts:    │   └─────────────────┘  │
│  │  postgres-data   │   │  ./dags/ → DAGs  │                        │
│  └─────────────────┘   │  ./data/ → files │                        │
│                         └──────────────────┘                        │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                      Host Filesystem (bind mounts)                   │
│                                                                     │
│   ./dags/   ──────────────────────────► Airflow DAGs (versionados)  │
│   ./data/   ──────────────────────────► DuckDB + Parquet files       │
│             finlake.duckdb                                           │
└─────────────────────────────────────────────────────────────────────┘

Profiles:
  core          →  postgres
  orchestration →  postgres + airflow
  full          →  postgres + airflow + metabase
```

---

## Components

| Component | Purpose | Technology | Profile |
|-----------|---------|------------|---------|
| PostgreSQL 15 | Storage Bronze (dados brutos) + metadata do Airflow | `postgres:15-alpine` | core, orchestration, full |
| Airflow standalone | Orquestração de pipelines BCB e CVM | `apache/airflow:2.10.4-python3.12` | orchestration, full |
| Metabase | Dashboards e visualização camada Gold | `metabase/metabase:latest` | full |
| DuckDB | Processamento analítico Gold (sem container — arquivo local) | Bind mount `./data/` | — |
| finlake-net | Rede interna Docker para comunicação entre serviços | Docker bridge network | todos |
| postgres-data | Volume nomeado para persistência do PostgreSQL | Docker named volume | todos |

---

## Key Decisions

### Decision 1: Docker Compose `include` + Profiles nativos

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-21 |

**Context:** O projeto precisa de flexibilidade para subir subconjuntos de serviços conforme o contexto (CI/CD precisa apenas de PostgreSQL; desenvolvimento precisa de Airflow; demo completa precisa de Metabase).

**Choice:** Cada serviço em arquivo Compose dedicado (`docker/compose.*.yml`), orquestrado pelo `docker-compose.yml` raiz via diretiva `include`. Profiles nativos do Docker Compose definem quais serviços sobem em cada contexto.

**Rationale:** É a solução mais idiomática disponível no Docker Compose v2.20+. Sem scripts shell para gerenciar múltiplos `-f`, sem lógica de orquestração externa. O Makefile apenas expõe os profiles como interface conveniente.

**Alternatives Rejected:**
1. Compose monolítico (`docker-compose.yml` único) — Rejeitado por falta de flexibilidade para CI/CD e crescimento sem controle
2. Múltiplos arquivos via flag `-f` no Makefile — Rejeitado por não ser idiomático, requer shell logic para combinar arquivos

**Consequences:**
- Requer Docker Compose v2.20+ (padrão no Docker Desktop atual)
- Cada arquivo de serviço é autossuficiente e pode ser inspecionado isoladamente

---

### Decision 2: Airflow `standalone` mode para desenvolvimento local

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-21 |

**Context:** LocalExecutor foi escolhido no Brainstorm. A alternativa canônica (compose oficial do Airflow) usa 5+ containers (webserver, scheduler, worker, redis, flower), o que é excessivo para desenvolvimento local.

**Choice:** Um único container Airflow usando o comando `airflow standalone`, que inicializa o banco de metadados, cria o usuário admin e inicia webserver + scheduler + triggerer em um único processo.

**Rationale:** `airflow standalone` é suportado oficialmente para desenvolvimento desde Airflow 2.4. Reduz o ambiente de 5 containers para 1, sem comprometer a funcionalidade de desenvolvimento. Para produção, a arquitetura mudaria para containers separados com CeleryExecutor ou KubernetesExecutor.

**Alternatives Rejected:**
1. Compose oficial do Airflow com 5 containers — Over-engineering para local dev, conflita com YAGNI
2. Astronomer Astro CLI — Dependência externa que obscurece conhecimento do Airflow puro

**Consequences:**
- `airflow standalone` não é recomendado para produção
- Migração futura para arquitetura multi-container requer redesign do compose

---

### Decision 3: PostgreSQL único para `finlake` e `airflow_metadata`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-21 |

**Context:** Airflow necessita de banco de metadados. PostgreSQL já está no projeto para dados Bronze. Criar um segundo container PostgreSQL apenas para Airflow seria desperdício de recursos em ambiente de desenvolvimento.

**Choice:** Container PostgreSQL único com duas databases: `finlake` (dados da plataforma) e `airflow_metadata` (metadados do Airflow). Script `init.sql` cria ambas na inicialização.

**Rationale:** PostgreSQL suporta múltiplas databases nativamente. O volume de metadados do Airflow em desenvolvimento é negligenciável. Reduz de 2 containers PostgreSQL para 1.

**Alternatives Rejected:**
1. SQLite para Airflow metadata — Não suporta bem concorrência com LocalExecutor; não reflete padrão de produção
2. Container PostgreSQL separado para Airflow — YAGNI; overhead desnecessário em dev

**Consequences:**
- `make reset` (que remove volumes) apaga tanto dados do FinLake quanto metadados do Airflow
- Única string de conexão para gerenciar, mas com duas databases distintas

---

### Decision 4: `pip` com constraints para imagem Airflow (uv postergado)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-04-21 |

**Context:** A convenção do projeto é `uv` para gerenciamento de pacotes (definido no CLAUDE.md). A assumption A-003 identificou risco de incompatibilidade entre `uv` e a imagem oficial do Airflow.

**Choice:** Para o MVP, usar `pip` com `apache-airflow-constraints-*.txt` para instalar dependências extras na imagem customizada do Airflow. Documentar migração para `uv` como próximo passo após validação.

**Rationale:** O Airflow tem um sistema rígido de gerenciamento de dependências via constraints para garantir compatibilidade. A imagem oficial usa `pip`. Introduzir `uv` sem validação pode quebrar a resolução de dependências do Airflow. `pip` com constraints é o padrão documentado pelo projeto Apache Airflow.

**Alternatives Rejected:**
1. `_PIP_ADDITIONAL_REQUIREMENTS` env var — Deprecado no Airflow 2.8+; instala pacotes a cada restart do container
2. `uv` sem validação — Risco de conflito com constraints do Airflow; assumption A-003 não validada

**Consequences:**
- Instalação de dependências via `pip` (mais lento que `uv`)
- Migração para `uv` documentada como melhoria futura, após validação de compatibilidade

---

## File Manifest

| # | File | Action | Purpose | Dependencies |
|---|------|--------|---------|--------------|
| 1 | `docker-compose.yml` | Create | Orquestrador principal: `include`, network, volume | Nenhuma |
| 2 | `docker/compose.postgres.yml` | Create | Serviço PostgreSQL 15 com volume nomeado e init.sql | 1, 9 |
| 3 | `docker/compose.airflow.yml` | Create | Serviço Airflow standalone com bind mounts | 1, 2, 7 |
| 4 | `docker/compose.metabase.yml` | Create | Serviço Metabase na porta 3030 | 1, 2 |
| 5 | `docker/airflow/Dockerfile` | Create | Imagem customizada Airflow + dependências Python | 6 |
| 6 | `docker/airflow/requirements.txt` | Create | Dependências Python para pipelines BCB/CVM | Nenhuma |
| 7 | `docker/postgres/init.sql` | Create | Cria databases `finlake` e `airflow_metadata` | Nenhuma |
| 8 | `.env.example` | Create | Todas as variáveis documentadas com placeholders | Nenhuma |
| 9 | `Makefile` | Create | Targets: `up`, `down`, `logs`, `ps`, `reset` | Nenhuma |
| 10 | `dags/.gitkeep` | Create | Placeholder para diretório de DAGs versionado | Nenhuma |
| 11 | `data/.gitkeep` | Create | Placeholder para diretório de dados versionado | Nenhuma |

**Total Files:** 11

---

## Agent Assignment Rationale

| Agent | Files | Justificativa |
|-------|-------|---------------|
| @ci-cd-specialist | 1, 2, 3, 4 | Especialista em Docker Compose, infraestrutura como código, profiles e pipelines |
| @aws-lambda-architect | — | N/A para este feature (infra local, sem Lambda) |
| @shell-script-specialist | 9 | Especialista em Makefile e scripts de automação com boas práticas |
| (general) | 5, 6, 7, 8, 10, 11 | Dockerfile, requirements.txt, SQL de init, .env.example — padrões diretos sem especialista dedicado |

---

## Code Patterns

### Pattern 1: `docker-compose.yml` — Orquestrador com `include` e recursos compartilhados

```yaml
# docker-compose.yml
# Orquestrador principal — declara recursos compartilhados e inclui serviços

include:
  - path: docker/compose.postgres.yml
  - path: docker/compose.airflow.yml
  - path: docker/compose.metabase.yml

networks:
  finlake-net:
    driver: bridge

volumes:
  postgres-data:
    driver: local
```

---

### Pattern 2: `docker/compose.postgres.yml` — Serviço PostgreSQL

```yaml
# docker/compose.postgres.yml

services:
  postgres:
    image: postgres:15-alpine
    profiles: ["core", "orchestration", "full"]
    container_name: finlake-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./docker/postgres/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - finlake-net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
```

---

### Pattern 3: `docker/compose.airflow.yml` — Serviço Airflow standalone

```yaml
# docker/compose.airflow.yml

services:
  airflow:
    build:
      context: .
      dockerfile: docker/airflow/Dockerfile
    profiles: ["orchestration", "full"]
    container_name: finlake-airflow
    restart: unless-stopped
    command: standalone
    environment:
      AIRFLOW__CORE__EXECUTOR: LocalExecutor
      AIRFLOW__CORE__FERNET_KEY: ${AIRFLOW__CORE__FERNET_KEY}
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: >-
        postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/airflow_metadata
      AIRFLOW__CORE__LOAD_EXAMPLES: "false"
      AIRFLOW__WEBSERVER__SECRET_KEY: ${AIRFLOW__WEBSERVER__SECRET_KEY}
      _AIRFLOW_WWW_USER_USERNAME: ${AIRFLOW_ADMIN_USER:-admin}
      _AIRFLOW_WWW_USER_PASSWORD: ${AIRFLOW_ADMIN_PASSWORD}
      AIRFLOW__LOGGING__LOGGING_LEVEL: INFO
    ports:
      - "${AIRFLOW_PORT:-8080}:8080"
    volumes:
      - ./dags:/opt/airflow/dags
      - ./data:/opt/airflow/data
    networks:
      - finlake-net
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s
```

---

### Pattern 4: `docker/compose.metabase.yml` — Serviço Metabase

```yaml
# docker/compose.metabase.yml

services:
  metabase:
    image: metabase/metabase:latest
    profiles: ["full"]
    container_name: finlake-metabase
    restart: unless-stopped
    environment:
      MB_DB_TYPE: h2
      JAVA_TIMEZONE: America/Sao_Paulo
    ports:
      - "${METABASE_PORT:-3030}:3000"
    networks:
      - finlake-net
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
```

---

### Pattern 5: `docker/airflow/Dockerfile` — Imagem customizada Airflow

```dockerfile
FROM apache/airflow:2.10.4-python3.12

# Versão do Airflow para constraints de dependências
ARG AIRFLOW_VERSION=2.10.4
ARG PYTHON_VERSION=3.12
ARG CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

USER airflow

COPY docker/airflow/requirements.txt /opt/airflow/requirements.txt

# Instalar dependências respeitando os constraints do Airflow
RUN pip install --no-cache-dir \
    -r /opt/airflow/requirements.txt \
    --constraint "${CONSTRAINT_URL}"
```

---

### Pattern 6: `docker/postgres/init.sql` — Inicialização das databases

```sql
-- Cria database de metadados do Airflow (finlake já é criado via POSTGRES_DB)
SELECT 'CREATE DATABASE airflow_metadata'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'airflow_metadata'
)\gexec

-- Schemas iniciais da plataforma FinLake
\c finlake;

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;

COMMENT ON SCHEMA bronze IS 'Dados brutos sem transformação, particionados por data de ingestão';
COMMENT ON SCHEMA silver IS 'Dados limpos, validados, tipados e normalizados por domínio';
COMMENT ON SCHEMA gold IS 'Métricas agregadas e cruzamentos prontos para consumo';
```

---

### Pattern 7: `.env.example` — Variáveis de ambiente documentadas

```dotenv
# ============================================================
# FinLake Brasil — Environment Variables
# Copie este arquivo: cp .env.example .env
# NUNCA commite o arquivo .env
# ============================================================

# PostgreSQL
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<POSTGRES_PASSWORD>
POSTGRES_DB=finlake
POSTGRES_PORT=5432

# Airflow
AIRFLOW_ADMIN_USER=admin
AIRFLOW_ADMIN_PASSWORD=<AIRFLOW_ADMIN_PASSWORD>
# Gerar com: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
AIRFLOW__CORE__FERNET_KEY=<FERNET_KEY>
# Gerar com: python -c "import secrets; print(secrets.token_hex(32))"
AIRFLOW__WEBSERVER__SECRET_KEY=<WEBSERVER_SECRET_KEY>
AIRFLOW_PORT=8080

# Metabase
METABASE_PORT=3030

# Aplicação
FINLAKE_ENV=development
```

---

### Pattern 8: `Makefile` — Targets de conveniência

```makefile
.PHONY: up down logs ps reset help

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
	@read -p "Confirma? [y/N] " ans && [ "$$ans" = "y" ]
	docker compose down -v

.DEFAULT_GOAL := help
```

---

## Data Flow

```text
1. Desenvolvedor executa: make up PROFILE=orchestration
   │
   ▼
2. Docker Compose resolve profiles → sobe postgres + airflow
   │
   ▼
3. postgres healthcheck passa → airflow standalone inicia
   │
   ├── airflow db migrate (inicializa schema em airflow_metadata)
   ├── airflow users create (cria admin via env vars)
   ├── airflow webserver (porta 8080)
   └── airflow scheduler (monitora ./dags/)
   │
   ▼
4. DAG desenvolvida em ./dags/ é detectada pelo scheduler em < 30s
   │
   ▼
5. DAG executa → grava em PostgreSQL (bronze.* ) e/ou ./data/*.parquet
   │
   ▼
6. DuckDB lê ./data/*.parquet diretamente do host para análises Gold
```

---

## Integration Points

| Sistema Externo | Tipo | Autenticação | Notas |
|-----------------|------|--------------|-------|
| PostgreSQL (interno) | Serviço Docker via rede finlake-net | `POSTGRES_USER` + `POSTGRES_PASSWORD` via env | Acessível externamente em `localhost:5432` |
| Airflow UI | HTTP via porta exposta | `AIRFLOW_ADMIN_USER` + `AIRFLOW_ADMIN_PASSWORD` | `http://localhost:8080` |
| Metabase UI | HTTP via porta exposta | Configurado no primeiro acesso | `http://localhost:3030` |
| API BCB (futuro) | REST API pública | Sem autenticação (API aberta) | Consumido pelas DAGs em `./dags/` |
| Portal CVM (futuro) | Download HTTP de CSVs | Sem autenticação (dados abertos) | Consumido pelas DAGs em `./dags/` |

---

## Testing Strategy

| Test Type | Scope | Arquivo | Ferramentas | Critério |
|-----------|-------|---------|-------------|----------|
| Smoke test | Todos containers healthy | `make ps` | `docker compose ps` | Todos `Up (healthy)` |
| Conectividade PostgreSQL | Conexão TCP na porta 5432 | `make test` target | `pg_isready` via docker exec | Exit 0 |
| Schemas criados | Schemas bronze/silver/gold existem | `make test` target | `psql` query via docker exec | 3 schemas retornados |
| Airflow UI | HTTP 200 em `/health` | `make test` target | `curl` | Status `{"metadatabase": {"status": "healthy"}}` |
| Metabase UI | HTTP 200 em `/api/health` | `make test` target | `curl` | `{"status": "ok"}` |
| DuckDB bind mount | Acesso ao diretório `./data/` | Manual | Criar arquivo e verificar | Arquivo visível no host |
| Persistência PG | Dados sobrevivem restart | Manual | `make down && make up` | Dados preservados |
| Nenhuma credencial | Zero credenciais hardcoded | CI/CD | `grep` no repo | Zero matches |

**Target Makefile para testes automatizados:**

```makefile
test: ## Executa smoke tests nos serviços (requer 'make up' anterior)
	@echo "Testando conectividade PostgreSQL..."
	@docker exec finlake-postgres pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB)
	@echo "Verificando schemas..."
	@docker exec finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		-c "\dn" | grep -E "bronze|silver|gold"
	@echo "Testando Airflow health..."
	@curl -sf http://localhost:$(AIRFLOW_PORT:-8080)/health | python3 -m json.tool
	@echo "Testando Metabase health..."
	@curl -sf http://localhost:$(METABASE_PORT:-3030)/api/health
	@echo "✓ Todos os testes passaram."
```

---

## Error Handling

| Erro | Estratégia | Retry? |
|------|------------|--------|
| PostgreSQL não inicia (porta ocupada) | `POSTGRES_PORT` configurável via `.env`; mensagem de erro clara no `docker compose up` | Manual: alterar porta e retentar |
| Airflow falha ao conectar ao PostgreSQL | `depends_on` com `condition: service_healthy` garante ordem de inicialização | Automático: Airflow aguarda healthcheck |
| Credenciais inválidas no `.env` | Containers falham na inicialização com mensagem de erro explícita | Manual: corrigir `.env` e restartar |
| `make reset` acidental | Confirmação interativa (`read -p "Confirma? [y/N]"`) antes de executar `down -v` | N/A — ação é irreversível |
| Porta 3030 ocupada (Metabase) | `METABASE_PORT` configurável via `.env` | Manual: alterar porta |

---

## Configuration

| Variável | Tipo | Default | Descrição |
|----------|------|---------|-----------|
| `POSTGRES_USER` | string | `postgres` | Usuário do PostgreSQL |
| `POSTGRES_PASSWORD` | string | *(obrigatório)* | Senha do PostgreSQL — nunca hardcoded |
| `POSTGRES_DB` | string | `finlake` | Database principal da plataforma |
| `POSTGRES_PORT` | int | `5432` | Porta exposta do PostgreSQL no host |
| `AIRFLOW_ADMIN_USER` | string | `admin` | Login da UI do Airflow |
| `AIRFLOW_ADMIN_PASSWORD` | string | *(obrigatório)* | Senha da UI do Airflow |
| `AIRFLOW__CORE__FERNET_KEY` | string | *(obrigatório)* | Chave para criptografar conexões no Airflow |
| `AIRFLOW__WEBSERVER__SECRET_KEY` | string | *(obrigatório)* | Chave de sessão do webserver Airflow |
| `AIRFLOW_PORT` | int | `8080` | Porta exposta do Airflow no host |
| `METABASE_PORT` | int | `3030` | Porta exposta do Metabase no host |
| `FINLAKE_ENV` | string | `development` | Ambiente (development / ci / production) |

---

## Security Considerations

- Todas as credenciais via arquivo `.env` — nunca em arquivos versionados
- `.env` listado no `.gitignore`; apenas `.env.example` com placeholders é commitado
- `FERNET_KEY` e `WEBSERVER_SECRET_KEY` do Airflow devem ser gerados com entropia suficiente (instruções no `.env.example`)
- PostgreSQL exposto apenas em `localhost` (sem `0.0.0.0`) — bind na interface loopback
- `make reset` requer confirmação interativa para prevenir perda acidental de dados
- Health checks em todos os serviços previnem exposição de endpoints não inicializados

---

## Observability

| Aspecto | Implementação |
|---------|---------------|
| Logs | `docker compose logs -f` para todos os serviços; `make logs` como atalho |
| Health checks | Definidos em todos os containers com `interval`, `timeout` e `retries` |
| Status | `make ps` expõe status e portas de todos os containers |
| Airflow UI | Dashboard nativo do Airflow em `localhost:8080` para monitorar DAG runs |
| Metabase | Dashboards em `localhost:3030` para visualizar dados das camadas Silver e Gold |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-21 | design-agent | Initial version from DEFINE_INFRA_BASE.md |

---

## Next Step

**Ready for:** `/build .claude/sdd/features/DESIGN_INFRA_BASE.md`

# DEFINE: Infrastructure Base

> Infraestrutura local containerizada com Docker Compose Modular + Profiles para suportar desenvolvimento, portfólio e CI/CD do FinLake Brasil

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | INFRA_BASE |
| **Date** | 2026-04-21 |
| **Author** | define-agent |
| **Status** | ✅ Shipped |
| **Clarity Score** | 14/15 |
| **Source** | BRAINSTORM_INFRA_BASE.md |

---

## Problem Statement

O projeto FinLake Brasil não possui infraestrutura local, impossibilitando o desenvolvimento de pipelines de dados, a demonstração do portfólio para recrutadores e a execução de testes automatizados em CI/CD. É necessário um ambiente containerizado flexível onde serviços possam ser ativados seletivamente conforme o contexto de uso.

---

## Target Users

| User | Role | Pain Point |
|------|------|------------|
| Nilton Coura | Senior Data Engineer (desenvolvedor) | Sem ambiente local, não consegue desenvolver ou testar pipelines BCB e CVM |
| Recrutadores / avaliadores técnicos | Avaliadores de portfólio | Precisam rodar o projeto com um único comando e ver resultados reais sem configuração complexa |
| GitHub Actions | Sistema de CI/CD | Precisa de subconjunto leve de serviços (apenas PostgreSQL) para rodar testes sem overhead de Metabase e Airflow |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | PostgreSQL 15 disponível localmente com credenciais via `.env` |
| **MUST** | Airflow LocalExecutor acessível para orquestrar DAGs das pipelines BCB e CVM |
| **MUST** | DuckDB persistido em `./data/finlake.duckdb` com bind mount acessível localmente |
| **MUST** | Metabase disponível para visualização dos dados Gold |
| **MUST** | Profiles Docker Compose permitem subir subconjuntos de serviços por contexto |
| **MUST** | `.env.example` documenta todas as variáveis necessárias — zero credenciais hardcoded |
| **SHOULD** | `Makefile` com targets de conveniência para operações comuns |
| **SHOULD** | `./dags/` como bind mount para desenvolvimento iterativo de DAGs sem rebuild |
| **COULD** | Health checks configurados em todos os serviços |

---

## Success Criteria

- [ ] `make up` sobe todos os serviços (`--profile full`) sem erros em máquina limpa com Docker instalado
- [ ] `make up profile=core` sobe apenas PostgreSQL e o script de init do DuckDB
- [ ] PostgreSQL acessível em `postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5432/finlake`
- [ ] Airflow UI acessível em `http://localhost:8080` com login via variáveis de ambiente
- [ ] Metabase acessível em `http://localhost:3030`
- [ ] `./data/finlake.duckdb` criado após `make up` com bind mount funcional
- [ ] `./data/` listado no `.gitignore`; apenas `./data/.gitkeep` versionado
- [ ] `.env.example` contém todas as variáveis com valores de exemplo (não reais)
- [ ] Nenhuma credencial presente em qualquer arquivo versionado

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Subida completa em máquina limpa | Docker instalado, `.env` criado a partir de `.env.example` | `make up` executado | Todos os serviços sobem sem erros; PostgreSQL, Airflow e Metabase acessíveis nas portas configuradas |
| AT-002 | Subida seletiva — profile core | Docker instalado, `.env` configurado | `make up profile=core` | Apenas PostgreSQL sobe; Airflow e Metabase não são iniciados |
| AT-003 | Persistência do DuckDB | Serviços rodando | `make down && make up` | `./data/finlake.duckdb` persiste entre restarts; dados não são perdidos |
| AT-004 | Nenhuma credencial hardcoded | Repositório clonado | `grep -r "password\|secret\|token" docker/ .env.example Makefile` (excluindo placeholders) | Zero ocorrências de credenciais reais; apenas placeholders como `<POSTGRES_PASSWORD>` |
| AT-005 | Reset limpo | Serviços rodando com dados | `make reset` | Todos os containers parados, volumes nomeados removidos, `./data/` preservado |

---

## Out of Scope

- **LangFuse** — observabilidade de LLM; adicionar quando agentes estiverem implementados
- **pgAdmin / Adminer** — ferramentas de admin de banco; Nilton usa psql/DBeaver
- **Redis** — dependência do CeleryExecutor; descartado em favor do LocalExecutor
- **CeleryExecutor / Flower** — over-engineering para workloads batch diários
- **SSL/TLS local** — não necessário para desenvolvimento local
- **Ambiente de produção** — este spec cobre apenas local + CI/CD
- **Ingestão de dados** — pipelines BCB e CVM são features separadas

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Técnico | Deve rodar em macOS (Darwin) e Linux (Ubuntu no GitHub Actions) | Evitar comandos ou paths específicos de OS; usar `docker compose` v2 (sem hífen) |
| Técnico | Airflow: LocalExecutor apenas | Sem Redis, sem workers extras; 1 container Airflow |
| Técnico | Python 3.12 como runtime das imagens customizadas | Base image: `python:3.12-slim` ou `apache/airflow:2.x-python3.12` |
| Técnico | Gerenciamento de pacotes via `uv` | Airflow image customizada deve ter `uv` instalado para instalar dependências |
| Segurança | Nenhuma credencial hardcoded | Todas as variáveis sensíveis via `.env` (não versionado); `.env.example` com placeholders |
| Portfólio | `make up` deve funcionar com um único comando após `cp .env.example .env` | DX de onboarding deve ser mínima para avaliadores externos |

---

## Technical Context

| Aspect | Value | Notes |
|--------|-------|-------|
| **Deployment Location** | Raiz do projeto + `docker/` | `docker-compose.yml` na raiz; arquivos de serviço em `docker/` |
| **KB Domains** | docker, airflow, postgresql | Patterns de Compose Profiles, Airflow LocalExecutor, PostgreSQL init scripts |
| **IaC Impact** | New resources | Docker Compose é o IaC local; sem impacto em cloud |

**Estrutura de arquivos esperada:**

```
finlake-brasil/
├── docker/
│   ├── compose.postgres.yml      # PostgreSQL 15 com volume nomeado
│   ├── compose.airflow.yml       # Airflow LocalExecutor + bind mount ./dags/
│   ├── compose.metabase.yml      # Metabase porta 3030
│   └── compose.duckdb.yml        # Init script + bind mount ./data/
├── docker-compose.yml            # Orquestrador: include + profiles
├── .env.example                  # Todas as variáveis documentadas com placeholders
├── Makefile                      # Targets: up, down, logs, ps, reset
├── dags/                         # Bind mount Airflow — DAGs versionados
│   └── .gitkeep
└── data/
    └── .gitkeep                  # Diretório versionado, dados ignorados
```

**Docker Compose Profiles:**

| Profile | Serviços | Uso |
|---------|----------|-----|
| `core` | PostgreSQL | Testes unitários em CI/CD |
| `orchestration` | PostgreSQL + Airflow | Desenvolvimento de pipelines |
| `full` | PostgreSQL + Airflow + Metabase | Demo completa / desenvolvimento com dashboards |

**Makefile targets:**

| Target | Comando equivalente | Descrição |
|--------|---------------------|-----------|
| `make up` | `docker compose --profile full up -d` | Sobe todos os serviços |
| `make up profile=core` | `docker compose --profile core up -d` | Sobe profile específico |
| `make down` | `docker compose down` | Para todos os containers |
| `make logs` | `docker compose logs -f` | Stream de logs |
| `make ps` | `docker compose ps` | Status dos serviços |
| `make reset` | `docker compose down -v` | Para containers e remove volumes nomeados |

---

## Data Contract

> N/A para este feature — infraestrutura base não processa dados. Contratos de dados serão definidos nas features de ingestão BCB e CVM.

---

## Assumptions

| ID | Assumption | If Wrong, Impact | Validated? |
|----|------------|------------------|------------|
| A-001 | Docker Desktop (Mac) / Docker Engine (Linux) já está instalado no ambiente do desenvolvedor | Setup inicial mais complexo, necessário adicionar instruções de instalação do Docker no README | [ ] |
| A-002 | Portas 5432, 8080 e 3030 estão disponíveis na máquina local | Necessário parametrizar portas via variáveis de ambiente no `.env` | [ ] |
| A-003 | `uv` pode ser instalado dentro da imagem Airflow customizada sem conflito com o sistema de pacotes da imagem base | Pode ser necessário usar `pip` com `constraints.txt` do Airflow em vez de `uv` | [ ] |
| A-004 | Airflow 2.x com LocalExecutor suporta as DAGs que serão desenvolvidas para BCB e CVM | Se DAGs exigirem paralelismo extensivo, LocalExecutor pode ser gargalo — revisar quando pipelines estiverem implementadas | [ ] |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Específico, contextualizado nos três casos de uso (dev, portfólio, CI/CD) |
| Users | 3 | Três personas com roles e pain points claros, incluindo GitHub Actions como "usuário" |
| Goals | 3 | Priorizados em MUST/SHOULD/COULD, todos derivados diretamente das personas |
| Success | 2 | Critérios testáveis e objetivos; sem SLA de tempo de startup (não crítico para MVP) |
| Scope | 3 | Out-of-scope explicitamente validado durante brainstorm com YAGNI aplicado |
| **Total** | **14/15** | |

---

## Open Questions

- **A-003:** Compatibilidade de `uv` com a imagem base do Airflow precisa ser validada antes do Design. Se incompatível, usar `pip` com `apache-airflow-constraints-*.txt`.
- **A-002:** Confirmar se portas devem ser hardcoded no Compose ou parametrizadas via `.env` desde o início (recomendo parametrizar para portfólio).

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-21 | define-agent | Initial version from BRAINSTORM_INFRA_BASE.md |

---

## Next Step

**Ready for:** `/design .claude/sdd/features/DEFINE_INFRA_BASE.md`

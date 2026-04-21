# BRAINSTORM: Infrastructure Base

> Exploratory session to clarify intent and approach before requirements capture

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | INFRA_BASE |
| **Date** | 2026-04-21 |
| **Author** | brainstorm-agent |
| **Status** | Ready for Define |

---

## Initial Idea

**Raw Input:** Infraestrutura base — Docker Compose com PostgreSQL, Airflow, Metabase e DuckDB configurados e prontos

**Context Gathered:**
- Projeto FinLake Brasil em fase inicial — apenas CLAUDE.md, README.md e .gitignore commitados
- Nenhum código de pipeline ou infraestrutura existe ainda
- Stack definida no CLAUDE.md: Python 3.12, PostgreSQL 15, DuckDB, Airflow, Metabase, Docker Compose, uv

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | Raiz do projeto + `docker/` | Compose files em `docker/`, orquestrador na raiz |
| Storage | PostgreSQL com volume nomeado, DuckDB + Parquet com bind mount em `./data/` | Dados não commitados, arquivos locais inspecionáveis |
| Orchestration | Airflow LocalExecutor | Sem Redis/Celery — mais leve para dev local e CI/CD |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Qual é o objetivo principal ao montar essa infraestrutura? | Todos: dev local, portfólio/demo, base para CI/CD | Infraestrutura deve ser flexível e servir múltiplos contextos |
| 2 | Qual setup de Airflow prefere? | Recomendação aceita: LocalExecutor | 1 container Airflow, sem Redis, sem workers extras |
| 3 | Como tratar volumes Docker? | Híbrido: PostgreSQL com volume nomeado, DuckDB/Parquet com bind mount em `./data/` | Dados de banco isolados do filesystem, arquivos de dados visíveis e inspecionáveis |

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Compose de referência | N/A | 0 | Construído do zero |
| .env.example de referência | N/A | 0 | Construído do zero |
| Requirements/pyproject | N/A | 0 | Ainda não existe no projeto |

**Observação:** Sem amostras disponíveis. Infraestrutura será criada com base nas especificações do CLAUDE.md e boas práticas.

---

## Approaches Explored

### Approach A: Docker Compose Modular com Profiles + Makefile ⭐ Recommended

**Description:** Cada serviço em arquivo Compose dedicado (`compose.postgres.yml`, `compose.airflow.yml`, etc.), orquestrado por um `docker-compose.yml` principal via `include`. Docker Compose Profiles permitem subir subconjuntos de serviços. Makefile de conveniência por cima.

**Pros:**
- Sobe apenas o necessário em cada contexto (`--profile core`, `--profile orchestration`, `--profile full`)
- CI/CD pode subir só PostgreSQL para testes, sem overhead de Metabase e Airflow
- Alinha com princípio de isolamento do Data Mesh
- Fácil de adicionar novos serviços sem poluir o arquivo principal

**Cons:**
- Mais arquivos para manter
- Curva inicial levemente maior para quem não conhece `include` e profiles

**Why Recommended:** Abordagem Staff-level de plataforma de dados. Isolamento por serviço, flexibilidade para CI/CD, extensível para novos domínios.

---

### Approach B: Docker Compose Único Monolítico

**Description:** Tudo em um `docker-compose.yml`. Sobe tudo ou nada.

**Pros:**
- Simples, um arquivo, fácil de entender de relance

**Cons:**
- Pesado no CI/CD
- Sem flexibilidade para subir serviços seletivamente
- Cresce sem controle conforme o projeto evolui

---

### Approach C: Makefile + Docker Compose Simples

**Description:** `docker-compose.yml` único com Makefile com targets como `make dev`, `make test`.

**Pros:**
- DX boa, comandos legíveis no README

**Cons:**
- Não resolve seletividade de serviços no CI/CD
- Makefile adiciona artefato extra sem resolver o problema central

---

## Data Engineering Context

### Source Systems
| Source | Type | Volume Estimate | Current Freshness |
|--------|------|-----------------|-------------------|
| PostgreSQL 15 | OLTP / Bronze storage | Baixo inicialmente | Daily |
| DuckDB | Analytical / Gold layer | Crescimento gradual | On-demand |

### Data Flow Sketch
```text
[BCB API / CVM CSV] → [Ingestão Python] → [PostgreSQL Bronze] → [dbt Silver] → [DuckDB Gold] → [Metabase]
```

### Key Data Questions Explored
| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Volume esperado? | Baixo (dados financeiros diários, não streaming) | LocalExecutor é suficiente |
| 2 | Quem consome o output? | Metabase dashboards + análises ad-hoc via DuckDB | Metabase precisa acessar PostgreSQL e DuckDB |
| 3 | Freshness SLA? | Daily batch | Airflow com schedule diário, sem necessidade de streaming |

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A + Makefile |
| **User Confirmation** | 2026-04-21 |
| **Reasoning** | Isolamento por serviço alinha com Data Mesh, flexibilidade no CI/CD é requisito, Makefile melhora DX sem custo estrutural |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Airflow LocalExecutor | Suficiente para workloads batch diários, mais leve em dev e CI/CD | CeleryExecutor (over-engineering), Astro CLI (obscurece Airflow puro) |
| 2 | Volumes híbridos | PostgreSQL isolado do filesystem, dados analíticos inspecionáveis localmente | Tudo em volumes nomeados (opaco), tudo em bind mounts (risco de commitar dados) |
| 3 | Docker Compose Profiles | Flexibilidade para subir subconjuntos de serviços por contexto | Compose monolítico (sem flexibilidade), Makefile puro (não resolve seletividade) |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| LangFuse | Observabilidade de LLM — sem valor até agentes estarem rodando | Sim |
| pgAdmin / Adminer | Nilton já usa psql/DBeaver; overhead sem benefício no MVP | Sim |
| Redis | Dependência do CeleryExecutor, descartado em favor do LocalExecutor | Sim, se escalar |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Escopo de serviços (YAGNI) | ✅ | Aprovado sem alterações | Não |
| Estrutura de arquivos e profiles | ✅ | Aprovado sem alterações | Não |

---

## Suggested Requirements for /define

### Problem Statement (Draft)
O projeto FinLake Brasil precisa de uma infraestrutura local containerizada que suporte desenvolvimento de pipelines, demonstração de portfólio e execução de testes em CI/CD, com serviços isolados e ativáveis seletivamente.

### Target Users (Draft)
| User | Pain Point |
|------|------------|
| Nilton (engenheiro) | Precisa de ambiente local funcional para desenvolver pipelines BCB e CVM |
| Recrutadores / avaliadores | Precisam conseguir rodar o projeto com um único comando e ver resultados reais |
| GitHub Actions (CI/CD) | Precisa de subconjunto leve de serviços para rodar testes automatizados |

### Success Criteria (Draft)
- [ ] `make up` sobe todos os serviços sem erros em ambiente limpo
- [ ] `make up profile=core` sobe apenas PostgreSQL e DuckDB
- [ ] PostgreSQL acessível em `localhost:5432` com credenciais do `.env`
- [ ] Airflow UI acessível em `localhost:8080`
- [ ] Metabase acessível em `localhost:3030`
- [ ] DuckDB persistido em `./data/finlake.duckdb`
- [ ] `./data/` no `.gitignore`, apenas `.gitkeep` versionado
- [ ] `.env.example` com todas as variáveis documentadas

### Constraints Identified
- Deve rodar em macOS (Darwin) e Linux (CI/CD)
- Airflow: LocalExecutor apenas
- Python 3.12 como runtime padrão
- Gerenciamento de pacotes via `uv`
- Nenhuma credencial hardcoded — tudo via `.env`

### Out of Scope (Confirmed)
- LangFuse (adicionar quando houver agentes)
- pgAdmin / Adminer
- Redis / CeleryExecutor
- SSL/TLS local
- Ambiente de produção (este spec é apenas para local + CI)

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 4 (3 discovery + 1 samples) |
| Approaches Explored | 3 |
| Features Removed (YAGNI) | 3 |
| Validations Completed | 2 |
| Duration | ~15 min |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_INFRA_BASE.md`

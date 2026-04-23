# DEFINE: Bronze BCB — Ingestão de Séries Temporais do Banco Central

> DAG Airflow com smart first run que ingere SELIC, IPCA e PTAX do BCB
> para o schema `bronze_bcb` no PostgreSQL com idempotência completa.

## Metadata

| Atributo          | Valor                                           |
|-------------------|-------------------------------------------------|
| **Feature**       | BRONZE_BCB                                      |
| **Data**          | 2026-04-23                                      |
| **Autor**         | Nilton Coura                                    |
| **Status**        | ✅ Shipped                                      |
| **Clarity Score** | 14/15                                           |
| **Origem**        | BRAINSTORM_BRONZE_BCB.md (2026-04-22)           |

---

## Problem Statement

A plataforma FinLake Brasil não possui dados financeiros ingeridos: a camada
Bronze do domínio BCB está vazia, tornando impossível qualquer pipeline
downstream (Silver, Gold, dashboards Metabase). Sem SELIC, IPCA e PTAX
históricos carregados de forma confiável e idempotente, não há base para
análise macroeconômica nem para evolução do Data Mesh.

---

## Target Users

| Usuário                  | Papel                                    | Pain Point                                                                |
|--------------------------|------------------------------------------|---------------------------------------------------------------------------|
| Nilton Coura             | Data Engineer / dono da plataforma       | Sem dados na Bronze, nenhuma pipeline posterior pode ser desenvolvida      |
| Analista / Metabase      | Consumidor de dashboards Gold            | Sem dados históricos de SELIC/IPCA/PTAX, não há métricas para visualizar  |
| Pipeline Silver/Gold     | Consumidor downstream automatizado       | Depende da Bronze populada para executar transformações e agregações       |

---

## Goals

| Prioridade | Goal                                                                                       |
|------------|--------------------------------------------------------------------------------------------|
| **MUST**   | DAG `dag_bronze_bcb` operacional com 3 tasks paralelas e schedule diário                  |
| **MUST**   | Smart first run: backfill automático desde `start_date` configurado por série              |
| **MUST**   | Idempotência garantida: reprocessamento seguro sem duplicatas                              |
| **MUST**   | Schema `bronze_bcb` criado via migration SQL versionada                                    |
| **MUST**   | Pré-requisitos de infraestrutura provisionados (provider Postgres + connection string)     |
| **SHOULD** | Lógica de skip para IPCA quando mês corrente já gravado (`AirflowSkipException`)           |
| **SHOULD** | Colunas de auditoria `ingested_at` e `source_api` em todas as tabelas                     |
| **COULD**  | Testes unitários para `get_load_range()` e funções de transformação                       |

---

## Success Criteria

- [ ] `dag_bronze_bcb` aparece na UI do Airflow (`localhost:8080`) sem erros de parse
- [ ] Primeira execução popula `bronze_bcb.selic_daily` com dados desde `2000-01-01`
- [ ] Primeira execução popula `bronze_bcb.ipca_monthly` com dados desde `1994-07-01`
- [ ] Primeira execução popula `bronze_bcb.ptax_daily` com dados desde `1999-01-01`
- [ ] Segunda execução no mesmo dia não insere registros duplicados
- [ ] `SELECT COUNT(*) FROM bronze_bcb.selic_daily` retorna ≥ 6.000 registros após backfill
- [ ] `SELECT COUNT(*) FROM bronze_bcb.ipca_monthly` retorna ≥ 380 registros após backfill
- [ ] `SELECT COUNT(*) FROM bronze_bcb.ptax_daily` retorna ≥ 6.000 registros após backfill
- [ ] Falha em uma task não cancela as demais (tasks independentes)
- [ ] Zero credenciais hardcoded no código

---

## Acceptance Tests

| ID     | Cenário                              | Given                                                    | When                                            | Then                                                                    |
|--------|--------------------------------------|----------------------------------------------------------|-------------------------------------------------|-------------------------------------------------------------------------|
| AT-001 | Backfill no primeiro run             | Tabelas `bronze_bcb.*` vazias                            | `dag_bronze_bcb` executada pela primeira vez    | Tabelas populadas desde `start_date` de cada série até hoje             |
| AT-002 | Incremental no segundo run           | Tabelas com dados históricos até D-1                     | `dag_bronze_bcb` executada no dia D             | Apenas registro do dia D inserido (ou dados faltantes); sem duplicatas  |
| AT-003 | Idempotência por reprocessamento     | Tabelas com dados do dia corrente                        | DAG executada duas vezes no mesmo dia           | Zero registros duplicados; segunda execução finaliza com `success`      |
| AT-004 | IPCA — skip quando mês já gravado   | `ipca_monthly` tem registro para o mês corrente          | Task `ingest_ipca_monthly` executa              | Task finaliza como `Skipped`; nenhum dado sobrescrito                   |
| AT-005 | Tasks paralelas e independentes      | Task `ingest_selic_daily` falha (API indisponível)       | DAG executa                                     | Tasks `ingest_ipca_monthly` e `ingest_ptax_daily` completam normalmente |
| AT-006 | Autenticação via variável de ambiente| `AIRFLOW_CONN_FINLAKE_POSTGRES` configurada no container | Qualquer task executa                           | Conexão estabelecida sem credenciais hardcoded no código                |
| AT-007 | Migration cria schema e tabelas      | PostgreSQL sem schema `bronze_bcb`                       | Migration `001_bronze_bcb.sql` executada        | Schema e 3 tabelas criados com PKs, defaults e tipos NUMERIC corretos   |

---

## Out of Scope

- **Parquet files paralelos ao PostgreSQL** — deferido para feature separada; DuckDB lê direto do Postgres no MVP
- **Tabela de controle `pipeline_runs`** — Airflow persiste execução, duração e status nativamente
- **Great Expectations na Bronze** — validação é concern da camada Silver
- **Alertas por e-mail/Slack** — configuração de destino é concern de operações
- **Camada Silver/Gold para BCB** — pipelines downstream são features separadas
- **Domínio CVM** — schema `bronze_cvm` e respectivas DAGs são features futuras

---

## Constraints

| Tipo        | Constraint                                                                 | Impacto                                                           |
|-------------|----------------------------------------------------------------------------|-------------------------------------------------------------------|
| Técnico     | Airflow standalone 2.10.4 — `LocalExecutor`, sem Celery                   | Tasks paralelas executam em threads do mesmo processo; sem worker |
| Técnico     | PostgreSQL 15 acessível internamente em `postgres:5432` (não localhost)   | Connection string do `PostgresHook` usa host `postgres`           |
| Técnico     | Imagem Airflow customizada requer rebuild após mudança em `requirements.txt` | `make down && make up` necessário para ativar novo provider       |
| Técnico     | API BCB SGS sem autenticação, mas com rate limiting não documentado        | `python-bcb` abstrai a API; falhas transitórias tratadas pelo retry do Airflow |
| Portfólio   | Código deve demonstrar padrões de Staff Engineer (type hints, docstrings)  | Todos os módulos Python seguem PEP8 + type hints + docstrings     |

---

## Technical Context

| Aspecto               | Valor                                                      | Notas                                                             |
|-----------------------|------------------------------------------------------------|-------------------------------------------------------------------|
| **Deployment Location** | `dags/domain_bcb/`                                       | Bind mount `./dags/` → `/opt/airflow/dags` no container Airflow   |
| **Migration Location**  | `docker/postgres/migrations/001_bronze_bcb.sql`          | Executada manualmente ou via `make migrate` (a definir no Design) |
| **IaC Impact**          | Modify existing                                          | `requirements.txt`, `.env.example`, `compose.airflow.yml`         |
| **Provider necessário** | `apache-airflow-providers-postgres`                      | Ausente no `requirements.txt` atual — PRE-01 bloqueante           |

---

## Data Contract

### Source Inventory

| Source          | Tipo | Series BCB (SGS) | Volume estimado  | Frequência | Owner       |
|-----------------|------|------------------|------------------|------------|-------------|
| BCB SGS API     | REST | SELIC: 11        | ~260 registros/ano | Diária (dias úteis) | BCB público |
| BCB SGS API     | REST | IPCA: 433        | ~12 registros/ano  | Mensal     | BCB público |
| BCB SGS API     | REST | PTAX venda: 1    | ~260 registros/ano | Diária (dias úteis) | BCB público |

### Schema Contract — `bronze_bcb.selic_daily`

| Coluna       | Tipo           | Constraints                    | PII? |
|--------------|----------------|--------------------------------|------|
| date         | DATE           | NOT NULL, PRIMARY KEY          | Não  |
| valor        | NUMERIC(10,6)  | NOT NULL                       | Não  |
| ingested_at  | TIMESTAMP      | NOT NULL, DEFAULT NOW()        | Não  |
| source_api   | VARCHAR(50)    | NOT NULL, DEFAULT 'BCB_SGS'   | Não  |

### Schema Contract — `bronze_bcb.ipca_monthly`

| Coluna       | Tipo           | Constraints                    | PII? |
|--------------|----------------|--------------------------------|------|
| date         | DATE           | NOT NULL, PRIMARY KEY          | Não  |
| valor        | NUMERIC(6,4)   | NOT NULL                       | Não  |
| ingested_at  | TIMESTAMP      | NOT NULL, DEFAULT NOW()        | Não  |
| source_api   | VARCHAR(50)    | NOT NULL, DEFAULT 'BCB_SGS'   | Não  |

### Schema Contract — `bronze_bcb.ptax_daily`

| Coluna       | Tipo           | Constraints                    | PII? |
|--------------|----------------|--------------------------------|------|
| date         | DATE           | NOT NULL, PRIMARY KEY          | Não  |
| valor        | NUMERIC(10,4)  | NOT NULL                       | Não  |
| ingested_at  | TIMESTAMP      | NOT NULL, DEFAULT NOW()        | Não  |
| source_api   | VARCHAR(50)    | NOT NULL, DEFAULT 'BCB_SGS'   | Não  |

### Freshness SLAs

| Camada  | Target                                      | Medição                                     |
|---------|---------------------------------------------|---------------------------------------------|
| Bronze  | Dados do dia D disponíveis até 08:00 BRT D  | `MAX(date)` deve ser ≥ D-1 após DAG diária  |
| IPCA    | Dado do mês M disponível até dia 15 de M    | `MAX(date)` deve refletir mês corrente      |

### Completeness Metrics

- Zero registros com `valor IS NULL` em qualquer tabela Bronze
- `COUNT(*)` por ano em `selic_daily` e `ptax_daily` deve ser ≥ 240 (mínimo de dias úteis anuais)
- `COUNT(*)` por ano em `ipca_monthly` deve ser = 12

---

## Assumptions

| ID    | Assumption                                                                     | Se errado, impacto                                                      | Validado? |
|-------|--------------------------------------------------------------------------------|-------------------------------------------------------------------------|-----------|
| A-001 | API BCB SGS disponível durante execução da DAG (sem SLA publicado)            | Task falha; Airflow reprocessa no próximo ciclo com retry configurado   | [ ]       |
| A-002 | `python-bcb` retorna `DatetimeIndex` + `float64` (confirmado via grounding)   | Código de conversão quebra; isolado no `bcb_client.py`                  | [x]       |
| A-003 | Volume histórico total (~13.000 registros) cabe em memória sem timeout        | Precisaria de chunking por período; risco baixo dado tamanho dos dados  | [ ]       |
| A-004 | PostgreSQL acessível em `postgres:5432` dentro da rede Docker durante execução | Todas as tasks falham; verificar `make ps` antes de triggar a DAG       | [ ]       |
| A-005 | `apache-airflow-providers-postgres` compatível com Airflow 2.10.4             | Possível conflito de versão; resolver fixando versão no `requirements.txt` | [ ]    |

---

## Pré-requisitos Bloqueantes

### PRE-01 — `apache-airflow-providers-postgres` em `requirements.txt`

```
# docker/airflow/requirements.txt
apache-airflow-providers-postgres>=5.0.0
```

Requer rebuild da imagem (`make down && make up`) para ativar o provider.

### PRE-02 — `AIRFLOW_CONN_FINLAKE_POSTGRES` declarada e injetada

**`.env` e `.env.example`:**
```dotenv
# Airflow Connections — host interno Docker, não localhost
AIRFLOW_CONN_FINLAKE_POSTGRES=postgresql://postgres:<POSTGRES_PASSWORD>@postgres:5432/finlake
```

**`docker/compose.airflow.yml`** — seção `environment` do serviço airflow:
```yaml
AIRFLOW_CONN_FINLAKE_POSTGRES: "${AIRFLOW_CONN_FINLAKE_POSTGRES}"
```

> Crítico: `postgres:5432` é o host interno Docker. Usar `localhost:5433`
> resulta em falha silenciosa de conexão em runtime.

---

## Clarity Score Breakdown

| Elemento | Score | Justificativa                                                              |
|----------|-------|----------------------------------------------------------------------------|
| Problem  | 3/3   | Específico: Bronze vazia bloqueia toda a plataforma downstream            |
| Users    | 2/3   | Data Engineer explícito; analistas e pipelines downstream implícitos       |
| Goals    | 3/3   | Priorizados com MUST/SHOULD/COULD e mensuráveis                           |
| Success  | 3/3   | Critérios testáveis com números (≥6.000 registros, zero duplicatas)       |
| Scope    | 3/3   | Out-of-scope explícito; YAGNI aplicado com 4 features removidas           |
| **Total**| **14/15** |                                                                        |

**Mínimo para prosseguir: 12/15 ✅**

---

## Open Questions

Nenhuma — pronto para Design.

As suposições A-001, A-003, A-004 e A-005 devem ser validadas durante a
fase de Design ou no início do Build, mas não bloqueiam a especificação.

---

## Revision History

| Versão | Data       | Autor        | Mudanças                    |
|--------|------------|--------------|-----------------------------|
| 1.0    | 2026-04-23 | define-agent | Versão inicial from BRAINSTORM_BRONZE_BCB.md |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_BRONZE_BCB.md`

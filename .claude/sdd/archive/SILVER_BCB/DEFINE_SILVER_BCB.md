# DEFINE: Silver BCB — Transformação e Validação de Séries Temporais

> Setup inicial do dbt no FinLake Brasil + 3 modelos Silver com indicadores
> derivados (taxa_anual, acumulado_12m, variacao_diaria_pct) e DAG Airflow
> orquestrando dbt run após Bronze.

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | SILVER_BCB                                       |
| **Data**          | 2026-04-24                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | ✅ Shipped                                       |
| **Clarity Score** | 14/15                                            |
| **Origem**        | BRAINSTORM_SILVER_BCB.md (2026-04-24)            |
| **Upstream**      | BRONZE_BCB (shipped 2026-04-23)                  |

---

## Problem Statement

A camada Silver do domínio BCB está ausente: dados brutos da Bronze
(`bronze_bcb`) não têm transformações, indicadores derivados nem validações
de qualidade, tornando-os inutilizáveis diretamente para dashboards Metabase
ou pipelines Gold. Adicionalmente, dbt-core — previsto na stack desde o início
— não está inicializado no projeto, bloqueando toda a estratégia de
transformação baseada em SQL versionado e testado.

---

## Target Users

| Usuário               | Papel                                  | Pain Point                                                               |
|-----------------------|----------------------------------------|--------------------------------------------------------------------------|
| Nilton Coura          | Data Engineer / dono da plataforma     | Bronze com dados brutos não consumíveis; dbt bloqueado sem projeto setup |
| Dashboard / Metabase  | Consumidor de métricas macroeconômicas | Sem `taxa_anual` da SELIC e `acumulado_12m` do IPCA, análises ficam incompletas |
| Pipeline Gold         | Consumidor downstream automatizado     | Depende de Silver com tipos corretos e colunas derivadas para cruzamentos |

---

## Goals

| Prioridade | Goal                                                                                        |
|------------|---------------------------------------------------------------------------------------------|
| **MUST**   | Inicializar projeto dbt em `transform/` com `dbt_project.yml` e `profiles.yml`             |
| **MUST**   | 3 modelos dbt: `selic_daily`, `ipca_monthly`, `ptax_daily` materializados como `table`     |
| **MUST**   | Schema `silver_bcb` criado via migration SQL `002_silver_bcb.sql`                          |
| **MUST**   | `dbt test` com zero failures: `not_null` + `unique` em `date` para todos os modelos        |
| **MUST**   | DAG `dag_silver_bcb` com `ExternalTaskSensor` + `BashOperator`                             |
| **MUST**   | Pré-requisitos de infraestrutura provisionados (dbt-postgres, bind mount, profiles)         |
| **SHOULD** | `sources.yml` com `freshness` config para monitorar atualização da Bronze                  |
| **SHOULD** | `schema.yml` com documentação de NULLs esperados em colunas derivadas                      |
| **COULD**  | Testes unitários Python para validar as fórmulas SQL com valores conhecidos                |

---

## Success Criteria

- [ ] `dbt run --select domain_bcb --target airflow` executa sem erros dentro do container
- [ ] Tabelas `silver_bcb.selic_daily`, `silver_bcb.ipca_monthly`, `silver_bcb.ptax_daily` criadas com colunas corretas
- [ ] `dbt test` retorna `0 failures, 0 errors` para todos os modelos
- [ ] `silver_bcb.selic_daily.taxa_anual` ≈ `14.65` para `taxa_diaria = 0.054266` (SELIC atual)
- [ ] `silver_bcb.ipca_monthly.acumulado_12m` é NULL para os primeiros 11 meses e não-NULL a partir de 1995-06-01
- [ ] `silver_bcb.ptax_daily.variacao_diaria_pct` é NULL apenas no primeiro registro histórico (1999-01-04)
- [ ] DAG `dag_silver_bcb` aparece na UI do Airflow sem erros de parse
- [ ] `ExternalTaskSensor` aguarda conclusão de `dag_bronze_bcb` antes do `dbt run`
- [ ] Zero credenciais hardcoded em `profiles.yml` (usa `env_var()` do dbt)

---

## Acceptance Tests

| ID     | Cenário                                        | Given                                              | When                                          | Then                                                               |
|--------|------------------------------------------------|----------------------------------------------------|-----------------------------------------------|--------------------------------------------------------------------|
| AT-001 | `dbt run` cria tabelas Silver                  | Schema `silver_bcb` existe, Bronze populada        | `dbt run --select domain_bcb` executado        | 3 tabelas criadas com todas as colunas e sem erros                 |
| AT-002 | `dbt test` 0 failures                          | Tabelas Silver criadas pelo AT-001                 | `dbt test --select domain_bcb` executado       | `0 failures, 0 errors, 0 warnings`                                 |
| AT-003 | Fórmula SELIC validada                         | `taxa_diaria = 0.054266` em `selic_daily`          | Query em `silver_bcb.selic_daily`              | `taxa_anual` entre `14.60` e `14.70` para esse registro            |
| AT-004 | `acumulado_12m` NULL nos primeiros 11 meses    | `ipca_monthly` com dados desde 1994-07-01          | Query em `silver_bcb.ipca_monthly`             | Registros de 1994-07 a 1995-05 têm `acumulado_12m IS NULL`         |
| AT-005 | `variacao_diaria_pct` NULL apenas no primeiro  | `ptax_daily` com dados desde 1999-01-04            | Query em `silver_bcb.ptax_daily`               | Apenas o registro mais antigo tem `variacao_diaria_pct IS NULL`    |
| AT-006 | ExternalTaskSensor aguarda Bronze              | `dag_bronze_bcb` ainda em execução                 | `dag_silver_bcb` triggada                     | `wait_bronze_bcb` permanece em `up_for_reschedule` até Bronze completar |
| AT-007 | BashOperator executa `dbt run`                 | Bronze completa, `wait_bronze_bcb` success         | Task `dbt_run_silver_bcb` executa              | Log mostra `dbt run` com `3 of 3 OK` e task finaliza como success  |
| AT-008 | `profiles.yml` sem hardcode                    | `.env` com `POSTGRES_USER` e `POSTGRES_PASSWORD`  | `dbt debug --target airflow` no container      | Conexão bem-sucedida sem credenciais no arquivo `profiles.yml`     |
| AT-009 | Migration idempotente                          | Schema `silver_bcb` já existente                   | `002_silver_bcb.sql` executado novamente       | Nenhum erro — `IF NOT EXISTS` em todas as operações                |

---

## Out of Scope

- **`indice_base100` do IPCA** — cálculo cumulativo desde 1994 como índice base 100; concern analítico da Gold layer
- **`astronomer-cosmos`** — deferido para quando o projeto dbt crescer para 10+ modelos com CVM
- **`dbt docs generate/serve`** — documentação de portfólio, não pipeline; deferido
- **`dbt snapshot` (SCD Type 2)** — séries temporais são imutáveis por design
- **`dbt seeds`** — nenhum dado de referência CSV no domínio BCB
- **Outlier detection como dbt test** — séries macroeconômicas requerem contexto histórico; concern de observabilidade
- **Multiple environments (staging/prod)** — apenas `dev` (local) e `airflow` (container)
- **Domínio CVM Silver** — feature futura e independente

---

## Constraints

| Tipo       | Constraint                                                                    | Impacto                                                       |
|------------|-------------------------------------------------------------------------------|---------------------------------------------------------------|
| Técnico    | dbt não instalado na imagem Airflow — requer rebuild                          | `make down && make up` obrigatório após PRE-01                |
| Técnico    | `profiles.yml` precisa de dois targets: `dev` (localhost:5433) e `airflow` (postgres:5432) | Credenciais idênticas, hosts diferentes por ambiente |
| Técnico    | `EXP(SUM(LN()))` pode ter comportamento inesperado se `variacao_mensal` for negativo | IPCA historicamente sempre positivo desde 1994-07 — risco baixo |
| Técnico    | `ExternalTaskSensor` com `execution_date` exato requer que ambas as DAGs usem o mesmo schedule e `start_date` | A configurar no Design |
| Portfólio  | SQL dbt deve ser legível e comentado com a fórmula financeira                | Demonstra domínio de negócio + habilidade técnica             |

---

## Technical Context

| Aspecto               | Valor                                                   | Notas                                                            |
|-----------------------|---------------------------------------------------------|------------------------------------------------------------------|
| **Deployment Location** | `transform/models/domain_bcb/` (modelos dbt)         | `transform/` novo diretório na raiz do projeto                   |
| **DAG Location**      | `dags/domain_bcb/dag_silver_bcb.py`                    | Mesmo pacote Python do domínio BCB                               |
| **Migration Location**| `docker/postgres/migrations/002_silver_bcb.sql`        | Segue convenção estabelecida em BRONZE_BCB                       |
| **IaC Impact**        | Modify existing                                        | `requirements.txt`, `compose.airflow.yml` (bind mount + env var) |
| **dbt Adapter**       | `dbt-postgres`                                         | Mesmo PostgreSQL da Bronze; DuckDB reservado para Gold           |

---

## Data Contract

### Source Inventory

| Source                      | Tipo     | Volume estimado     | Freshness          | Owner       |
|-----------------------------|----------|---------------------|--------------------|-------------|
| `bronze_bcb.selic_daily`    | Postgres | ~6.600 registros    | D-1 (dias úteis)   | domain_bcb  |
| `bronze_bcb.ipca_monthly`   | Postgres | ~381 registros      | Mensal             | domain_bcb  |
| `bronze_bcb.ptax_daily`     | Postgres | ~6.856 registros    | D-1 (dias úteis)   | domain_bcb  |

### Schema Contract — `silver_bcb.selic_daily`

| Coluna           | Tipo          | Constraints       | Origem        | PII? |
|------------------|---------------|-------------------|---------------|------|
| `date`           | DATE          | NOT NULL, PK      | bronze        | Não  |
| `taxa_diaria`    | NUMERIC(10,6) | NOT NULL          | `valor`       | Não  |
| `taxa_anual`     | NUMERIC(8,4)  | NOT NULL          | derivada      | Não  |
| `source_api`     | VARCHAR(50)   | NOT NULL          | bronze        | Não  |
| `transformed_at` | TIMESTAMP     | NOT NULL          | `current_timestamp` | Não |

### Schema Contract — `silver_bcb.ipca_monthly`

| Coluna             | Tipo         | Constraints            | Origem        | PII? |
|--------------------|--------------|------------------------|---------------|------|
| `date`             | DATE         | NOT NULL, PK           | bronze        | Não  |
| `variacao_mensal`  | NUMERIC(6,4) | NOT NULL               | `valor`       | Não  |
| `acumulado_12m`    | NUMERIC(8,4) | NULL primeiros 11 meses| derivada      | Não  |
| `source_api`       | VARCHAR(50)  | NOT NULL               | bronze        | Não  |
| `transformed_at`   | TIMESTAMP    | NOT NULL               | `current_timestamp` | Não |

### Schema Contract — `silver_bcb.ptax_daily`

| Coluna                 | Tipo          | Constraints              | Origem        | PII? |
|------------------------|---------------|--------------------------|---------------|------|
| `date`                 | DATE          | NOT NULL, PK             | bronze        | Não  |
| `taxa_cambio`          | NUMERIC(10,4) | NOT NULL                 | `valor`       | Não  |
| `variacao_diaria_pct`  | NUMERIC(8,4)  | NULL no primeiro registro| derivada      | Não  |
| `source_api`           | VARCHAR(50)   | NOT NULL                 | bronze        | Não  |
| `transformed_at`       | TIMESTAMP     | NOT NULL                 | `current_timestamp` | Não |

### Freshness SLAs

| Camada | Target                                           | Medição                                       |
|--------|--------------------------------------------------|-----------------------------------------------|
| Silver | Atualizada diariamente após Bronze completar     | `dag_silver_bcb` success após `dag_bronze_bcb`|
| Silver | `MAX(date)` em `selic_daily` = `MAX(date)` da Bronze | Query de verificação pós-run               |

### Completeness Metrics

- `dbt test` com `not_null` em `date`, `taxa_diaria`, `taxa_anual`, `variacao_mensal`, `taxa_cambio` — zero failures
- `acumulado_12m` não-null a partir de 1995-06-01 (12º mês após start_date do IPCA)
- `variacao_diaria_pct` não-null em todos os registros exceto o primeiro (1999-01-04)

### Lineage

```
bronze_bcb.selic_daily   → (dbt ref) → silver_bcb.selic_daily
bronze_bcb.ipca_monthly  → (dbt ref) → silver_bcb.ipca_monthly
bronze_bcb.ptax_daily    → (dbt ref) → silver_bcb.ptax_daily
```

---

## Assumptions

| ID    | Assumption                                                                              | Se errado, impacto                                                          | Validado? |
|-------|-----------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|-----------|
| A-001 | `dbt-postgres` compatível com Airflow 2.10.4 constraints file                         | Conflito de dependência no build da imagem — fixar versão manualmente       | [ ]       |
| A-002 | `env_var()` do dbt resolve `POSTGRES_USER` e `POSTGRES_PASSWORD` injetadas no container | dbt debug falha — verificar que o compose injeta as variáveis corretas     | [ ]       |
| A-003 | `ExternalTaskSensor` com `execution_date_fn=None` resolve o run mais recente de `dag_bronze_bcb` | Sensor fica em timeout — pode precisar de `execution_delta` configurado | [ ]       |
| A-004 | `EXP(SUM(LN(1 + variacao_mensal/100.0)))` não gera erros matemáticos (LN de negativo) | IPCA historicamente positivo desde 1994-07 — risco muito baixo mas verificar | [ ]     |
| A-005 | `dbt run` com `materialization: table` é idempotente — recria a tabela a cada execução | Dados duplicados ou inconsistentes — nunca acontece com `table` (truncate + insert) | [x] |

---

## Pré-requisitos Bloqueantes

### PRE-01 — `dbt-postgres` no `requirements.txt`

```
dbt-postgres
```

Rebuild da imagem: `make down && make up PROFILE=orchestration`.

### PRE-02 — `profiles.yml` com targets `dev` e `airflow`

```yaml
# transform/profiles.yml
finlake:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5433
      user: "{{ env_var('POSTGRES_USER') }}"
      password: "{{ env_var('POSTGRES_PASSWORD') }}"
      dbname: finlake
      schema: silver_bcb
      threads: 4
    airflow:
      type: postgres
      host: postgres
      port: 5432
      user: "{{ env_var('POSTGRES_USER') }}"
      password: "{{ env_var('POSTGRES_PASSWORD') }}"
      dbname: finlake
      schema: silver_bcb
      threads: 4
```

### PRE-03 — Bind mount `./transform` no container Airflow

```yaml
# docker/compose.airflow.yml — seção volumes
- ../transform:/opt/airflow/transform
```

Sem este mount, `cwd = '/opt/airflow/transform'` na `BashOperator` falha com
`No such file or directory` em runtime — erro silencioso difícil de diagnosticar.

---

## Clarity Score Breakdown

| Elemento | Score | Justificativa                                                                   |
|----------|-------|---------------------------------------------------------------------------------|
| Problem  | 3/3   | Silver ausente + dbt não inicializado bloqueiam Gold e Metabase — específico   |
| Users    | 2/3   | Data Engineer explícito; Gold e Metabase como consumidores downstream implícitos|
| Goals    | 3/3   | MUST/SHOULD/COULD priorizados, fórmulas validadas com dados reais              |
| Success  | 3/3   | `taxa_anual ≈ 14.65`, `dbt test 0 failures`, DAG na UI — todos testáveis       |
| Scope    | 3/3   | 8 itens out-of-scope explícitos; YAGNI com 7 features removidas                |
| **Total**| **14/15** |                                                                             |

**Mínimo para prosseguir: 12/15 ✅**

---

## Open Questions

Nenhuma — pronto para Design.

A-001, A-002 e A-003 devem ser validadas durante o Design ou início do Build,
mas não bloqueiam a especificação.

---

## Revision History

| Versão | Data       | Autor        | Mudanças                                      |
|--------|------------|--------------|-----------------------------------------------|
| 1.0    | 2026-04-24 | define-agent | Versão inicial from BRAINSTORM_SILVER_BCB.md  |
| 1.1    | 2026-04-24 | ship-agent   | Shipped e arquivado                           |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_SILVER_BCB.md`

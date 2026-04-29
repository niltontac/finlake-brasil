# DESIGN: Silver CVM — Transformação e Validação do Domínio Fundos

> Design técnico para implementar `silver_cvm.fundos` e `silver_cvm.informe_diario` via dbt, orquestrado por `dag_silver_cvm.py`, com filtro de fundos operacionais, tipagem correta e derivação de `captacao_liquida`.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | SILVER_CVM |
| **Data** | 2026-04-29 |
| **Autor** | design-agent |
| **DEFINE** | [DEFINE_SILVER_CVM.md](./DEFINE_SILVER_CVM.md) |
| **Status** | Pronto para Build |

---

## Correção Pré-Design (Critical Fix)

> **Descoberta na validação antes do design:** O campo `sit` em `bronze_cvm.cadastro` usa o valor `'LIQUIDAÇÃO'` (sem prefixo `'EM'`), **não** `'EM LIQUIDAÇÃO'` como constava no DEFINE v1.0.

O DEFINE contém `sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` — **valor incorreto**.

O filtro correto, validado contra os dados reais, é:

```sql
WHERE sit IN ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')
```

**Impacto:** Todos os code patterns, testes dbt (`accepted_values`) e comentários neste DESIGN usam `'LIQUIDAÇÃO'` (correto). O DEFINE será atualizado via `/iterate` após o Build confirmar.

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                    SILVER CVM — DATA FLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  PostgreSQL: bronze_cvm                                                 │
│  ┌──────────────────────┐    ┌─────────────────────────────────────┐   │
│  │ cadastro             │    │ informe_diario (partitioned)        │   │
│  │ 41k rows, SCD1      │    │ 6.5M+ rows, RANGE(dt_comptc)        │   │
│  └──────────┬───────────┘    └───────────────────┬─────────────────┘   │
│             │                                    │                     │
│             ▼ dbt source()                       ▼ dbt source()        │
│  ┌──────────────────────┐    ┌─────────────────────────────────────┐   │
│  │ fundos.sql           │    │ informe_diario.sql                  │   │
│  │ materialized: table  │    │ materialized: incremental           │   │
│  │ filter: sit IN (     │    │ strategy: delete+insert             │   │
│  │  'EM FUNCIONAMENTO   │    │ unique_key: (cnpj_fundo,            │   │
│  │   NORMAL',           │    │              dt_comptc)             │   │
│  │  'LIQUIDAÇÃO')       │    │ lookback: 30 days                   │   │
│  │ ~2.500 rows          │    │ derives: captacao_liquida           │   │
│  └──────────┬───────────┘    └───────────────────┬─────────────────┘   │
│             │                                    │                     │
│             └─────────────────┬──────────────────┘                     │
│                               ▼                                         │
│  PostgreSQL: silver_cvm                                                 │
│  ┌──────────────────────┐    ┌─────────────────────────────────────┐   │
│  │ silver_cvm.fundos    │    │ silver_cvm.informe_diario           │   │
│  │ 15 colunas tipadas  │    │ 11 colunas tipadas + derivada       │   │
│  └──────────────────────┘    └─────────────────────────────────────┘   │
│                               ▼                                         │
│  Gold CVM (downstream)                                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  ref('fundos') JOIN ref('informe_diario') → métricas por fundo  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  Orquestração (Airflow)                                                 │
│  dag_bronze_cvm_cadastro (@daily) ──ExternalTaskSensor──► dag_silver_cvm│
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Components

| Componente | Propósito | Tecnologia |
|-----------|-----------|------------|
| `005_silver_cvm.sql` | Cria schema `silver_cvm` no PostgreSQL | SQL (idempotente) |
| `sources.yml` | Declara `bronze_cvm` como fonte dbt | dbt YAML |
| `fundos.sql` | Model Silver: filtro + tipagem de cadastro | dbt SQL, `materialized: table` |
| `informe_diario.sql` | Model Silver: tipagem + derivação incremental | dbt SQL, `materialized: incremental` |
| `schema.yml` | Documenta modelos + testes dbt | dbt YAML |
| `dbt_project.yml` (mod) | Adiciona bloco `domain_cvm` com `+schema: silver_cvm` | YAML (modificação) |
| `Makefile` (mod) | Adiciona `005_silver_cvm.sql` ao target `migrate` | Makefile (modificação) |
| `dag_silver_cvm.py` | Orquestra ExternalTaskSensor → dbt run | Python, Apache Airflow |

---

## Key Decisions

### Decision 1: Materialização `table` para `fundos`, `incremental` para `informe_diario`

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-29 |

**Contexto:** Os dois modelos têm volumes e padrões de atualização radicalmente distintos. `fundos` tem ~2.500 rows estáticos (SCD1, atualiza diariamente); `informe_diario` tem 6,5M+ rows que crescem mensalmente e precisam de janela de 30 dias para recapturar correções.

**Escolha:** `fundos` como `table` (full refresh); `informe_diario` como `incremental` com `delete+insert` e lookback de 30 dias.

**Rationale:** Full refresh em `fundos` é seguro porque o volume é pequeno (~2.500 rows) e a idempotência é garantida. Incremental em `informe_diario` é necessário porque reconstruir 6,5M+ rows a cada run seria inviável no PostgreSQL local.

**Alternativas Rejeitadas:**
1. `incremental` para `fundos` — desnecessário com ~2.500 rows; complica lógica por zero ganho
2. `table` para `informe_diario` — reconstrução diária de 6,5M+ rows excede capacidade local do MVP

**Consequências:**
- `dbt run --full-refresh` no `informe_diario` pode demorar (primeira carga, ~6,5M rows) — aceitável por ser one-time
- Lookback de 30 dias processa ~540k rows/run — dentro das capacidades do PostgreSQL local

---

### Decision 2: `delete+insert` como incremental strategy

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-29 |

**Contexto:** `dbt-postgres` não suporta `merge` nativo. As opções disponíveis são `append` (não-idempotente) ou `delete+insert` (idempotente por `unique_key`).

**Escolha:** `incremental_strategy: 'delete+insert'` com `unique_key: ['cnpj_fundo', 'dt_comptc']`.

**Rationale:** `delete+insert` é atômico por chave — deleta os registros da janela e reinsere, garantindo idempotência sem risco de duplicatas. Comportamento correto para dados de informe que podem chegar com correções retroativas.

**Alternativas Rejeitadas:**
1. `append` — produz duplicatas se o Bronze reinserir dados já processados; não-idempotente
2. `merge` — não disponível no `dbt-postgres`

**Consequências:**
- Performance ligeiramente inferior ao `merge` (delete + insert vs. upsert em-place)
- Idempotência total: re-executar a DAG no mesmo dia é seguro

---

### Decision 3: Filtro `sit IN ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')` — sem staging

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-29 |

**Contexto:** O DEFINE especificava `'EM LIQUIDAÇÃO'`; a validação pré-design revelou que o valor real no Bronze é `'LIQUIDAÇÃO'` (sem prefixo). Staging intermediário (`stg_cvm_fundos`) foi descartado no DEFINE por YAGNI.

**Escolha:** Casting direto no model `fundos.sql` com filtro `WHERE sit IN ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')` — sem staging.

**Rationale:** Volume pequeno (~41k → ~2.500 rows). Staging adicionaria um artefato dbt sem benefício analítico nesta escala. O filtro no model é suficiente e mais legível.

**Alternativas Rejeitadas:**
1. Staging `stg_cvm_fundos` — overhead sem benefício; descartado no DEFINE
2. `'EM LIQUIDAÇÃO'` — valor incorreto validado contra dados reais

**Consequências:**
- `accepted_values` dbt test valida `['EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO']` — alertará se CVM mudar a nomenclatura
- Fundos cancelados (maioria dos 41k) ficam fora da Silver — correto por design

---

### Decision 4: ExternalTaskSensor aguardando apenas `dag_bronze_cvm_cadastro`

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-29 |

**Contexto:** O Bronze CVM tem duas DAGs: `dag_bronze_cvm_cadastro` (daily) e `dag_bronze_cvm_informe` (monthly). A Silver precisa de `fundos` atualizado diariamente; o `informe_diario` incremental é no-op nos dias sem novos dados Bronze.

**Escolha:** Silver DAG aguarda apenas `dag_bronze_cvm_cadastro` via `ExternalTaskSensor`.

**Rationale:** A DAG de informe é mensal — criar dependência dela travaria a Silver por até 30 dias. O modelo incremental de `informe_diario` é naturalmente no-op quando não há novos dados Bronze, então aguardar só o cadastro (daily) é suficiente.

**Alternativas Rejeitadas:**
1. Aguardar ambas as DAGs Bronze — travaria Silver por até 30 dias desnecessariamente
2. Schedule fixo sem sensor — risco de race condition com Bronze ainda rodando

**Consequências:**
- Silver roda diariamente; `informe_diario` processa novos dados mensalmente quando disponíveis
- Operacionalmente mais simples e resiliente

---

## File Manifest

| # | Arquivo | Ação | Propósito | Dependências |
|---|---------|------|-----------|--------------|
| 1 | `docker/postgres/migrations/005_silver_cvm.sql` | Criar | DDL: `CREATE SCHEMA IF NOT EXISTS silver_cvm` | Nenhuma |
| 2 | `Makefile` | Modificar | Adicionar `005_silver_cvm.sql` ao target `migrate` | 1 |
| 3 | `transform/dbt_project.yml` | Modificar | Adicionar bloco `domain_cvm` com `+schema: silver_cvm` | Nenhuma |
| 4 | `transform/models/domain_cvm/sources.yml` | Criar | Declarar `bronze_cvm` como fonte dbt + source freshness | Nenhuma |
| 5 | `transform/models/domain_cvm/fundos.sql` | Criar | Model Silver: filtro + tipagem de `bronze_cvm.cadastro` | 3, 4 |
| 6 | `transform/models/domain_cvm/informe_diario.sql` | Criar | Model Silver incremental: tipagem + `captacao_liquida` | 3, 4 |
| 7 | `transform/models/domain_cvm/schema.yml` | Criar | Docs + testes dbt para `fundos` e `informe_diario` | 5, 6 |
| 8 | `dags/domain_cvm/dag_silver_cvm.py` | Criar | DAG Airflow: ExternalTaskSensor → dbt run silver | 5, 6, 7 |

**Total de Arquivos:** 8 (2 modificações, 6 criações)

---

## Code Patterns

### Pattern 1: Migration `005_silver_cvm.sql`

```sql
-- 005_silver_cvm.sql
-- Cria schema silver_cvm para modelos dbt do domínio Fundos (CVM).
-- dbt cria as tabelas; esta migration apenas provisiona o schema.

CREATE SCHEMA IF NOT EXISTS silver_cvm;

COMMENT ON SCHEMA silver_cvm IS
    'Camada Silver do domínio Fundos (CVM): dados limpos, tipados e validados.';
```

---

### Pattern 2: `dbt_project.yml` — bloco `domain_cvm`

```yaml
# Adicionar dentro de models.finlake, ao lado de domain_bcb:
models:
  finlake:
    domain_bcb:
      +materialized: table
      gold:
        +schema: gold_bcb

    domain_cvm:                     # <-- novo bloco
      +materialized: table
      +schema: silver_cvm           # override: ignora default silver_bcb do profiles.yml
```

> **Por que funciona:** A macro `generate_schema_name` do projeto retorna `custom_schema_name` diretamente (sem prefixo de target), então `silver_cvm` é o schema final.

---

### Pattern 3: `sources.yml` — `bronze_cvm`

```yaml
version: 2

sources:
  - name: bronze_cvm
    database: finlake
    schema: bronze_cvm
    description: "Dados brutos do Portal CVM (Comissão de Valores Mobiliários)."
    tables:
      - name: cadastro
        description: "Cadastro completo de fundos de investimento (SCD1, 41k fundos)."
        freshness:
          warn_after: {count: 26, period: hour}
          error_after: {count: 50, period: hour}
        loaded_at_field: updated_at
        columns:
          - name: cnpj_fundo
            description: "CNPJ do fundo — chave primária."
          - name: sit
            description: "Situação do fundo. Valores operacionais: 'EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO'."

      - name: informe_diario
        description: "Informe diário de fundos particionado por dt_comptc (RANGE mensal)."
        columns:
          - name: cnpj_fundo
            description: "CNPJ do fundo."
          - name: dt_comptc
            description: "Data de competência do informe."
```

---

### Pattern 4: `fundos.sql` — model Silver

```sql
{{
    config(
        materialized='table',
        schema='silver_cvm',
    )
}}

select
    cnpj_fundo::varchar(18)                              as cnpj_fundo,
    tp_fundo::varchar(100)                               as tp_fundo,
    denom_social::text                                   as denom_social,
    sit::varchar(80)                                     as sit,
    classe::varchar(100)                                 as classe,
    classe_anbima::varchar(100)                          as classe_anbima,
    publico_alvo::text                                   as publico_alvo,
    fundo_exclusivo::varchar(1)                          as fundo_exclusivo,
    cast(nullif(trim(inf_taxa_adm), '')  as numeric(10, 4)) as taxa_adm,
    cast(nullif(trim(inf_taxa_perfm), '') as numeric(10, 4)) as taxa_perfm,
    dt_ini_ativ::date                                    as dt_ini_ativ,
    dt_fim_ativ::date                                    as dt_fim_ativ,
    admin::text                                          as admin,
    gestor::text                                         as gestor,
    current_timestamp                                    as transformed_at
from {{ source('bronze_cvm', 'cadastro') }}
where sit in ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')
```

> **Nota `taxa_adm` / `taxa_perfm`:** O Bronze armazena como `TEXT`; `nullif(trim(...), '')` converte strings vazias em NULL antes do cast numérico, evitando erro de cast.

---

### Pattern 5: `informe_diario.sql` — model incremental

```sql
{{
    config(
        materialized='incremental',
        schema='silver_cvm',
        unique_key=['cnpj_fundo', 'dt_comptc'],
        incremental_strategy='delete+insert',
    )
}}

select
    cnpj_fundo::varchar(18)                             as cnpj_fundo,
    dt_comptc::date                                     as dt_comptc,
    tp_fundo::varchar(50)                               as tp_fundo,
    vl_total::numeric(22, 6)                            as vl_total,
    vl_quota::numeric(22, 8)                            as vl_quota,
    vl_patrim_liq::numeric(22, 6)                       as vl_patrim_liq,
    captc_dia::numeric(22, 6)                           as captc_dia,
    resg_dia::numeric(22, 6)                            as resg_dia,
    (captc_dia::numeric(22, 6) - resg_dia::numeric(22, 6)) as captacao_liquida,
    nr_cotst::integer                                   as nr_cotst,
    current_timestamp                                   as transformed_at
from {{ source('bronze_cvm', 'informe_diario') }}

{% if is_incremental() %}
    where dt_comptc >= (
        select max(dt_comptc) - interval '30 days'
        from {{ this }}
    )
{% endif %}
```

> **Comportamento `captacao_liquida`:** NULL quando `captc_dia` ou `resg_dia` for NULL (propagação natural de NULL no PostgreSQL — sem COALESCE intencional para preservar a semântica de "dado ausente").

---

### Pattern 6: `schema.yml` — testes dbt

```yaml
version: 2

models:
  - name: fundos
    description: >
      Fundos de investimento operacionais extraídos de bronze_cvm.cadastro.
      Filtro: sit IN ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO').
      Grain: um registro por CNPJ de fundo.
    columns:
      - name: cnpj_fundo
        description: "CNPJ do fundo — PK da tabela."
        tests:
          - not_null
          - unique

      - name: sit
        description: "Situação operacional do fundo."
        tests:
          - not_null
          - accepted_values:
              values: ['EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO']

      - name: denom_social
        description: "Denominação social do fundo."
        tests:
          - not_null

      - name: tp_fundo
        description: "Tipo do fundo conforme classificação CVM."
        tests:
          - not_null

      - name: fundo_exclusivo
        description: "Flag de fundo exclusivo: 'S' ou 'N'."
        tests:
          - accepted_values:
              values: ['S', 'N']
              severity: warn

      - name: transformed_at
        description: "Timestamp de transformação pela Silver."
        tests:
          - not_null

  - name: informe_diario
    description: >
      Informe diário de fundos tipado com captacao_liquida derivada.
      Grain: um registro por (cnpj_fundo, dt_comptc).
      Estratégia incremental: delete+insert com lookback de 30 dias.
    columns:
      - name: cnpj_fundo
        description: "CNPJ do fundo."
        tests:
          - not_null
          - relationships:
              to: ref('fundos')
              field: cnpj_fundo
              severity: warn

      - name: dt_comptc
        description: "Data de competência do informe."
        tests:
          - not_null

      - name: captacao_liquida
        description: "Captação líquida derivada: captc_dia - resg_dia. NULL quando base é NULL."

      - name: transformed_at
        description: "Timestamp de transformação pela Silver."
        tests:
          - not_null
```

> **Nota `relationships` em `informe_diario.cnpj_fundo`:** Definido com `severity: warn` porque fundos cancelados no Bronze não existem na Silver (por design). A FK não é hard constraint — é uma checagem de qualidade não-bloqueante.

---

### Pattern 7: `dag_silver_cvm.py`

```python
"""DAG Silver CVM — transforma bronze_cvm em silver_cvm via dbt."""

from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS = {
    "owner": "domain_funds",
    "retries": 1,
}

_DBT_CMD = (
    "dbt run"
    " --select domain_cvm"
    " --target airflow"
    " --profiles-dir /opt/airflow/transform"
)


@dag(
    dag_id="dag_silver_cvm",
    description="Silver CVM: transformação dbt de bronze_cvm em silver_cvm.",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["silver", "cvm", "domain_funds", "medallion", "dbt"],
)
def dag_silver_cvm() -> None:
    wait_bronze_cvm_cadastro = ExternalTaskSensor(
        task_id="wait_bronze_cvm_cadastro",
        external_dag_id="dag_bronze_cvm_cadastro",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run_silver_cvm = BashOperator(
        task_id="dbt_run_silver_cvm",
        bash_command=_DBT_CMD,
        cwd="/opt/airflow/transform",
    )

    wait_bronze_cvm_cadastro >> dbt_run_silver_cvm


dag_silver_cvm()
```

---

### Pattern 8: `Makefile` — target `migrate` atualizado

```makefile
migrate:
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/001_bronze_bcb.sql
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/002_silver_bcb.sql
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/003_gold_bcb.sql
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/004_bronze_cvm.sql
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/005_silver_cvm.sql
```

---

## Data Flow

```text
1. dag_bronze_cvm_cadastro (@daily) conclui com status success
   │
   ▼ ExternalTaskSensor detecta conclusão
2. dag_silver_cvm acorda (trigger diário)
   │
   ▼ BashOperator executa
3. dbt run --select domain_cvm --target airflow
   │
   ├──► fundos.sql
   │      SELECT + WHERE sit IN ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')
   │      DROP TABLE silver_cvm.fundos + CREATE TABLE + INSERT (full refresh)
   │      ~2.500 rows entregues
   │
   └──► informe_diario.sql
          is_incremental() = TRUE → WHERE dt_comptc >= MAX(dt_comptc) - 30 days
          DELETE registros da janela + INSERT novos (~540k rows/run típico)
          captacao_liquida = captc_dia - resg_dia (derivada inline)
   │
   ▼ dbt test --select domain_cvm (opcional: via BashOperator adicional)
4. silver_cvm.fundos e silver_cvm.informe_diario disponíveis para Gold CVM
```

---

## Integration Points

| Sistema Externo | Tipo | Mecanismo |
|----------------|------|-----------|
| `bronze_cvm.cadastro` | PostgreSQL table | `dbt source()` via `profiles.yml` |
| `bronze_cvm.informe_diario` | PostgreSQL partitioned table | `dbt source()` — PostgreSQL roteia para partição correta automaticamente |
| `dag_bronze_cvm_cadastro` | Airflow DAG | `ExternalTaskSensor` (mode=reschedule) |
| Gold CVM (futuro) | dbt downstream | `ref('fundos')` + `ref('informe_diario')` |

---

## Pipeline Architecture

### DAG Diagram

```text
dag_bronze_cvm_cadastro (@daily)
        │
        │ ExternalTaskSensor (mode=reschedule, timeout=3600s)
        ▼
dag_silver_cvm (@daily)
  └── wait_bronze_cvm_cadastro ──► dbt_run_silver_cvm
                                         │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                        fundos.sql        informe_diario.sql
                        (table)           (incremental)
```

### Partition Strategy

| Tabela | Partition Key | Granularidade | Rationale |
|--------|--------------|---------------|-----------|
| `bronze_cvm.informe_diario` | `dt_comptc` | Mensal (RANGE) | Gerencia ~48MB uncompressed/mês; PostgreSQL roteia automaticamente |
| `silver_cvm.informe_diario` | — | Sem particionamento | Volume Silver (~2M rows ativo) dentro da capacidade do PostgreSQL local sem particionamento |

### Incremental Strategy

| Model | Strategy | Unique Key | Lookback |
|-------|----------|-----------|---------|
| `fundos` | full refresh (table) | `cnpj_fundo` | N/A |
| `informe_diario` | `delete+insert` | `(cnpj_fundo, dt_comptc)` | 30 dias |

### Schema Evolution Plan

| Tipo de Mudança | Handling | Rollback |
|-----------------|----------|---------|
| Nova coluna em `fundos` | Adicionar no SELECT + `schema.yml`; dbt recria a table | Remover do SELECT + DROP COLUMN |
| Nova coluna em `informe_diario` | Adicionar no SELECT + `--full-refresh` na primeira vez | `--full-refresh` sem a coluna |
| Coluna Bronze renomeada | Atualizar alias no model; testar com `dbt compile` | Reverter alias |
| Novo valor de `sit` (CVM altera nomenclatura) | Atualizar `accepted_values` no `schema.yml` + WHERE clause | Reverter valores |

### Data Quality Gates

| Gate | Ferramenta | Threshold | Ação em Falha |
|------|-----------|-----------|---------------|
| `cnpj_fundo NOT NULL` em `fundos` | dbt test | 0 nulls | Bloqueia pipeline (severity: error) |
| `cnpj_fundo UNIQUE` em `fundos` | dbt test | 0 duplicatas | Bloqueia pipeline (severity: error) |
| `sit accepted_values` em `fundos` | dbt test | 0 violações | Bloqueia pipeline (severity: error) |
| `(cnpj_fundo, dt_comptc) NOT NULL` em `informe_diario` | dbt test | 0 nulls | Bloqueia pipeline (severity: error) |
| FK `informe_diario.cnpj_fundo` → `fundos` | dbt test | N/A | Warning apenas (severity: warn) — fundos cancelados esperados |
| Row count `fundos` entre 1.500-5.000 | Smoke test manual | Fora do range | Investigar filtro `sit` |

---

## Testing Strategy

| Tipo | Escopo | Arquivos | Ferramentas | Meta de Cobertura |
|------|--------|----------|-------------|-------------------|
| dbt tests (schema) | Todos os modelos | `schema.yml` | `dbt test --select domain_cvm` | 100% das colunas críticas |
| Smoke test manual | Row count + valores | Query direta no PostgreSQL | psql / DBeaver | `fundos` entre 1.500-5.000; `captacao_liquida` não-nula ≥90% |
| Idempotência | `fundos` (table) | `dbt run --select fundos` × 2 | dbt | Mesmo row count em execuções repetidas |
| Incremental | `informe_diario` | `dbt run --select informe_diario` | dbt | Zero duplicatas em `(cnpj_fundo, dt_comptc)` |
| DAG E2E | Airflow | `dag_silver_cvm` | Airflow UI | Status success; duração < 15 min |
| Source freshness | `bronze_cvm.cadastro` | `sources.yml` | `dbt source freshness` | warn após 26h; error após 50h |

### Acceptance Tests Mapeados para o Build

| AT-ID | Verificação | Como Testar no Build |
|-------|-------------|---------------------|
| AT-001 | Filtro `sit` correto | `SELECT COUNT(*) FROM silver_cvm.fundos WHERE sit NOT IN ('EM FUNCIONAMENTO NORMAL', 'LIQUIDAÇÃO')` → deve retornar 0 |
| AT-002 | Incremental sem duplicatas | `dbt run --select informe_diario` duas vezes; `SELECT COUNT(*) FROM silver_cvm.informe_diario` deve ser idêntico |
| AT-003 | `captacao_liquida` derivada | `SELECT captc_dia, resg_dia, captacao_liquida FROM silver_cvm.informe_diario WHERE captc_dia IS NOT NULL AND resg_dia IS NOT NULL LIMIT 10` — validar manualmente |
| AT-004 | FK warn sem bloqueio | `dbt test --select informe_diario` retorna exit code 0 mesmo com warnings de `relationships` |
| AT-005 | ExternalTaskSensor funciona | Trigger manual de `dag_silver_cvm` na Airflow UI após `dag_bronze_cvm_cadastro` concluir |
| AT-006 | Idempotência `fundos` | `dbt run --select fundos` × 2; row count idêntico |
| AT-007 | `publico_alvo` presente | `SELECT COUNT(*) FROM silver_cvm.fundos WHERE publico_alvo IS NOT NULL` > 0 |
| AT-008 | Schema override funciona | `SELECT table_schema FROM information_schema.tables WHERE table_name IN ('fundos', 'informe_diario')` → deve retornar `silver_cvm` |
| AT-009 | Migration idempotente | `psql < 005_silver_cvm.sql` × 2 → zero erros |

---

## Error Handling

| Tipo de Erro | Estratégia | Retry? |
|-------------|------------|--------|
| `dag_bronze_cvm_cadastro` ainda rodando | `ExternalTaskSensor` aguarda até 3600s; falha por timeout se Bronze exceder | Sim (Airflow retry automático) |
| dbt compilation error (ex: coluna renomeada) | Build falha explicitamente com mensagem clara; sem silêncio | Não (requer fix manual) |
| Cast error (coluna Bronze com tipo inesperado) | dbt run falha com erro de tipo PostgreSQL | Não (requer investigação) |
| Partição Bronze não existe para o período | PostgreSQL retorna zero rows (sem erro); incremental fica no-op | N/A |
| `sit` com valor novo inesperado | `accepted_values` dbt test falha com severity error | Não (requer update do `schema.yml`) |

---

## Configuration

| Config Key | Tipo | Default | Descrição |
|-----------|------|---------|-----------|
| `schema` (dbt_project.yml) | string | `silver_cvm` | Schema PostgreSQL alvo para todos os modelos domain_cvm |
| `materialized` (fundos) | string | `table` | Full refresh a cada dbt run |
| `materialized` (informe_diario) | string | `incremental` | Processa apenas janela de 30 dias |
| `incremental_strategy` | string | `delete+insert` | Único disponível no dbt-postgres |
| `unique_key` (informe_diario) | list | `['cnpj_fundo', 'dt_comptc']` | Chave composta para deduplicação |
| `lookback_days` | int | `30` | Janela incremental em dias (hardcoded no SQL) |
| `ExternalTaskSensor.timeout` | int | `3600` | Timeout em segundos aguardando Bronze |
| `ExternalTaskSensor.poke_interval` | int | `60` | Frequência de verificação em segundos |

---

## Security Considerations

- Credenciais PostgreSQL injetadas via env vars (`POSTGRES_USER`, `POSTGRES_PASSWORD`) — nunca hardcoded
- `silver_cvm` schema separado do Bronze: modelos Silver não têm permissão de escrita no Bronze por design de IAM PostgreSQL (a ser configurado em produção)
- Nenhum dado PII nos modelos Silver CVM — CNPJs são de pessoas jurídicas (fundos), não físicas

---

## Observability

| Aspecto | Implementação |
|---------|---------------|
| Logging (dbt) | `dbt run` produz logs estruturados no stdout; capturado pelo BashOperator do Airflow |
| Logging (Airflow) | Logs de task disponíveis na UI do Airflow (http://localhost:8080) |
| Métricas | Row count de `silver_cvm.fundos` e `silver_cvm.informe_diario` monitorados via smoke tests pós-run |
| Freshness | `dbt source freshness` configurado em `sources.yml`: warn após 26h, error após 50h para `bronze_cvm.cadastro` |
| Alertas | Airflow email/Slack configurável via `on_failure_callback` (não incluído no MVP) |

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-29 | design-agent | Versão inicial — 8 artefatos, 4 ADRs inline |
| 1.0 | 2026-04-29 | design-agent | Correção crítica: `sit = 'LIQUIDAÇÃO'` (não `'EM LIQUIDAÇÃO'`) aplicada em todos os patterns |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_SILVER_CVM.md`

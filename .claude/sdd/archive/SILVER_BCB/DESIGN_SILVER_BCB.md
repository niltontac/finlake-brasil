# DESIGN: Silver BCB — Transformação e Validação de Séries Temporais

> dbt-core greenfield + 3 modelos Silver + DAG Airflow com ExternalTaskSensor

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | SILVER_BCB                                       |
| **Data**          | 2026-04-24                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | ✅ Shipped                                       |
| **Origem**        | DEFINE_SILVER_BCB.md (2026-04-24)                |
| **Upstream**      | BRONZE_BCB (shipped 2026-04-23)                  |

---

## Arquitetura

### Visão Geral

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PostgreSQL 15 (localhost:5433 / postgres:5432 no container)            │
│                                                                         │
│  schema: bronze_bcb          schema: silver_bcb  ← NOVO               │
│  ┌─────────────────────┐     ┌──────────────────────────────────────┐  │
│  │ selic_daily         │ dbt │ selic_daily                          │  │
│  │  date, valor,       │────▶│  date, taxa_diaria, taxa_anual,      │  │
│  │  ingested_at,       │     │  source_api, transformed_at          │  │
│  │  source_api         │     │                                      │  │
│  ├─────────────────────┤     ├──────────────────────────────────────┤  │
│  │ ipca_monthly        │ dbt │ ipca_monthly                         │  │
│  │  date, valor,       │────▶│  date, variacao_mensal, acumulado_12m│  │
│  │  ingested_at,       │     │  source_api, transformed_at          │  │
│  │  source_api         │     │                                      │  │
│  ├─────────────────────┤     ├──────────────────────────────────────┤  │
│  │ ptax_daily          │ dbt │ ptax_daily                           │  │
│  │  date, valor,       │────▶│  date, taxa_cambio,                  │  │
│  │  ingested_at,       │     │  variacao_diaria_pct,                │  │
│  │  source_api         │     │  source_api, transformed_at          │  │
│  └─────────────────────┘     └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
         ▲                                ▲
         │                                │ dbt run (BashOperator)
  dag_bronze_bcb                   dag_silver_bcb
  (ExternalTaskSensor aguarda ────▶ wait_bronze_bcb ──▶ dbt_run_silver_bcb)
```

### Estrutura de Diretórios Final

```
transform/                          ← NOVO (dbt project)
├── dbt_project.yml
├── profiles.yml                    ← targets: dev + airflow
└── models/
    └── domain_bcb/
        ├── sources.yml             ← declara bronze_bcb como fonte
        ├── schema.yml              ← dbt tests + docs de comportamento
        ├── selic_daily.sql
        ├── ipca_monthly.sql
        └── ptax_daily.sql

dags/domain_bcb/
├── __init__.py
├── dag_bronze_bcb.py               (existente)
├── dag_silver_bcb.py               ← NOVO
└── ingestion/                      (existente)

docker/
├── airflow/
│   └── requirements.txt            ← MODIFICAR (+ dbt-postgres)
├── compose.airflow.yml             ← MODIFICAR (bind mount + POSTGRES env vars)
└── postgres/
    └── migrations/
        ├── 001_bronze_bcb.sql      (existente)
        └── 002_silver_bcb.sql      ← NOVO (schema silver_bcb)

Makefile                            ← MODIFICAR (target migrate: + 002)
```

### Fluxo de Dados

```
@daily trigger
     │
     ▼
dag_silver_bcb
     │
     ├── [wait_bronze_bcb] ExternalTaskSensor
     │         external_dag_id='dag_bronze_bcb'
     │         mode='reschedule' (não bloqueia worker slot)
     │         timeout=3600s
     │         poke_interval=60s
     │
     └── [dbt_run_silver_bcb] BashOperator (após sensor success)
               bash_command='dbt run --select domain_bcb --target airflow
                             --profiles-dir /opt/airflow/transform'
               cwd='/opt/airflow/transform'
               (herda POSTGRES_USER e POSTGRES_PASSWORD do container)
```

---

## Decisões de Arquitetura (ADRs)

### ADR-001 — Materialização `table` para modelos Silver

| Atributo    | Valor                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Data**    | 2026-04-24                   |

**Contexto:** dbt suporta `view`, `table`, `incremental` e `ephemeral`. Para séries temporais Silver, precisamos de uma estratégia idempotente e de baixo custo cognitivo.

**Decisão:** `materialized: table` em todos os 3 modelos Silver BCB.

**Rationale:**
- `table` recria a tabela completa a cada `dbt run` — idempotência garantida por design (assumption A-005 do DEFINE, já validada)
- `view` computaria as janelas (`OVER ... ROWS BETWEEN 11 PRECEDING`) a cada query do Metabase/Gold — custo de CPU inaceitável para rolling 12m e LAG sobre ~7000 registros
- `incremental` exigiria `unique_key` e lógica de merge — complexidade desnecessária quando o volume (< 7000 registros por série) é trivial para recriação completa
- `table` é a materialização padrão recomendada para camadas Silver em Data Warehouses pequenos/médios

**Consequências:**
- `dbt run` diário recria as 3 tabelas — ~7000 registros × 3 = operação de segundos
- Sem risco de dados stale por incremental mal configurado

---

### ADR-002 — `profiles.yml` em `transform/` (não em `~/.dbt/`)

| Atributo    | Valor                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Data**    | 2026-04-24                   |

**Contexto:** dbt busca `profiles.yml` em `~/.dbt/` por padrão. No container Airflow, não há `~/.dbt/` configurado, e commitá-lo com credenciais seria um problema de segurança.

**Decisão:** `profiles.yml` em `transform/profiles.yml`, versionado no repositório, com todas as credenciais via `env_var()` do dbt.

**Rationale:**
- Portabilidade: qualquer ambiente que monte `./transform` tem acesso ao profiles
- Segurança: zero credenciais hardcoded — `env_var('POSTGRES_USER')` e `env_var('POSTGRES_PASSWORD')` resolvem em runtime
- `--profiles-dir /opt/airflow/transform` na BashOperator é explícito e auditável
- Não polui o home do usuário (`~/.dbt/`) — importante em containers efêmeros

**Alternativas rejeitadas:**
1. `~/.dbt/profiles.yml` — inexistente no container por padrão; requereria scripts de setup do `airflow` user
2. `DBT_PROFILES_DIR` env var — menos explícito que flag na BashOperator, mais difícil de auditar no log do Airflow

**Consequências:**
- O arquivo é versionado — revisores do código podem auditar os targets
- `dbt debug --profiles-dir transform/` funciona no desenvolvimento local também

---

### ADR-003 — `ExternalTaskSensor` (não `TriggerDagRunOperator`)

| Atributo    | Valor                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Data**    | 2026-04-24                   |

**Contexto:** Silver precisa esperar Bronze completar antes de rodar `dbt run`. Há dois padrões principais para cross-DAG dependency no Airflow.

**Decisão:** `ExternalTaskSensor` em `dag_silver_bcb` aguardando `dag_bronze_bcb`.

**Rationale:**
- Direção de dependência correta: downstream (Silver) conhece upstream (Bronze) — não o contrário
- `TriggerDagRunOperator` em `dag_bronze_bcb` exigiria que Bronze "soubesse" sobre Silver — violaria isolamento de domínio (Data Mesh)
- `mode='reschedule'` não bloqueia um worker slot enquanto aguarda — eficiente no LocalExecutor com recursos limitados
- Ambas as DAGs compartilham `schedule='@daily'` e `start_date=datetime(2024, 1, 1)` → o sensor resolve o `execution_date` correto sem `execution_delta`

**Alternativas rejeitadas:**
1. `TriggerDagRunOperator` em `dag_bronze_bcb` — inverteria o fluxo de dependência; Bronze "saberia" que existe uma Silver
2. `mode='poke'` no sensor — bloqueia o worker slot durante todo o timeout; inaceitável no LocalExecutor

**Consequências:**
- Se `dag_bronze_bcb` falhar ou for skipada no dia, `wait_bronze_bcb` ficará em timeout após 3600s e falhará — comportamento correto e esperado

---

### ADR-004 — `BashOperator` para `dbt run` (não `astronomer-cosmos`)

| Atributo    | Valor                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Data**    | 2026-04-24                   |

**Contexto:** `astronomer-cosmos` oferece integração nativa dbt+Airflow com observabilidade por modelo. Para o MVP com 3 modelos, a avaliação de custo/benefício é clara.

**Decisão:** `BashOperator` simples com `dbt run --select domain_bcb`.

**Rationale:**
- 3 modelos não justificam ~50 dependências extras do cosmos
- `BashOperator` entrega o mesmo resultado final (tabelas Silver criadas) com zero overhead
- Migração para cosmos está documentada como recomendação quando o projeto dbt crescer para 10+ modelos (entrada do domínio CVM Silver)

**Alternativas rejeitadas:**
1. `DbtRunOperator` (via `dbt-airflow`) — deprecado e pouco mantido
2. `astronomer-cosmos` — over-engineering para 3 modelos; custo de dependências alto

---

### ADR-005 — `current_timestamp` no SELECT do modelo (não DEFAULT no DDL)

| Atributo    | Valor                        |
|-------------|------------------------------|
| **Status**  | Accepted                     |
| **Data**    | 2026-04-24                   |

**Contexto:** A coluna `transformed_at` precisa registrar quando o modelo foi executado. Há dois locais possíveis: DDL (`DEFAULT NOW()`) ou SELECT do modelo dbt.

**Decisão:** `current_timestamp` como expressão no SELECT do modelo dbt.

**Rationale:**
- Com `materialized: table`, o dbt executa `CREATE TABLE AS SELECT ...` — não há DDL separado
- `current_timestamp` no SELECT reflete exatamente o momento do `dbt run`, não o momento da inserção de cada row (diferença invisível aqui, mas idiomático dbt)
- Consistência com o padrão dbt: transformações e metadados gerados no próprio modelo SQL
- Revisores identificam a lógica completa lendo apenas o arquivo `.sql`

---

## File Manifest

| # | Arquivo | Ação | Propósito | Deps |
|---|---------|------|-----------|------|
| 1 | `docker/postgres/migrations/002_silver_bcb.sql` | Create | Schema `silver_bcb` (DDL idempotente) | — |
| 2 | `docker/airflow/requirements.txt` | Modify | Adicionar `dbt-postgres` | — |
| 3 | `docker/compose.airflow.yml` | Modify | Bind mount `../transform` + env vars `POSTGRES_USER`/`POSTGRES_PASSWORD` | — |
| 4 | `Makefile` | Modify | Target `migrate` executa também `002_silver_bcb.sql` | 1 |
| 5 | `transform/dbt_project.yml` | Create | Configuração do projeto dbt `finlake` | — |
| 6 | `transform/profiles.yml` | Create | Targets `dev` e `airflow` com `env_var()` | — |
| 7 | `transform/models/domain_bcb/sources.yml` | Create | Declara `bronze_bcb` como fonte dbt com freshness | 5, 6 |
| 8 | `transform/models/domain_bcb/schema.yml` | Create | Testes `not_null` + `unique` + docs de NULLs esperados | 5, 6, 7 |
| 9 | `transform/models/domain_bcb/selic_daily.sql` | Create | Modelo Silver SELIC com `taxa_anual` | 5, 6, 7 |
| 10 | `transform/models/domain_bcb/ipca_monthly.sql` | Create | Modelo Silver IPCA com `acumulado_12m` | 5, 6, 7 |
| 11 | `transform/models/domain_bcb/ptax_daily.sql` | Create | Modelo Silver PTAX com `variacao_diaria_pct` | 5, 6, 7 |
| 12 | `dags/domain_bcb/dag_silver_bcb.py` | Create | DAG `dag_silver_bcb` com sensor + BashOperator | 3, 5, 6 |

**Ordem de execução no Build:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

---

## Code Patterns

### `002_silver_bcb.sql`

```sql
-- Domínio BCB — schema Silver
-- Execute: make migrate (ou psql -U postgres -d finlake -f docker/postgres/migrations/002_silver_bcb.sql)
-- Idempotente: IF NOT EXISTS — dbt cria as tabelas; migration cria apenas o schema

CREATE SCHEMA IF NOT EXISTS silver_bcb;

COMMENT ON SCHEMA silver_bcb IS
    'Silver layer — domínio BCB (Banco Central do Brasil). '
    'Dados transformados, validados e com indicadores derivados. '
    'Tabelas criadas e mantidas pelo dbt-core.';
```

---

### `docker/airflow/requirements.txt` (diff)

```
# Adicionar ao final da seção Domínio Macro (BCB):
dbt-postgres
```

> **Atenção (A-001):** `dbt-postgres` pode ter conflitos com o `constraints-2.10.4` do Airflow.
> Se `pip install` falhar no build, fixar versão: `dbt-postgres==1.8.*`.
> A versão 1.8.x é a última compatível com Python 3.12 e dbt-core 1.8.x.

---

### `docker/compose.airflow.yml` (diff)

```yaml
# Na seção environment — adicionar após AIRFLOW_CONN_FINLAKE_POSTGRES:
POSTGRES_USER: "${POSTGRES_USER}"
POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"

# Na seção volumes — adicionar após ../dags:/opt/airflow/dags:
- ../transform:/opt/airflow/transform
```

---

### `Makefile` (diff — target migrate atualizado)

```makefile
migrate: ## Executa migrations do PostgreSQL (requer 'make up PROFILE=core')
	@echo "→ Executando migration 001_bronze_bcb (schema bronze_bcb + tabelas)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/001_bronze_bcb.sql
	@echo "✓ Migration 001_bronze_bcb executada."
	@echo "→ Executando migration 002_silver_bcb (schema silver_bcb)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/002_silver_bcb.sql
	@echo "✓ Migration 002_silver_bcb executada."
```

---

### `transform/dbt_project.yml`

```yaml
name: finlake
version: '1.0.0'
config-version: 2

profile: finlake

model-paths: ["models"]
target-path: "target"
clean-targets:
  - "target"
  - "dbt_packages"

models:
  finlake:
    domain_bcb:
      +materialized: table
```

> `schema` não é definido aqui — todos os modelos herdam `schema: silver_bcb` do `profiles.yml`.

---

### `transform/profiles.yml`

```yaml
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

> `dev` aponta para `localhost:5433` (PostgreSQL exposto no host).
> `airflow` aponta para `postgres:5432` (host Docker interno).
> Credenciais idênticas — apenas hosts/portas diferem.

---

### `transform/models/domain_bcb/sources.yml`

```yaml
version: 2

sources:
  - name: bronze_bcb
    database: finlake
    schema: bronze_bcb
    description: "Bronze layer — domínio BCB (Banco Central do Brasil). Dados brutos via python-bcb."
    freshness:
      warn_after: {count: 2, period: day}
      error_after: {count: 7, period: day}
    loaded_at_field: ingested_at
    tables:
      - name: selic_daily
        description: "Taxa SELIC diária (série BCB SGS 11). Apenas dias úteis."
      - name: ipca_monthly
        description: "Variação mensal do IPCA (série BCB SGS 433). Primeiro dia do mês."
      - name: ptax_daily
        description: "Taxa PTAX venda USD/BRL diária (série BCB SGS 1). Apenas dias úteis."
```

---

### `transform/models/domain_bcb/schema.yml`

```yaml
version: 2

models:
  - name: selic_daily
    description: >
      SELIC diária com taxa anualizada via convenção BCB (252 dias úteis/ano).
      Fórmula: (power(1 + taxa_diaria / 100.0, 252) - 1) * 100.
    columns:
      - name: date
        description: "Data de referência (apenas dias úteis)"
        tests:
          - not_null
          - unique
      - name: taxa_diaria
        description: "Taxa SELIC diária (% a.d., 6 casas decimais)"
        tests:
          - not_null
      - name: taxa_anual
        description: "Taxa SELIC anualizada (% a.a., 4 casas decimais). Convenção BCB: 252 d.u./ano."
        tests:
          - not_null
      - name: source_api
        tests:
          - not_null
      - name: transformed_at
        tests:
          - not_null

  - name: ipca_monthly
    description: >
      IPCA mensal com acumulado 12 meses via produto encadeado EXP(SUM(LN())).
      Comportamento esperado: acumulado_12m é NULL nos primeiros 11 meses
      (1994-07 a 1995-05) — janela de 12 meses ainda incompleta.
    columns:
      - name: date
        description: "Primeiro dia do mês de referência"
        tests:
          - not_null
          - unique
      - name: variacao_mensal
        description: "Variação mensal do IPCA (%, 4 casas decimais)"
        tests:
          - not_null
      - name: acumulado_12m
        description: >
          IPCA acumulado nos últimos 12 meses (%, 4 casas decimais).
          NULL de 1994-07-01 a 1995-05-01 (primeiros 11 meses da série) — comportamento esperado por design.
          Não-NULL a partir de 1995-06-01.
      - name: source_api
        tests:
          - not_null
      - name: transformed_at
        tests:
          - not_null

  - name: ptax_daily
    description: >
      PTAX diária (R$/USD) com variação percentual em relação ao dia útil anterior.
      Comportamento esperado: variacao_diaria_pct é NULL apenas no primeiro registro
      histórico (1999-01-04), pois não há dia útil anterior disponível.
      LAG opera naturalmente sobre dias úteis — fins de semana e feriados não existem
      na tabela Bronze, portanto não há gap artificial no cálculo.
    columns:
      - name: date
        description: "Data de referência (apenas dias úteis)"
        tests:
          - not_null
          - unique
      - name: taxa_cambio
        description: "Taxa PTAX venda (R$/USD, 4 casas decimais)"
        tests:
          - not_null
      - name: variacao_diaria_pct
        description: >
          Variação percentual diária da taxa de câmbio (%, 4 casas decimais).
          NULL apenas no registro mais antigo (1999-01-04) — comportamento esperado por design.
      - name: source_api
        tests:
          - not_null
      - name: transformed_at
        tests:
          - not_null
```

---

### `transform/models/domain_bcb/selic_daily.sql`

```sql
{{
    config(
        materialized='table'
    )
}}

-- Convenção BCB: 252 dias úteis/ano
-- Fórmula: (power(1 + taxa_diaria / 100.0, 252) - 1) * 100
-- Exemplo: taxa_diaria = 0.054266 → taxa_anual ≈ 14.65% a.a.

select
    date::date                                                          as date,
    valor::numeric(10, 6)                                               as taxa_diaria,
    ((power(1 + valor / 100.0, 252) - 1) * 100)::numeric(8, 4)         as taxa_anual,
    source_api::varchar(50)                                             as source_api,
    current_timestamp                                                   as transformed_at
from {{ source('bronze_bcb', 'selic_daily') }}
```

---

### `transform/models/domain_bcb/ipca_monthly.sql`

```sql
{{
    config(
        materialized='table'
    )
}}

-- Produto encadeado via EXP(SUM(LN())) — fórmula exata de composição para % acumulado
-- CTE com row_number() para identificar os primeiros 11 meses (janela incompleta → NULL)
-- IPCA historicamente positivo desde 1994-07-01 — LN(valor positivo) não gera erros matemáticos

with base as (
    select
        date,
        valor,
        source_api,
        row_number() over (order by date) as rn
    from {{ source('bronze_bcb', 'ipca_monthly') }}
)

select
    date::date                                                          as date,
    valor::numeric(6, 4)                                               as variacao_mensal,
    case
        when rn >= 12
        then (
            (
                exp(
                    sum(ln(1 + valor / 100.0))
                    over (order by date rows between 11 preceding and current row)
                ) - 1
            ) * 100
        )::numeric(8, 4)
        else null
    end                                                                 as acumulado_12m,
    source_api::varchar(50)                                            as source_api,
    current_timestamp                                                   as transformed_at
from base
```

---

### `transform/models/domain_bcb/ptax_daily.sql`

```sql
{{
    config(
        materialized='table'
    )
}}

-- LAG(taxa_cambio) opera sobre dias úteis naturalmente
-- Bronze contém apenas dias úteis — fins de semana e feriados não existem na tabela
-- NULL apenas no primeiro registro histórico (1999-01-04)

select
    date::date                                                          as date,
    valor::numeric(10, 4)                                              as taxa_cambio,
    (
        (valor / lag(valor, 1) over (order by date) - 1) * 100
    )::numeric(8, 4)                                                   as variacao_diaria_pct,
    source_api::varchar(50)                                            as source_api,
    current_timestamp                                                   as transformed_at
from {{ source('bronze_bcb', 'ptax_daily') }}
```

---

### `dags/domain_bcb/dag_silver_bcb.py`

```python
"""DAG de transformação Silver do domínio BCB — Banco Central do Brasil.

Executa modelos dbt após conclusão de dag_bronze_bcb via ExternalTaskSensor.
Downstream (Silver) aguarda upstream (Bronze) — direção de dependência Data Mesh.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS: dict = {
    "owner": "domain_bcb",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_silver_bcb

Transformação Silver do domínio BCB via dbt-core.

### Modelos executados

| Modelo            | Schema     | Coluna derivada      | Fórmula                                     |
|-------------------|------------|----------------------|---------------------------------------------|
| `selic_daily`     | silver_bcb | `taxa_anual`         | `(1 + taxa_diaria/100)^252 - 1` em %       |
| `ipca_monthly`    | silver_bcb | `acumulado_12m`      | `EXP(SUM(LN()))` rolling 12 meses          |
| `ptax_daily`      | silver_bcb | `variacao_diaria_pct`| `(taxa_cambio / lag - 1) * 100`             |

### Dependência cross-DAG

`wait_bronze_bcb` usa `ExternalTaskSensor` aguardando `dag_bronze_bcb` completar.
Downstream conhece upstream — princípio Data Mesh preservado.

### NULLs esperados

- `acumulado_12m`: NULL de 1994-07 a 1995-05 (primeiros 11 meses, janela incompleta)
- `variacao_diaria_pct`: NULL apenas em 1999-01-04 (primeiro registro histórico)
"""


@dag(
    dag_id="dag_silver_bcb",
    description="Silver BCB: transformação dbt de SELIC, IPCA e PTAX para silver_bcb",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["silver", "bcb", "domain_macro", "medallion", "dbt"],
    doc_md=_DOC_MD,
)
def dag_silver_bcb() -> None:
    """DAG de transformação Silver do domínio BCB."""

    wait_bronze = ExternalTaskSensor(
        task_id="wait_bronze_bcb",
        external_dag_id="dag_bronze_bcb",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run = BashOperator(
        task_id="dbt_run_silver_bcb",
        bash_command=(
            "dbt run"
            " --select domain_bcb"
            " --target airflow"
            " --profiles-dir /opt/airflow/transform"
        ),
        cwd="/opt/airflow/transform",
    )

    wait_bronze >> dbt_run


dag_silver_bcb()
```

> `BashOperator` não recebe `env` explícito — herda o ambiente do container Airflow,
> que já tem `POSTGRES_USER` e `POSTGRES_PASSWORD` injetados via `compose.airflow.yml`.

---

## Estratégia de Testes

### dbt Tests (automáticos via `dbt test`)

| Modelo | Coluna | Teste | Comportamento esperado |
|--------|--------|-------|----------------------|
| `selic_daily` | `date` | `not_null`, `unique` | Zero failures |
| `selic_daily` | `taxa_diaria`, `taxa_anual`, `source_api`, `transformed_at` | `not_null` | Zero failures |
| `ipca_monthly` | `date` | `not_null`, `unique` | Zero failures |
| `ipca_monthly` | `variacao_mensal`, `source_api`, `transformed_at` | `not_null` | Zero failures |
| `ipca_monthly` | `acumulado_12m` | — | NULL intencional, sem teste de not_null |
| `ptax_daily` | `date` | `not_null`, `unique` | Zero failures |
| `ptax_daily` | `taxa_cambio`, `source_api`, `transformed_at` | `not_null` | Zero failures |
| `ptax_daily` | `variacao_diaria_pct` | — | NULL no primeiro registro, sem teste de not_null |

**Comando de execução:**
```bash
# No container Airflow:
dbt test --select domain_bcb --target airflow --profiles-dir /opt/airflow/transform

# Local (requer PostgreSQL em localhost:5433 com POSTGRES_USER/PASSWORD no env):
cd transform && dbt test --select domain_bcb --target dev --profiles-dir .
```

### Acceptance Tests Manuais (AT-001 a AT-009)

Queries de verificação a executar após `dbt run`:

```sql
-- AT-003: Validar fórmula SELIC (taxa_anual ≈ 14.65 para taxa_diaria = 0.054266)
SELECT date, taxa_diaria, taxa_anual
FROM silver_bcb.selic_daily
WHERE taxa_diaria = 0.054266
LIMIT 5;
-- Esperado: taxa_anual entre 14.60 e 14.70

-- AT-004: acumulado_12m NULL nos primeiros 11 meses
SELECT COUNT(*) AS deve_ser_11
FROM silver_bcb.ipca_monthly
WHERE date < '1995-06-01'
  AND acumulado_12m IS NULL;
-- Esperado: 11

-- AT-005: variacao_diaria_pct NULL apenas no primeiro registro
SELECT COUNT(*) AS deve_ser_1
FROM silver_bcb.ptax_daily
WHERE variacao_diaria_pct IS NULL;
-- Esperado: 1 (registro de 1999-01-04)

-- AT-009: Migration idempotente (executar 002_silver_bcb.sql duas vezes)
-- Esperado: sem erros
```

### Smoke Test de Infraestrutura (validar PRE antes do Build)

```bash
# PRE-01 — dbt-postgres instalado no container
docker exec finlake-airflow dbt --version

# PRE-02 — profiles.yml acessível e conexão ok
docker exec finlake-airflow bash -c \
    "cd /opt/airflow/transform && dbt debug --target airflow --profiles-dir ."

# PRE-03 — bind mount ativo
docker exec finlake-airflow ls /opt/airflow/transform/dbt_project.yml
```

---

## Assumptions — Atualização

| ID    | Assumption                                                           | Status     | Estratégia de validação                           |
|-------|----------------------------------------------------------------------|------------|---------------------------------------------------|
| A-001 | `dbt-postgres` compatível com constraints Airflow 2.10.4 + Python 3.12 | Não validado | Build: se falhar, fixar `dbt-postgres==1.8.*` |
| A-002 | `env_var()` resolve `POSTGRES_USER` e `POSTGRES_PASSWORD` do container | Não validado | PRE smoke test: `dbt debug --target airflow`  |
| A-003 | `ExternalTaskSensor` sem `execution_delta` resolve o run correto     | Não validado | Testar via AT-006 na UI do Airflow              |
| A-004 | `LN(1 + valor/100)` nunca recebe valor negativo no IPCA              | Risco baixo | Validar via query na Bronze: `SELECT MIN(valor) FROM bronze_bcb.ipca_monthly` |
| A-005 | `materialized: table` é idempotente                                  | ✅ Validado  | Design doc — garantia dbt                       |

---

## Pré-requisitos — Sequência de Execução

```
1. make down
2. Editar docker/airflow/requirements.txt (+ dbt-postgres)
3. Editar docker/compose.airflow.yml (+ bind mount + env vars)
4. make up PROFILE=orchestration
5. make migrate (cria schema silver_bcb)
6. Smoke tests de infraestrutura (dbt --version, dbt debug)
7. dbt run --select domain_bcb --target airflow --profiles-dir /opt/airflow/transform
8. dbt test --select domain_bcb --target airflow --profiles-dir /opt/airflow/transform
9. Queries de acceptance test (AT-001 a AT-009)
10. Validar dag_silver_bcb na UI do Airflow
```

---

## Revision History

| Versão | Data       | Autor        | Mudanças                                        |
|--------|------------|--------------|-------------------------------------------------|
| 1.0    | 2026-04-24 | design-agent | Versão inicial from DEFINE_SILVER_BCB.md        |
| 1.1    | 2026-04-24 | ship-agent   | Shipped e arquivado                             |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_SILVER_BCB.md`

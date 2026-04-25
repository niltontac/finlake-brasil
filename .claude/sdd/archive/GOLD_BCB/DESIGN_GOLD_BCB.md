# DESIGN: Gold BCB — Métricas Analíticas Cross-Série

> Especificação técnica da camada Gold do domínio BCB: 2 modelos dbt no schema
> `gold_bcb` com métricas cross-série (SELIC real, PTAX variação mensal), DAG
> Airflow com `ExternalTaskSensor` aguardando Silver, macro `generate_schema_name`
> para schema exato sem concatenação.

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | GOLD_BCB                                         |
| **Data**          | 2026-04-24                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | ✅ Shipped                                       |
| **Origem**        | DEFINE_GOLD_BCB.md (2026-04-24)                 |
| **Upstream**      | SILVER_BCB (shipped 2026-04-24)                  |

---

## Arquitetura

### Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL 15 — database: finlake                              │
│                                                                 │
│  schema: bronze_bcb          schema: silver_bcb                 │
│  ┌─────────────┐             ┌──────────────────┐              │
│  │ selic_daily │──ref()──────▶ selic_daily       │──┐          │
│  │ ipca_monthly│──ref()──────▶ ipca_monthly      │  │          │
│  │ ptax_daily  │──ref()──────▶ ptax_daily        │──┼──┐       │
│  └─────────────┘             └──────────────────┘  │  │       │
│                                                     │  │       │
│  schema: gold_bcb                                   │  │       │
│  ┌────────────────────────────────────────────┐     │  │       │
│  │  macro_mensal  ◀────────────────ref()──────┘  │  │       │
│  │  (grain: mês)                                  │         │       │
│  │  · taxa_anual (AVG SELIC do mês)               │         │       │
│  │  · acumulado_12m (MAX IPCA do mês)             │  │       │
│  │  · selic_real = taxa_anual - acumulado_12m     │  │       │
│  │  · ptax_media (AVG PTAX do mês)                │  │       │
│  │  · ptax_variacao_mensal_pct (LAG)              │  │       │
│  └────────────┬───────────────────────────────┘  │  │       │
│               │ ref()                             │  │       │
│               ▼                                   │  │       │
│  ┌────────────────────────────────────────────┐  │  │       │
│  │  macro_diario  ◀───────────────────ref()───┘  │       │
│  │  (grain: dia útil)                             ◀──┘       │
│  │  · taxa_anual (SELIC diária)                              │
│  │  · taxa_cambio + variacao_diaria_pct (PTAX)               │
│  │  · acumulado_12m (carry forward do mensal)                │
│  │  · selic_real = taxa_anual - acumulado_12m                │
│  └────────────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Apache Airflow — DAG: dag_gold_bcb                            │
│                                                                 │
│  dag_silver_bcb (external) ──▶ wait_silver_bcb (sensor)        │
│                                       │                         │
│                                       ▼                         │
│                               dbt_run_gold_bcb                  │
│                               (BashOperator)                    │
│                               dbt run --select                  │
│                                 macro_mensal macro_diario       │
└─────────────────────────────────────────────────────────────────┘
```

### Lineage dbt

```
bronze_bcb.selic_daily   ──source()──▶ silver_bcb.selic_daily   ──ref()──┐
bronze_bcb.ipca_monthly  ──source()──▶ silver_bcb.ipca_monthly  ──ref()──┼──▶ gold_bcb.macro_mensal ──ref()──┐
bronze_bcb.ptax_daily    ──source()──▶ silver_bcb.ptax_daily    ──ref()──┘                                   ├──▶ gold_bcb.macro_diario
                                       silver_bcb.selic_daily   ──────────────────────────────────ref()──────┤
                                       silver_bcb.ptax_daily    ──────────────────────────────────ref()──────┘
```

**Regra de dependência:** `macro_diario` referencia `macro_mensal` via `ref()` —
dbt infere a ordem de execução automaticamente. `--select macro_mensal macro_diario`
executa na ordem correta respeitando o grafo.

---

## Decisões Arquiteturais (ADRs)

### ADR-1: PostgreSQL para Gold (mesma engine da Bronze e Silver)

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-24 |

**Contexto:** CLAUDE.md declara DuckDB para Gold, mas o volume analítico do domínio
BCB é ~7k registros — insuficiente para justificar uma engine separada.

**Decisão:** Gold BCB usa PostgreSQL 15, schema `gold_bcb`, mesmo banco da Bronze
e Silver. Modelos Gold entram no projeto dbt `finlake` existente como subdiretório
`transform/models/domain_bcb/gold/`.

**Rationale:**
- Metabase conecta ao PostgreSQL nativamente sem configuração adicional
- `dbt-postgres` já instalado — zero nova dependência
- `transform/` já montado no container Airflow — zero nova infra
- Separação por engine (PostgreSQL × DuckDB) só se justifica acima de 10M+ rows
  ou quando a diferença de funcionalidades analíticas é material para o caso de uso

**Alternativas rejeitadas:**
1. DuckDB com `dbt-duckdb` — driver Metabase comunitário (JAR manual), `ATTACH`
   PostgreSQL, `transform_gold/` separado, nova dependência Python. Complexidade
   desproporcional para ~7k registros.

**Consequências:**
- CLAUDE.md documenta DuckDB para Gold genericamente; BCB especificamente usa
  PostgreSQL como exceção justificada por volume. CVM Gold (quando existir) pode
  usar DuckDB se o volume justificar.
- Toda a lógica analítica fica acessível ao dbt lineage — sem fronteira de engine.

---

### ADR-2: Macro `generate_schema_name` para schema exato

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-24 |

**Contexto:** O comportamento padrão do dbt ao usar `+schema: gold_bcb` é
concatenar o schema do profile com o custom schema: `silver_bcb` + `gold_bcb` →
`silver_bcb_gold_bcb`. O resultado seria um schema inexistente e invisível para Metabase.

**Decisão:** Criar `transform/macros/generate_schema_name.sql` com a macro padrão
dbt que retorna o `custom_schema_name` diretamente quando fornecido, sem concatenação.

**Rationale:** Esta é a macro documentada oficialmente pelo dbt para multi-schema.
Sem ela, qualquer projeto dbt com múltiplos schemas sofre o mesmo problema.

**Alternativas rejeitadas:**
1. Usar `{{ target.schema }}` no modelo — não escala para múltiplos schemas
2. Schemas hardcoded no SQL — viola DRY e ignora o mecanismo de configuração do dbt
3. Profile separado para Gold — complexidade desnecessária, viola o padrão do projeto

**Consequências:**
- Macro se aplica globalmente ao projeto `finlake` — qualquer novo `+schema:` em
  `dbt_project.yml` usará schema exato sem concatenação automaticamente.

---

### ADR-3: `ref()` para Silver nos modelos Gold (não `source()`)

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-24 |

**Contexto:** Modelos Silver (`selic_daily`, `ipca_monthly`, `ptax_daily`) estão
definidos como `source()` na Bronze e como modelos dbt na Silver. Gold precisa
referenciar a Silver — via `source('silver_bcb', ...)` ou via `ref('selic_daily')`.

**Decisão:** Gold usa `{{ ref('selic_daily') }}`, `{{ ref('ipca_monthly') }}`,
`{{ ref('ptax_daily') }}` — referências a modelos dbt, não a sources.

**Rationale:**
- `ref()` cria lineage explícito no grafo dbt: Silver → Gold
- `dbt run --select macro_mensal+` executa Silver antes de Gold automaticamente
  quando necessário
- `source()` seria tecnicamente errado — apontaria para Bronze, não Silver
- `ref()` garante que Gold nunca leia dados desatualizados de Bronze ignorando Silver

**Consequências:**
- `macro_diario` usa `ref('macro_mensal')` para Gold → Gold dependency — dbt
  resolve a ordem corretamente mesmo com `--select macro_mensal macro_diario`.

---

### ADR-4: Selector `--select macro_mensal macro_diario` no BashOperator

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-24 |

**Contexto:** `dag_silver_bcb` usa `--select domain_bcb` para executar todos os
modelos do domínio. Se `dag_gold_bcb` usasse o mesmo selector, re-executaria
Silver desnecessariamente.

**Decisão:** `--select macro_mensal macro_diario` — executa apenas os 2 modelos Gold.

**Rationale:**
- Idempotência: Silver já executada por `dag_silver_bcb` — re-executá-la no Gold
  é ineficiente e cria dependência implícita de tempo de execução
- Explicitação: o comando documenta exatamente quais modelos são responsabilidade
  do `dag_gold_bcb`
- Segurança: dbt respeita o grafo de `ref()` — `macro_mensal` executa antes de
  `macro_diario` mesmo sem `--select domain_bcb`

**Alternativas rejeitadas:**
1. `--select +macro_diario` — executa toda a árvore upstream (Silver incluída)
2. `--select domain_bcb/gold` — path selector mais frágil que nomes explícitos

---

### ADR-5: Hierarquia macro_mensal → macro_diario (toda lógica no mensal)

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-24 |

**Contexto:** SELIC real e variação PTAX requerem joins de 3 séries com grains
diferentes (diário, mensal). O modelo diário poderia replicar a lógica do mensal
ou depender dele.

**Decisão:** `macro_mensal` é o SSOT analítico — toda lógica de join, agregação e
métricas cross-série vive nele. `macro_diario` usa `ref('macro_mensal')` para carry
forward do `acumulado_12m` para resolução diária, sem recalcular nada.

**Rationale:**
- DRY: a fórmula `selic_real = taxa_anual - acumulado_12m` existe em um lugar
- Cortar `macro_diario` do projeto = deletar um arquivo SQL sem tocar em `macro_mensal`
- `acumulado_12m` do IPCA é definido mensalmente — carry forward é semanticamente
  correto (o valor de março/2026 é válido para todos os dias de março/2026)

**Alternativas rejeitadas:**
1. `macro_diario` autônomo recalculando tudo — duplica lógica, aumenta risco de divergência
2. Apenas `macro_mensal` sem `macro_diario` — Metabase precisa de granularidade diária
   para séries temporais contínuas

---

## File Manifest

| # | Arquivo | Ação | Propósito | Dependências |
|---|---------|------|-----------|--------------|
| 1 | `docker/postgres/migrations/003_gold_bcb.sql` | Create | Schema `gold_bcb` idempotente | Nenhuma |
| 2 | `transform/macros/generate_schema_name.sql` | Create | Macro dbt para schema exato | Nenhuma |
| 3 | `transform/dbt_project.yml` | Modify | Adicionar `gold: +schema: gold_bcb` | 2 |
| 4 | `transform/models/domain_bcb/gold/schema.yml` | Create | Testes `not_null` + `unique` em `date` | Nenhuma |
| 5 | `transform/models/domain_bcb/gold/macro_mensal.sql` | Create | Modelo mensal: SELIC real + PTAX mensal | 2, 3 |
| 6 | `transform/models/domain_bcb/gold/macro_diario.sql` | Create | Modelo diário: carry forward acumulado_12m | 5 |
| 7 | `dags/domain_bcb/dag_gold_bcb.py` | Create | DAG com ExternalTaskSensor + BashOperator | 5, 6 |
| 8 | `Makefile` | Modify | Adicionar `003_gold_bcb.sql` ao target `migrate` | 1 |

**Ordem de execução no Build:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

---

## Code Patterns

### 1. `docker/postgres/migrations/003_gold_bcb.sql`

```sql
-- Domínio BCB — schema Gold
-- Execute: make migrate (ou psql -U postgres -d finlake -f docker/postgres/migrations/003_gold_bcb.sql)
-- Idempotente: IF NOT EXISTS — dbt cria as tabelas; migration cria apenas o schema

CREATE SCHEMA IF NOT EXISTS gold_bcb;

COMMENT ON SCHEMA gold_bcb IS
    'Gold layer — domínio BCB (Banco Central do Brasil). '
    'Métricas analíticas cross-série: SELIC real, câmbio médio mensal e variação cambial. '
    'Tabelas criadas e mantidas pelo dbt-core.';
```

---

### 2. `transform/macros/generate_schema_name.sql`

```sql
-- Macro padrão dbt para schema exato — sem concatenar o schema do profile.
-- Sem esta macro: dbt gera silver_bcb_gold_bcb ao invés de gold_bcb.
-- Comportamento: retorna custom_schema_name diretamente quando fornecido.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

---

### 3. `transform/dbt_project.yml` (modificação)

Adicionar bloco `gold` dentro de `domain_bcb` no `dbt_project.yml` existente:

```yaml
# Antes:
models:
  finlake:
    domain_bcb:
      +materialized: table

# Depois:
models:
  finlake:
    domain_bcb:
      +materialized: table
      gold:
        +schema: gold_bcb
```

---

### 4. `transform/models/domain_bcb/gold/schema.yml`

```yaml
version: 2

models:
  - name: macro_mensal
    description: >
      Métricas macroeconômicas mensais cross-série: SELIC real (taxa acima da inflação),
      câmbio médio mensal e variação cambial MoM. Grain: primeiro dia do mês.
      SSOT analítico — toda lógica de join e agregação cross-série está neste modelo.
      macro_diario é derivado via ref() carry forward.
      Comportamento esperado: ptax_variacao_mensal_pct é NULL apenas em 2000-01-01 (primeiro mês).
    columns:
      - name: date
        description: "Primeiro dia do mês de referência (grain mensal)"
        tests:
          - not_null
          - unique
      - name: taxa_anual
        description: "SELIC média anualizada do mês (% a.a., 4 casas decimais). AVG dos dias úteis do mês."
        tests:
          - not_null
      - name: acumulado_12m
        description: "IPCA acumulado nos últimos 12 meses (%, 4 casas decimais). Único por mês."
        tests:
          - not_null
      - name: selic_real
        description: >
          SELIC real = taxa_anual - acumulado_12m (%, 4 casas decimais).
          Mede o retorno da SELIC acima da inflação. Março/2026: 14.6499 - 4.1428 = 10.5071.
        tests:
          - not_null
      - name: ptax_media
        description: "PTAX média mensal (R$/USD, 4 casas decimais). AVG dos dias úteis do mês."
        tests:
          - not_null
      - name: ptax_variacao_mensal_pct
        description: >
          Variação percentual da PTAX média vs mês anterior (%, 4 casas decimais).
          NULL apenas em 2000-01-01 (primeiro mês da série) — comportamento esperado por design.
      - name: transformed_at
        description: "Timestamp de geração do registro pelo dbt"
        tests:
          - not_null

  - name: macro_diario
    description: >
      Métricas macroeconômicas diárias com granularidade de dias úteis SELIC.
      Derivado de macro_mensal via ref(): acumulado_12m é carry forward do valor mensal
      para cada dia útil do mês — semanticamente correto pois IPCA é definido mensalmente.
      Grain: dia útil (dias úteis SELIC desde 2000-01-03, ~6.600 registros).
    columns:
      - name: date
        description: "Data de referência (apenas dias úteis SELIC)"
        tests:
          - not_null
          - unique
      - name: taxa_anual
        description: "SELIC anualizada do dia (% a.a., 4 casas decimais)"
        tests:
          - not_null
      - name: taxa_cambio
        description: "PTAX venda do dia (R$/USD, 4 casas decimais)"
        tests:
          - not_null
      - name: variacao_diaria_pct
        description: >
          Variação percentual diária da PTAX (%, 4 casas decimais).
          NULL apenas no primeiro registro histórico — herdado de silver_bcb.ptax_daily.
      - name: acumulado_12m
        description: >
          IPCA acumulado 12 meses (%, 4 casas decimais). Carry forward do macro_mensal:
          todos os dias de um mesmo mês têm o mesmo acumulado_12m.
        tests:
          - not_null
      - name: selic_real
        description: "SELIC real diária = taxa_anual - acumulado_12m (%, 4 casas decimais)"
        tests:
          - not_null
      - name: transformed_at
        description: "Timestamp de geração do registro pelo dbt"
        tests:
          - not_null
```

---

### 5. `transform/models/domain_bcb/gold/macro_mensal.sql`

```sql
{{
    config(
        materialized='table'
    )
}}

-- SELIC real = taxa_anual (SELIC média mensal) - acumulado_12m (IPCA acumulado 12 meses)
-- Validação março/2026: AVG(14.6499) - MAX(4.1428) = 10.5071%
-- CTE para GROUP BY primeiro, LAG na query externa — PostgreSQL não suporta window dentro de aggregate
with monthly as (
    select
        date_trunc('month', s.date)::date           as date,
        avg(s.taxa_anual)::numeric(8, 4)            as taxa_anual,
        max(i.acumulado_12m)::numeric(8, 4)         as acumulado_12m,
        avg(p.taxa_cambio)::numeric(8, 4)           as ptax_media
    from {{ ref('selic_daily') }} s
    join {{ ref('ipca_monthly') }} i
        on date_trunc('month', s.date) = i.date
    join {{ ref('ptax_daily') }} p
        on p.date = s.date
    where i.acumulado_12m is not null
    group by date_trunc('month', s.date)
)

select
    date,
    taxa_anual,
    acumulado_12m,
    (taxa_anual - acumulado_12m)::numeric(8, 4)                             as selic_real,
    ptax_media,
    ((ptax_media / lag(ptax_media) over (order by date) - 1) * 100)
        ::numeric(8, 4)                                                     as ptax_variacao_mensal_pct,
    current_timestamp                                                        as transformed_at
from monthly
```

---

### 6. `transform/models/domain_bcb/gold/macro_diario.sql`

```sql
{{
    config(
        materialized='table'
    )
}}

-- macro_diario não recalcula métricas: delega ao macro_mensal via ref().
-- acumulado_12m é carry forward: todos os dias de março/2026 têm acumulado_12m = 4.1428.
-- Join condition: date_trunc('month', s.date) = m.date vincula cada dia ao mês correto.
select
    s.date,
    s.taxa_anual,
    p.taxa_cambio,
    p.variacao_diaria_pct,
    m.acumulado_12m,
    (s.taxa_anual - m.acumulado_12m)::numeric(8, 4)                         as selic_real,
    current_timestamp                                                         as transformed_at
from {{ ref('macro_mensal') }} m
join {{ ref('selic_daily') }} s
    on date_trunc('month', s.date) = m.date
join {{ ref('ptax_daily') }} p
    on p.date = s.date
```

---

### 7. `dags/domain_bcb/dag_gold_bcb.py`

```python
"""DAG de transformação Gold do domínio BCB — Banco Central do Brasil.

Executa modelos dbt Gold após conclusão de dag_silver_bcb via ExternalTaskSensor.
Downstream (Gold) aguarda upstream (Silver) — direção de dependência Data Mesh.
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
## dag_gold_bcb

Transformação Gold do domínio BCB via dbt-core.

### Modelos executados

| Modelo          | Schema   | Grain   | Métricas                                      |
|-----------------|----------|---------|-----------------------------------------------|
| `macro_mensal`  | gold_bcb | Mensal  | `selic_real`, `ptax_media`, `ptax_variacao_mensal_pct` |
| `macro_diario`  | gold_bcb | Diário  | `selic_real` (diário), `acumulado_12m` carry forward   |

### Dependência cross-DAG

`wait_silver_bcb` usa `ExternalTaskSensor` aguardando `dag_silver_bcb` completar.
Downstream conhece upstream — princípio Data Mesh preservado.

### Selector dbt

`--select macro_mensal macro_diario` executa apenas os modelos Gold.
Silver não é re-executada — responsabilidade de `dag_silver_bcb`.
"""


@dag(
    dag_id="dag_gold_bcb",
    description="Gold BCB: métricas cross-série SELIC/IPCA/PTAX em gold_bcb via dbt",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["gold", "bcb", "domain_macro", "medallion", "dbt"],
    doc_md=_DOC_MD,
)
def dag_gold_bcb() -> None:
    """DAG de transformação Gold do domínio BCB."""

    wait_silver = ExternalTaskSensor(
        task_id="wait_silver_bcb",
        external_dag_id="dag_silver_bcb",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run = BashOperator(
        task_id="dbt_run_gold_bcb",
        bash_command=(
            "dbt run"
            " --select macro_mensal macro_diario"
            " --target airflow"
            " --profiles-dir /opt/airflow/transform"
        ),
        cwd="/opt/airflow/transform",
    )

    wait_silver >> dbt_run


dag_gold_bcb()
```

---

### 8. `Makefile` (modificação)

Adicionar bloco para `003_gold_bcb.sql` após o bloco do `002_silver_bcb`:

```makefile
# Trecho atual (depois do 002):
	@echo "✓ Migration 002_silver_bcb executada."

# Adicionar:
	@echo "→ Executando migration 003_gold_bcb (schema gold_bcb)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/003_gold_bcb.sql
	@echo "✓ Migration 003_gold_bcb executada."
```

---

## Verificações de Consistência

### Comportamento esperado do join `macro_mensal`

```sql
-- Validar A-001: date_trunc('month', s.date) = i.date funciona como join SELIC × IPCA
-- Executar na Bronze antes do build para confirmar:
SELECT
    date_trunc('month', s.date)::date AS month,
    COUNT(s.date)                     AS dias_uteis,
    AVG(s.valor)::numeric(8,4)        AS avg_selic,
    MAX(i.valor)::numeric(8,4)        AS ipca_mes
FROM bronze_bcb.selic_daily s
JOIN bronze_bcb.ipca_monthly i
    ON date_trunc('month', s.date) = i.date
WHERE date_trunc('month', s.date) = '2026-03-01'
GROUP BY 1;
-- Esperado: 1 linha com ~20 dias úteis, avg_selic ≈ 14.65, ipca_mes ≈ 1.32
```

### Validação `selic_real` (AT-003)

```sql
-- Após dbt run — validar resultado de março/2026:
SELECT date, taxa_anual, acumulado_12m, selic_real
FROM gold_bcb.macro_mensal
WHERE date = '2026-03-01';
-- Esperado: taxa_anual ≈ 14.6499, acumulado_12m ≈ 4.1428, selic_real entre 10.50 e 10.51
```

### Validação `ptax_variacao_mensal_pct` NULL (AT-004)

```sql
SELECT COUNT(*) FROM gold_bcb.macro_mensal WHERE ptax_variacao_mensal_pct IS NULL;
-- Esperado: 1 (apenas 2000-01-01)
```

### Validação carry forward diário (AT-005)

```sql
SELECT DISTINCT acumulado_12m
FROM gold_bcb.macro_diario
WHERE date >= '2026-03-01' AND date < '2026-04-01';
-- Esperado: 1 valor único ≈ 4.1428
```

### Validação schema correto (AT-009)

```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_name IN ('macro_mensal', 'macro_diario');
-- Esperado: ambas em gold_bcb, NENHUMA em silver_bcb_gold_bcb
```

---

## Estratégia de Testes

| Tipo | Escopo | Ferramenta | Quando |
|------|--------|------------|--------|
| **Lint** | `dag_gold_bcb.py` | `ruff check` | Durante build, após criar cada arquivo Python |
| **Import** | DAG structure | `python -c "import dag_gold_bcb"` | Após criar o DAG |
| **dbt compile** | SQL syntax | `dbt compile --select macro_mensal macro_diario` | Antes de `dbt run` |
| **dbt run** | Materialização | `dbt run --select macro_mensal macro_diario --target airflow` | Container |
| **dbt test** | Contratos de dados | `dbt test --select macro_mensal macro_diario --target airflow` | Após `dbt run` |
| **AT queries** | Acceptance tests | `psql` queries manuais | Após `dbt test` |

### Cobertura `dbt test`

| Modelo | Coluna | Testes |
|--------|--------|--------|
| `macro_mensal` | `date` | `not_null`, `unique` |
| `macro_mensal` | `taxa_anual`, `acumulado_12m`, `selic_real`, `ptax_media`, `transformed_at` | `not_null` |
| `macro_diario` | `date` | `not_null`, `unique` |
| `macro_diario` | `taxa_anual`, `taxa_cambio`, `acumulado_12m`, `selic_real`, `transformed_at` | `not_null` |

Total esperado: `12 passed` (2 unique + 2 not_null em date + 5 not_null macro_mensal + 5 not_null macro_diario menos as colunas nullable).

---

## Pré-requisitos de Build

Antes de executar `dbt run`, verificar na ordem:

1. `make migrate` atualizado executado — `gold_bcb` schema existe no PostgreSQL
2. `transform/macros/generate_schema_name.sql` presente — dbt não concatena schemas
3. `dbt_project.yml` com `gold: +schema: gold_bcb` — configuração de schema ativa
4. Silver populada — `silver_bcb.selic_daily`, `silver_bcb.ipca_monthly`, `silver_bcb.ptax_daily` com dados

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-24 | design-agent | Versão inicial from DEFINE_GOLD_BCB.md |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_GOLD_BCB.md`

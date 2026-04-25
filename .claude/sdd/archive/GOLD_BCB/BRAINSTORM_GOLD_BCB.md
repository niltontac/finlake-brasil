# BRAINSTORM: GOLD_BCB

> Phase 0 — Exploração e decisões arquiteturais
> Data: 2026-04-24
> Autor: Nilton Coura

---

## Metadata

| Atributo         | Valor                                      |
|------------------|--------------------------------------------|
| **Feature**      | GOLD_BCB                                   |
| **Domínio**      | domain_macro (BCB)                         |
| **Fase**         | Gold — Métricas Analíticas Cross-Série     |
| **Upstream**     | SILVER_BCB (shipped 2026-04-24)            |
| **Próxima fase** | `/define BRAINSTORM_GOLD_BCB.md`           |

---

## Objetivo

Construir a camada Gold do domínio BCB: métricas analíticas cross-série cruzando
SELIC, IPCA e PTAX da `silver_bcb` para consumo direto pelo Metabase.
Gold usa o mesmo PostgreSQL da Bronze e Silver (schema `gold_bcb`) — mesma
engine, complexidade zero adicional, Metabase conecta sem configuração extra.
Modelos Gold entram no projeto dbt `finlake` existente em `transform/` como
subdiretório `models/domain_bcb/gold/`.

---

## Contexto do Projeto

Silver BCB populada e operacional (2026-04-24):

| Tabela | Rows | Range | Último valor relevante |
|--------|------|-------|------------------------|
| `silver_bcb.selic_daily` | 6.606 | 2000-01-03 → 2026-04-22 | `taxa_anual = 14.65%` |
| `silver_bcb.ipca_monthly` | 381 | 1994-07-01 → 2026-03-01 | `acumulado_12m = 4.14%` |
| `silver_bcb.ptax_daily` | 6.856 | 1999-01-04 → 2026-04-22 | `taxa_cambio = 4.9653` |

**Grounding — SELIC real validada com dados reais:**
```
date        taxa_anual  acumulado_12m  selic_real
2026-03-31  14.6499     4.1428         10.5071   ← SELIC real ≈ 10.5% em março/2026
```

**Grounding — Cross-série PTAX + SELIC funcional:**
```
date        taxa_cambio  variacao_diaria_pct  taxa_anual
2026-04-22  4.9653       -0.3832              14.6499
```

Overlap temporal para `macro_mensal`: SELIC começa em 2000-01-01 (série mais
curta). Grain mensal inicia em **2000-01-01**.

---

## Decisões Exploradas

### Q1 — Engine da Gold Layer

**Decisão: PostgreSQL** — schema `gold_bcb` no mesmo banco da Bronze e Silver.

Motivo: complexidade de DuckDB (driver Metabase comunitário, ATTACH PostgreSQL,
`transform_gold/` separado, `dbt-duckdb` como nova dependência) não se justifica
para ~7k registros e volume analítico do portfólio. Metabase já conecta ao
PostgreSQL nativamente — zero configuração adicional. A separação arquitetural
de engines é um princípio válido mas não defensável como diferencial de portfólio
quando o custo excede o benefício demonstrável.

**Alternativa descartada:** DuckDB com `dbt-duckdb` — complexidade (ATTACH, driver
JAR Metabase, projeto separado) não proporcional ao volume atual.

---

### Q2 — Localização no Projeto dbt

**Decisão: `transform/models/domain_bcb/gold/`** — subdiretório dentro do projeto
`finlake` existente. Mesma engine (PostgreSQL), mesmo adapter (`dbt-postgres`),
sem nova dependência.

Schema `gold_bcb` gerenciado via macro `generate_schema_name` (padrão dbt) +
`+schema: gold_bcb` no `dbt_project.yml`. Sem esse macro, o dbt concatenaria
`silver_bcb_gold_bcb` — comportamento que precisa ser sobrescrito.

**Estrutura resultante:**
```
transform/
├── dbt_project.yml       ← adicionar gold: +schema: gold_bcb
├── profiles.yml          ← inalterado
├── macros/
│   └── generate_schema_name.sql   ← NOVO (padrão dbt para multi-schema)
└── models/
    └── domain_bcb/
        ├── sources.yml, schema.yml, selic_daily.sql, ...  (Silver — inalterados)
        └── gold/
            ├── schema.yml
            ├── macro_mensal.sql
            └── macro_diario.sql
```

---

### Q3 — Métricas dos Modelos Gold

**Dois modelos com hierarquia explícita:**

| Modelo | Grain | Papel |
|--------|-------|-------|
| `macro_mensal` | Mensal | SSOT analítico — toda lógica de join e agregação |
| `macro_diario` | Diário | `ref('macro_mensal')` + expand via `ref()` Silver |

`macro_diario` não re-calcula nada — carry forward do `acumulado_12m` do mensal
para cada dia útil do mês. Cortar o diário = deletar um arquivo SQL.

**Schema `gold_bcb.macro_mensal`:**

| Coluna | Tipo | Fórmula/Origem |
|--------|------|----------------|
| `date` | DATE PK | `date_trunc('month', selic.date)` |
| `taxa_anual` | NUMERIC(8,4) | `AVG(selic_daily.taxa_anual)` — média SELIC do mês |
| `acumulado_12m` | NUMERIC(8,4) | `MAX(ipca_monthly.acumulado_12m)` — único por mês |
| `selic_real` | NUMERIC(8,4) | `taxa_anual - acumulado_12m` |
| `ptax_media` | NUMERIC(8,4) | `AVG(ptax_daily.taxa_cambio)` — câmbio médio do mês |
| `ptax_variacao_mensal_pct` | NUMERIC(8,4) | `(ptax_media / LAG(ptax_media) - 1) * 100` |
| `transformed_at` | TIMESTAMP | `current_timestamp` |

**Schema `gold_bcb.macro_diario`:**

| Coluna | Tipo | Origem |
|--------|------|--------|
| `date` | DATE PK | `selic_daily.date` — dias úteis |
| `taxa_anual` | NUMERIC(8,4) | `ref('selic_daily').taxa_anual` |
| `taxa_cambio` | NUMERIC(8,4) | `ref('ptax_daily').taxa_cambio` |
| `variacao_diaria_pct` | NUMERIC(8,4) | `ref('ptax_daily').variacao_diaria_pct` |
| `acumulado_12m` | NUMERIC(8,4) | `ref('macro_mensal').acumulado_12m` — carry forward |
| `selic_real` | NUMERIC(8,4) | `taxa_anual - acumulado_12m` |
| `transformed_at` | TIMESTAMP | `current_timestamp` |

**Métricas descartadas:**
- `selic_deflacionada_ptax` — concern analítico específico
- Correlações pré-computadas — `CORR()` ad-hoc no Metabase sobre janela desejada

---

## Fórmulas Validadas com Dados Reais

### `macro_mensal` — CTE + LAG (mesmo padrão de `ipca_monthly.sql`)

```sql
with monthly as (
    select
        date_trunc('month', s.date)::date       as date,
        avg(s.taxa_anual)::numeric(8, 4)        as taxa_anual,
        max(i.acumulado_12m)::numeric(8, 4)     as acumulado_12m,
        avg(p.taxa_cambio)::numeric(8, 4)       as ptax_media
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
    (taxa_anual - acumulado_12m)::numeric(8, 4)                      as selic_real,
    ptax_media,
    ((ptax_media / lag(ptax_media) over (order by date) - 1) * 100)
        ::numeric(8, 4)                                              as ptax_variacao_mensal_pct,
    current_timestamp                                                as transformed_at
from monthly
```

**Validação:** `taxa_anual(14.6499) - acumulado_12m(4.1428) = selic_real(10.5071)` ✓

### `macro_diario` — `ref(macro_mensal)` + refs Silver

```sql
select
    s.date,
    s.taxa_anual,
    p.taxa_cambio,
    p.variacao_diaria_pct,
    m.acumulado_12m,                              -- carry forward do mensal
    (s.taxa_anual - m.acumulado_12m)::numeric(8, 4)  as selic_real,
    current_timestamp                             as transformed_at
from {{ ref('macro_mensal') }} m
join {{ ref('selic_daily') }} s
    on date_trunc('month', s.date) = m.date
join {{ ref('ptax_daily') }} p
    on p.date = s.date
```

`macro_diario` usa `ref()` para ambos — Silver e o próprio Gold. dbt gera o
grafo de dependência correto: `selic_daily → macro_mensal → macro_diario`.

---

## Lineage dbt

```
silver_bcb.selic_daily   ──┐
silver_bcb.ipca_monthly  ──┼──▶ gold_bcb.macro_mensal ──┐
silver_bcb.ptax_daily    ──┘                              ├──▶ gold_bcb.macro_diario
silver_bcb.selic_daily   ─────────────────────────────────┤
silver_bcb.ptax_daily    ─────────────────────────────────┘
```

---

## Macro `generate_schema_name`

Macro padrão dbt para schema exato (sem concatenar profile schema):

```sql
-- transform/macros/generate_schema_name.sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

Com este macro e `+schema: gold_bcb` no `dbt_project.yml`, os modelos Gold
materializam em `gold_bcb` (não em `silver_bcb_gold_bcb`).

---

## DAG `dag_gold_bcb`

```
dag_gold_bcb  (schedule: @daily, catchup=False)
│
├── wait_silver_bcb
│     ExternalTaskSensor
│       external_dag_id  = 'dag_silver_bcb'
│       external_task_id = None
│       timeout          = 3600s
│       mode             = 'reschedule'
│
└── dbt_run_gold_bcb
      BashOperator
        bash_command = 'dbt run --select macro_mensal macro_diario
                        --target airflow
                        --profiles-dir /opt/airflow/transform'
        cwd          = '/opt/airflow/transform'
```

Selector `--select macro_mensal macro_diario` executa apenas os modelos Gold —
sem re-rodar a Silver. Sem novo bind mount (transform já montado).

---

## YAGNI — Features Removidas

| Feature | Decisão | Motivo |
|---------|---------|--------|
| DuckDB / `dbt-duckdb` | Removido | Complexidade não justificada para ~7k registros |
| `transform_gold/` separado | Removido | Mesma engine → mesmo projeto dbt |
| Metabase DuckDB driver | Removido | Metabase conecta nativamente ao PostgreSQL |
| `selic_deflacionada_ptax` | Removido | Concern analítico de investidor estrangeiro |
| Correlações pré-computadas | Removido | Janela temporal é decisão analítica → Metabase `CORR()` |
| `dbt docs generate/serve` | Deferido | Documentação de portfólio, não pipeline |
| `astronomer-cosmos` | Deferido | 2 modelos não justificam cosmos |
| Dashboards Metabase | Fora do escopo | Esta feature entrega os dados; dashboards são concern de produto |

---

## Pré-requisitos Bloqueantes

### PRE-01 — Migration `003_gold_bcb.sql`
```sql
CREATE SCHEMA IF NOT EXISTS gold_bcb;
```
Executar via `make migrate` (atualizar Makefile para incluir `003_`).

### PRE-02 — Macro `generate_schema_name` em `transform/macros/`
Sem este arquivo, dbt concatena o schema do profile com o custom schema.

### PRE-03 — `dbt_project.yml` atualizado
```yaml
models:
  finlake:
    domain_bcb:
      +materialized: table
      gold:
        +schema: gold_bcb
```

> Não há novos PRE relacionados a dependências, bind mounts ou infraestrutura —
> tudo já existe da Silver.

---

## Assumptions

| ID | Assumption | Impacto se errada |
|----|------------|-------------------|
| A-001 | `date_trunc('month', s.date) = i.date` funciona como join SELIC × IPCA no PostgreSQL | Join produz cross product ou zero linhas — testar com query direta |
| A-002 | `LAG(ptax_media) IS NULL` apenas no primeiro mês (2000-01-01) | Comportamento esperado — documentar no `schema.yml` |
| A-003 | `ref('macro_mensal')` em `macro_diario` executa após `macro_mensal` mesmo com `--select macro_mensal macro_diario` | dbt respeita dependências — confirmado pelo grafo |
| A-004 | Metabase vê schema `gold_bcb` automaticamente após criação (sem reconfiguração de conexão) | Pode precisar de sync manual no Metabase — verificar após `dbt run` |

---

## Requisitos Rascunho para `/define`

### Funcionais

- **RF-01:** Macro `generate_schema_name` em `transform/macros/` para schema exato.
- **RF-02:** `dbt_project.yml` atualizado com `gold: +schema: gold_bcb`.
- **RF-03:** Migration `003_gold_bcb.sql` criando schema `gold_bcb`.
- **RF-04:** Modelo `macro_mensal` grain mensal: `date, taxa_anual, acumulado_12m,
  selic_real, ptax_media, ptax_variacao_mensal_pct, transformed_at`.
- **RF-05:** Modelo `macro_diario` grain diário: `date, taxa_anual, taxa_cambio,
  variacao_diaria_pct, acumulado_12m, selic_real, transformed_at`.
- **RF-06:** `schema.yml` com `not_null` + `unique` em `date` para ambos os modelos.
- **RF-07:** DAG `dag_gold_bcb` com `ExternalTaskSensor` (dag_silver_bcb) + `BashOperator`.

### Não-Funcionais

- **RNF-01:** `dbt run` idempotente — `materialized: table`.
- **RNF-02:** `dbt test` passa com 0 failures após `dbt run`.
- **RNF-03:** Nenhuma nova dependência Python — `dbt-postgres` já instalado.

### Pré-requisitos

- **PRE-01:** `003_gold_bcb.sql` + `make migrate` atualizado.
- **PRE-02:** `transform/macros/generate_schema_name.sql`.
- **PRE-03:** `dbt_project.yml` com `gold: +schema: gold_bcb`.

---

## Próximos Passos

```
/define .claude/sdd/features/BRAINSTORM_GOLD_BCB.md
```

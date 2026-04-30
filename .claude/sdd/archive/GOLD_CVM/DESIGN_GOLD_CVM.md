# DESIGN: Gold CVM — Métricas de Performance e Cross-Domain de Fundos

> Design técnico para implementar `gold_cvm.fundo_diario` e `gold_cvm.fundo_mensal` via dbt, com cross-domain `ref('macro_mensal')` para alpha vs. SELIC/IPCA, orquestrados por `dag_gold_cvm` com 2 ExternalTaskSensors paralelos.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | GOLD_CVM |
| **Data** | 2026-04-30 |
| **Autor** | design-agent |
| **DEFINE** | [DEFINE_GOLD_CVM.md](./DEFINE_GOLD_CVM.md) |
| **Status** | ✅ Shipped |

---

## Validações Pré-Design Confirmadas

| Assumption | Status | Evidência |
|------------|--------|-----------|
| A-002: `gold_bcb.macro_mensal` tem 12 meses de 2024 | **Confirmado** | Cobertura completa 2024-01-01 a 2024-12-01 |
| A-004: `date` em `macro_mensal` é primeiro dia do mês | **Confirmado** | `2024-01-01`, `2024-02-01`... — join direto: `ON date_trunc('month', i.dt_comptc)::date = m.date` |

---

## Architecture Overview

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         GOLD CVM — DATA FLOW                                     │
├──────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  silver_cvm (dbt ref)                                                            │
│  ┌──────────────────────┐    ┌───────────────────────────────────────────────┐  │
│  │ informe_diario       │    │ informe_diario                                │  │
│  │ 6.514.571 rows       │    │ 6.514.571 rows                                │  │
│  └──────────┬───────────┘    └──────────────────────┬────────────────────────┘  │
│             │                                       │                            │
│             │ LAG(vl_quota) OVER                    │ FIRST_VALUE / LAST_VALUE   │
│             │ PARTITION BY cnpj_fundo               │ + GROUP BY (cnpj_fundo,    │
│             │ NULLIF(vl_quota_ant, 0)               │   ano_mes)                 │
│             ▼                                       │                            │
│  ┌──────────────────────┐                           │ ref('fundos') ─────────►  │
│  │ fundo_diario.sql     │                           │ (gestor)                  │
│  │ materialized: table  │                           │                            │
│  │ schema: gold_cvm     │                           │ ref('macro_mensal') ────►  │
│  │ ~6.5M rows           │                           │ LEFT JOIN por ano_mes      │
│  │ grain: cnpj + data   │                           │ (alpha_selic, alpha_ipca)  │
│  └──────────────────────┘                           ▼                            │
│                                          ┌───────────────────────────────────┐  │
│                                          │ fundo_mensal.sql                  │  │
│                                          │ materialized: table               │  │
│                                          │ schema: gold_cvm                  │  │
│                                          │ ~1.560 rows (max)                 │  │
│                                          │ grain: cnpj + ano_mes             │  │
│                                          └───────────────────────────────────┘  │
│                                                                                  │
│  gold_bcb (cross-domain)                                                         │
│  ┌──────────────────────┐                                                        │
│  │ macro_mensal         │ ─────────────────────────────────────────────────────► │
│  │ ~315 rows            │ LEFT JOIN: ano_mes = date                              │
│  └──────────────────────┘                                                        │
│                                                                                  │
│  Orquestração (Airflow)                                                          │
│  dag_silver_cvm (@daily) ─┬─ ExternalTaskSensor ─┐                              │
│                            │                     ├──► dag_gold_cvm (@daily)     │
│  dag_gold_bcb  (@daily) ──┘─ ExternalTaskSensor ─┘                              │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

| Componente | Propósito | Tecnologia |
|-----------|-----------|------------|
| `006_gold_cvm.sql` | Cria schema `gold_cvm` no PostgreSQL | SQL (idempotente) |
| `fundo_diario.sql` | Model Gold: rentabilidade diária via LAG, NULLIF | dbt SQL, `materialized: table` |
| `fundo_mensal.sql` | Model Gold: métricas mensais + cross-domain alpha | dbt SQL, `materialized: table`, CTE pattern |
| `schema.yml` | Documenta modelos Gold + testes dbt | dbt YAML (dbt 1.11 syntax) |
| `dbt_project.yml` (mod) | Adiciona bloco `gold:` em `domain_cvm` com `+schema: gold_cvm` | YAML (modificação) |
| `Makefile` (mod) | Adiciona `006_gold_cvm.sql` ao target `migrate` | Makefile (modificação) |
| `dag_gold_cvm.py` | DAG com 2 ExternalTaskSensors paralelos → dbt run | Python, Apache Airflow |

---

## Key Decisions

### Decision 1: Dois modelos Gold independentes do Silver (Approach A)

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-30 |

**Contexto:** O brainstorm avaliou 3 abordagens: (A) dois modelos Gold independentes lendo diretamente do Silver, (B) `fundo_mensal` derivando de `ref('fundo_diario')`, (C) modelo cross-domain separado. Com 28.443 zeros e valores negativos confirmados em `vl_quota`, a escolha da abordagem afeta a robustez matemática do pipeline.

**Escolha:** Approach A — `fundo_diario` e `fundo_mensal` buscam dados diretamente de `ref('informe_diario')`, sem `ref()` entre modelos Gold do mesmo domínio.

**Rationale:** `EXP(SUM(LN()))` para rentabilidade composta (Approach B) quebra matematicamente com zeros e negativos — os 28.443 zeros causariam `LN(0) = -infinity`. FIRST/LAST VALUE direto do Silver é algebricamente equivalente para rentabilidade mensal e robusto com qualquer valor de cota. A leitura dupla do Silver é irrelevante no PostgreSQL local com 6.5M rows.

**Alternativas Rejeitadas:**
1. Approach B (`ref('fundo_diario')`) — `EXP(SUM(LN()))` quebra com zeros confirmados; cria dependência interna Gold que bloqueia `fundo_mensal` se `fundo_diario` falhar
2. Approach C (modelo cross-domain separado) — duplica colunas sem benefício analítico; fragmenta o que o Metabase quer em uma view única

**Consequências:**
- `silver_cvm.informe_diario` lido duas vezes por run — custo de I/O irrelevante no PostgreSQL local
- Lineage dbt limpo: Silver → Gold (cada modelo tem fontes explícitas e independentes)

---

### Decision 2: CTE pattern obrigatório — window function não pode estar dentro de aggregate

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-30 |

**Contexto:** `fundo_mensal` precisa de FIRST_VALUE/LAST_VALUE (window) por mês + SUM/AVG (aggregate) por mês. PostgreSQL não permite window functions aninhadas dentro de funções de agregação em um único SELECT.

**Escolha:** CTE em dois estágios: (1) `monthly_base` — window functions por row; (2) `monthly_agg` — GROUP BY + aggregate functions sobre o resultado das windows.

**Rationale:** É o padrão estabelecido pelo próprio `macro_mensal.sql` do Gold BCB (CTE `monthly` com GROUP BY, depois LAG na query externa). Compilado e validado no dbt 1.11.8.

**Alternativas Rejeitadas:**
1. Subquery inline — mesma lógica de dois estágios mas menos legível e mais difícil de depurar
2. Usar DISTINCT ON para pegar primeiro/último — não funciona com aggregate simultâneo

**Consequências:**
- SQL mais verboso mas completamente correto e alinhado ao padrão do projeto
- Facilita debugging: cada CTE pode ser testada isoladamente

---

### Decision 3: NULLIF obrigatório em ambos os modelos — não-opcional

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-30 |

**Contexto:** 28.443 zeros confirmados em `vl_quota` na Silver CVM. Divisão por zero em PostgreSQL produz erro, não NULL — quebraria o pipeline inteiro.

**Escolha:** `NULLIF(vl_quota_anterior, 0)` no denominador de `rentabilidade_diaria_pct`; `NULLIF(vl_quota_inicial, 0)` no denominador de `rentabilidade_mes_pct`. Rentabilidade permanece NULL quando denominador é zero.

**Rationale:** NULLIF é a proteção padrão PostgreSQL para divisão por zero. NULL propagado é semanticamente correto: "rentabilidade não calculável quando cota anterior é zero". Alternativas como COALESCE para zero ou filtro WHERE gerariam rows faltantes ou mascaramento de dado.

**Alternativas Rejeitadas:**
1. WHERE `vl_quota_anterior > 0` — remove rows do resultado; perde dados de captação/PL para esses dias
2. COALESCE(rentabilidade, 0) — mascara dado ausente com zero, enganando análises

**Consequências:**
- Testes dbt verificam que `rentabilidade_diaria_pct IS NULL` onde `vl_quota_anterior = 0`
- O analista no Metabase sabe que NULL = dado não calculável, não = zero retorno

---

### Decision 4: LEFT JOIN (não INNER JOIN) com `macro_mensal` no `fundo_mensal`

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-30 |

**Contexto:** `fundo_mensal` precisa de `alpha_selic` e `alpha_ipca` do cross-domain BCB. A-002 confirmou que `macro_mensal` tem os 12 meses de 2024 — mas o pipeline deve ser robusto mesmo se um mês futuro for adicionado ao Silver antes de rodar o Gold BCB.

**Escolha:** `LEFT JOIN {{ ref('macro_mensal') }} m ON a.ano_mes = m.date` — `alpha_selic` e `alpha_ipca` ficam NULL se não houver match.

**Rationale:** INNER JOIN eliminaria rows de fundos para meses sem dados BCB — quebraria a contagem de `meses_com_dados` e removeria silenciosamente dados de rentabilidade válidos. LEFT JOIN preserva todas as rows de fundos; NULL em `alpha` é explícito e detectável.

**Alternativas Rejeitadas:**
1. INNER JOIN — elimina silenciosamente rows de fundo se BCB estiver atrasado; não-robusto
2. Modelo separado para cross-domain — overhead sem benefício analítico (Approach C rejeitado no brainstorm)

**Consequências:**
- AT-009 (mês sem match) retorna NULL em `alpha_*` sem falha de pipeline — correto por design
- Testes dbt validam `alpha_selic` não-nulo em ≥ 95% das rows (aceita edge cases)

---

### Decision 5: Dois ExternalTaskSensors paralelos no DAG

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-04-30 |

**Contexto:** `dag_gold_cvm` depende de dois upstream: `dag_silver_cvm` (Silver CVM) e `dag_gold_bcb` (Gold BCB, produz `macro_mensal`). As duas dependências são independentes entre si — rodam em paralelo.

**Escolha:** Dois `ExternalTaskSensor` em paralelo (`wait_silver_cvm` + `wait_gold_bcb`), ambos ligados a `dbt_run_gold_cvm` via `>>`.

**Rationale:** Máxima eficiência — Gold CVM começa assim que ambos os upstream concluem, independentemente de qual termina primeiro. Sem serialização desnecessária.

**Alternativas Rejeitadas:**
1. Sensor único apenas para `dag_silver_cvm` — race condition: `macro_mensal` pode não estar atualizado quando `fundo_mensal` roda
2. Sensor sequencial (`wait_silver >> wait_gold_bcb`) — serializa duas esperas independentes sem razão

**Consequências:**
- DAG espera o mais lento dos dois upstream — comportamento correto
- Timeout de 3600s por sensor — suficiente para os dois domínios concluírem antes das 03:00 UTC

---

## File Manifest

| # | Arquivo | Ação | Propósito | Dependências |
|---|---------|------|-----------|--------------|
| 1 | `docker/postgres/migrations/006_gold_cvm.sql` | Criar | DDL: `CREATE SCHEMA IF NOT EXISTS gold_cvm` | Nenhuma |
| 2 | `Makefile` | Modificar | Adicionar `006_gold_cvm.sql` ao target `migrate` | 1 |
| 3 | `transform/dbt_project.yml` | Modificar | Adicionar bloco `gold:` com `+schema: gold_cvm` em `domain_cvm` | Nenhuma |
| 4 | `transform/models/domain_cvm/gold/fundo_diario.sql` | Criar | Model Gold: rentabilidade diária via LAG + NULLIF | 3 |
| 5 | `transform/models/domain_cvm/gold/fundo_mensal.sql` | Criar | Model Gold: métricas mensais + cross-domain alpha | 3 |
| 6 | `transform/models/domain_cvm/gold/schema.yml` | Criar | Docs + testes dbt para os 2 modelos Gold | 4, 5 |
| 7 | `dags/domain_cvm/dag_gold_cvm.py` | Criar | DAG Airflow: 2 sensores paralelos → dbt run gold | 4, 5, 6 |

**Total de Arquivos:** 7 (2 modificações, 5 criações)

---

## Code Patterns

### Pattern 1: Migration `006_gold_cvm.sql`

```sql
-- 006_gold_cvm.sql
-- Provisiona o schema gold_cvm para os modelos dbt do domínio Fundos (CVM).
-- As tabelas são criadas pelo dbt; esta migration apenas cria o schema.
-- Idempotente: pode ser executada múltiplas vezes sem erro.

CREATE SCHEMA IF NOT EXISTS gold_cvm;

COMMENT ON SCHEMA gold_cvm IS
    'Camada Gold do domínio Fundos (CVM): métricas de performance, cross-domain BCB×CVM. Tabelas gerenciadas pelo dbt.';
```

---

### Pattern 2: `dbt_project.yml` — bloco `gold:` em `domain_cvm`

```yaml
models:
  finlake:
    domain_bcb:
      +materialized: table
      gold:
        +schema: gold_bcb

    domain_cvm:
      +materialized: table
      +schema: silver_cvm
      gold:                          # <-- novo bloco
        +schema: gold_cvm            # override: substitui silver_cvm para subpasta gold/
```

> **Hierarquia de override:** `domain_cvm` herda `+materialized: table` do pai. O bloco `gold:` sobrescreve apenas o `+schema` para `gold_cvm` — sem necessidade de repetir `+materialized`.

---

### Pattern 3: `fundo_diario.sql`

```sql
{{
    config(
        materialized='table',
        schema='gold_cvm',
    )
}}

with daily as (
    select
        cnpj_fundo,
        dt_comptc,
        tp_fundo,
        vl_quota,
        lag(vl_quota) over (
            partition by cnpj_fundo
            order by dt_comptc
        )                                                                as vl_quota_anterior,
        vl_patrim_liq,
        captacao_liquida,
        current_timestamp                                                as transformed_at
    from {{ ref('informe_diario') }}
)

select
    cnpj_fundo,
    dt_comptc,
    tp_fundo,
    vl_quota::numeric(22, 8)                                             as vl_quota,
    vl_quota_anterior::numeric(22, 8)                                    as vl_quota_anterior,
    vl_patrim_liq::numeric(22, 6)                                        as vl_patrim_liq,
    captacao_liquida::numeric(22, 6)                                     as captacao_liquida,
    case
        when nullif(vl_quota_anterior, 0) is not null
            then ((vl_quota - vl_quota_anterior)
                  / nullif(vl_quota_anterior, 0) * 100)::numeric(10, 6)
        else null
    end                                                                  as rentabilidade_diaria_pct,
    transformed_at
from daily
```

> **Nota `vl_quota_anterior`:** NULL para o primeiro registro de cada fundo — comportamento correto por design (LAG sem histórico prévio).

---

### Pattern 4: `fundo_mensal.sql` — CTE em dois estágios

```sql
{{
    config(
        materialized='table',
        schema='gold_cvm',
    )
}}

-- Estágio 1: window functions por row (PostgreSQL não permite window dentro de aggregate)
with monthly_base as (
    select
        cnpj_fundo,
        date_trunc('month', dt_comptc)::date                             as ano_mes,
        tp_fundo,
        vl_quota,
        captacao_liquida,
        vl_patrim_liq,
        nr_cotst,
        first_value(vl_quota) over (
            partition by cnpj_fundo, date_trunc('month', dt_comptc)
            order by dt_comptc
            rows between unbounded preceding and unbounded following
        )                                                                as vl_quota_inicial,
        last_value(vl_quota) over (
            partition by cnpj_fundo, date_trunc('month', dt_comptc)
            order by dt_comptc
            rows between unbounded preceding and unbounded following
        )                                                                as vl_quota_final,
        count(distinct date_trunc('month', dt_comptc)::date) over (
            partition by cnpj_fundo
        )                                                                as meses_com_dados
    from {{ ref('informe_diario') }}
),

-- Estágio 2: aggregate por (cnpj_fundo, ano_mes)
monthly_agg as (
    select
        cnpj_fundo,
        ano_mes,
        tp_fundo,
        max(vl_quota_inicial)::numeric(22, 8)                            as vl_quota_inicial,
        max(vl_quota_final)::numeric(22, 8)                              as vl_quota_final,
        sum(captacao_liquida)::numeric(22, 6)                            as captacao_liquida_acumulada,
        avg(vl_patrim_liq)::numeric(22, 6)                               as vl_patrim_liq_medio,
        avg(nr_cotst)::numeric(10, 2)                                    as nr_cotst_medio,
        max(meses_com_dados)                                             as meses_com_dados
    from monthly_base
    group by cnpj_fundo, ano_mes, tp_fundo
),

-- Estágio 3: enriquecer com atributos e cross-domain
enriched as (
    select
        a.cnpj_fundo,
        a.ano_mes,
        a.tp_fundo,
        f.gestor,
        a.vl_quota_inicial,
        a.vl_quota_final,
        case
            when nullif(a.vl_quota_inicial, 0) is not null
                then ((a.vl_quota_final - a.vl_quota_inicial)
                      / nullif(a.vl_quota_inicial, 0) * 100)::numeric(10, 6)
            else null
        end                                                              as rentabilidade_mes_pct,
        a.captacao_liquida_acumulada,
        a.vl_patrim_liq_medio,
        a.nr_cotst_medio,
        a.meses_com_dados,
        m.taxa_anual                                                     as taxa_anual_bcb,
        m.acumulado_12m                                                  as acumulado_12m_ipca
    from monthly_agg a
    left join {{ ref('fundos') }} f
        on f.cnpj_fundo = a.cnpj_fundo
    left join {{ ref('macro_mensal') }} m
        on a.ano_mes = m.date
)

select
    cnpj_fundo,
    ano_mes,
    tp_fundo,
    gestor,
    vl_quota_inicial,
    vl_quota_final,
    rentabilidade_mes_pct,
    captacao_liquida_acumulada,
    vl_patrim_liq_medio,
    nr_cotst_medio,
    meses_com_dados,
    taxa_anual_bcb,
    acumulado_12m_ipca,
    case
        when rentabilidade_mes_pct is not null and taxa_anual_bcb is not null
            then (rentabilidade_mes_pct - taxa_anual_bcb / 12)::numeric(10, 6)
        else null
    end                                                                  as alpha_selic,
    case
        when rentabilidade_mes_pct is not null and acumulado_12m_ipca is not null
            then (rentabilidade_mes_pct - acumulado_12m_ipca / 12)::numeric(10, 6)
        else null
    end                                                                  as alpha_ipca,
    current_timestamp                                                    as transformed_at
from enriched
```

> **Nota `alpha_selic`:** `taxa_anual_bcb / 12` converte taxa anual para equivalente mensal (linear — adequado para comparação de curto prazo com retorno mensal de fundo).

---

### Pattern 5: `schema.yml` — testes dbt Gold CVM (dbt 1.11 syntax)

```yaml
version: 2

models:
  - name: fundo_diario
    description: >
      Métricas diárias de performance por fundo de investimento.
      Grain: (cnpj_fundo, dt_comptc). Fonte: ref('informe_diario').
      rentabilidade_diaria_pct é NULL quando vl_quota_anterior = 0 ou NULL — por design.
    columns:
      - name: cnpj_fundo
        description: "CNPJ do fundo."
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('fundos')
                field: cnpj_fundo
              config:
                severity: warn

      - name: dt_comptc
        description: "Data de competência."
        data_tests:
          - not_null

      - name: vl_quota
        description: "Valor da cota na data."

      - name: vl_quota_anterior
        description: "Cota do dia anterior (LAG). NULL no primeiro registro de cada fundo."

      - name: rentabilidade_diaria_pct
        description: >
          Retorno diário = (vl_quota - vl_quota_anterior) / NULLIF(vl_quota_anterior, 0) * 100.
          NULL quando vl_quota_anterior é NULL (primeiro dia) ou zero (dado anômalo).

      - name: transformed_at
        description: "Timestamp de transformação."
        data_tests:
          - not_null

  - name: fundo_mensal
    description: >
      Métricas mensais de performance com comparativo cross-domain vs. SELIC e IPCA.
      Grain: (cnpj_fundo, ano_mes). Fonte: ref('informe_diario') + ref('fundos') + ref('macro_mensal').
      alpha_selic e alpha_ipca são NULL quando sem match BCB (LEFT JOIN) ou rentabilidade não calculável.
    columns:
      - name: cnpj_fundo
        description: "CNPJ do fundo."
        data_tests:
          - not_null

      - name: ano_mes
        description: "Primeiro dia do mês de referência (date_trunc)."
        data_tests:
          - not_null

      - name: tp_fundo
        description: "Tipo do fundo."

      - name: gestor
        description: "Nome do gestor (via JOIN com silver_cvm.fundos)."

      - name: vl_quota_inicial
        description: "Cota no primeiro dia útil do mês (FIRST_VALUE)."

      - name: vl_quota_final
        description: "Cota no último dia útil do mês (LAST_VALUE)."

      - name: rentabilidade_mes_pct
        description: >
          Retorno mensal = (vl_quota_final - vl_quota_inicial) / NULLIF(vl_quota_inicial, 0) * 100.
          NULL quando vl_quota_inicial é zero.

      - name: captacao_liquida_acumulada
        description: "Soma de captacao_liquida no mês."

      - name: vl_patrim_liq_medio
        description: "Média do patrimônio líquido diário no mês."

      - name: nr_cotst_medio
        description: "Média do número de cotistas diário no mês."

      - name: meses_com_dados
        description: "Quantidade de meses distintos com dados para o fundo em todo o período Silver disponível."
        data_tests:
          - not_null

      - name: taxa_anual_bcb
        description: "SELIC média anualizada do mês (via gold_bcb.macro_mensal). NULL se sem match."

      - name: acumulado_12m_ipca
        description: "IPCA acumulado 12 meses do mês (via gold_bcb.macro_mensal). NULL se sem match."

      - name: alpha_selic
        description: >
          Alpha vs. SELIC = rentabilidade_mes_pct - (taxa_anual_bcb / 12).
          Positivo significa que o fundo superou a SELIC no mês.
          NULL quando rentabilidade ou taxa BCB não disponíveis.

      - name: alpha_ipca
        description: >
          Alpha vs. IPCA = rentabilidade_mes_pct - (acumulado_12m_ipca / 12).
          Positivo significa que o fundo superou a inflação no mês.
          NULL quando rentabilidade ou IPCA não disponíveis.

      - name: transformed_at
        description: "Timestamp de transformação."
        data_tests:
          - not_null
```

---

### Pattern 6: `dag_gold_cvm.py`

```python
"""DAG Gold CVM — métricas de performance de fundos via dbt."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS = {
    "owner": "domain_funds",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_gold_cvm

Transformação Gold do domínio Fundos (CVM) via dbt-core.

### Modelos executados

| Modelo          | Schema   | Grain              | Métricas principais                                   |
|-----------------|----------|--------------------|-------------------------------------------------------|
| `fundo_diario`  | gold_cvm | cnpj + dt_comptc   | `rentabilidade_diaria_pct` (LAG + NULLIF)            |
| `fundo_mensal`  | gold_cvm | cnpj + ano_mes     | `rentabilidade_mes_pct`, `alpha_selic`, `alpha_ipca`  |

### Dependências cross-DAG (paralelas)

- `wait_silver_cvm` → `dag_silver_cvm` (Silver CVM)
- `wait_gold_bcb` → `dag_gold_bcb` (Gold BCB, produz macro_mensal)

Ambos os sensores rodam em paralelo. `dbt_run_gold_cvm` aguarda os dois.
"""

_DBT_CMD = (
    "dbt run"
    " --select fundo_diario fundo_mensal"
    " --target airflow"
    " --profiles-dir /opt/airflow/transform"
)


@dag(
    dag_id="dag_gold_cvm",
    description="Gold CVM: métricas de performance e cross-domain BCB×CVM via dbt.",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["gold", "cvm", "domain_funds", "medallion", "dbt"],
    doc_md=_DOC_MD,
)
def dag_gold_cvm() -> None:
    """Orquestra a transformação Gold do domínio Fundos (CVM).

    Aguarda dag_silver_cvm (dados de fundos) e dag_gold_bcb (macro_mensal para
    cross-domain) em paralelo antes de executar os modelos dbt Gold.
    """
    wait_silver_cvm = ExternalTaskSensor(
        task_id="wait_silver_cvm",
        external_dag_id="dag_silver_cvm",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    wait_gold_bcb = ExternalTaskSensor(
        task_id="wait_gold_bcb",
        external_dag_id="dag_gold_bcb",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run_gold_cvm = BashOperator(
        task_id="dbt_run_gold_cvm",
        bash_command=_DBT_CMD,
        cwd="/opt/airflow/transform",
    )

    [wait_silver_cvm, wait_gold_bcb] >> dbt_run_gold_cvm


dag_gold_cvm()
```

> **Nota `[wait_silver_cvm, wait_gold_bcb] >> dbt_run_gold_cvm`:** Lista de tasks como upstream cria dependência paralela — ambas devem completar antes do dbt run, mas correm simultaneamente.

---

### Pattern 7: `Makefile` — target `migrate` atualizado

```makefile
	@echo "→ Executando migration 005_silver_cvm (schema silver_cvm)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/005_silver_cvm.sql
	@echo "✓ Migration 005_silver_cvm executada."
	@echo "→ Executando migration 006_gold_cvm (schema gold_cvm)..."
	@docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
		< docker/postgres/migrations/006_gold_cvm.sql
	@echo "✓ Migration 006_gold_cvm executada."
```

---

## Data Flow

```text
1. dag_silver_cvm (@daily) conclui → silver_cvm.fundos + informe_diario atualizados
   dag_gold_bcb  (@daily) conclui → gold_bcb.macro_mensal atualizado
   (paralelo — qualquer ordem)
   │
   ▼ Ambos os ExternalTaskSensors detectam conclusão
2. dag_gold_cvm acorda

3. dbt run --select fundo_diario fundo_mensal
   │
   ├──► fundo_diario.sql
   │      CTE daily: LAG(vl_quota) OVER PARTITION BY cnpj_fundo ORDER BY dt_comptc
   │      SELECT: CASE WHEN NULLIF(vl_quota_anterior, 0) IS NOT NULL THEN ...
   │      DROP TABLE gold_cvm.fundo_diario + CREATE TABLE + INSERT (~6.5M rows)
   │
   └──► fundo_mensal.sql
          CTE monthly_base: FIRST_VALUE + LAST_VALUE + COUNT DISTINCT OVER
          CTE monthly_agg: GROUP BY + SUM + AVG
          CTE enriched: LEFT JOIN fundos (gestor) + LEFT JOIN macro_mensal (alpha)
          SELECT: CASE WHEN NULLIF(vl_quota_inicial, 0) IS NOT NULL THEN ...
          DROP TABLE gold_cvm.fundo_mensal + CREATE TABLE + INSERT (~1.560 rows max)

4. gold_cvm.fundo_diario e gold_cvm.fundo_mensal disponíveis para Metabase
```

---

## Integration Points

| Sistema Externo | Tipo | Mecanismo |
|----------------|------|-----------|
| `silver_cvm.informe_diario` | dbt `ref()` → PostgreSQL table | `ref('informe_diario')` — lido em ambos os modelos |
| `silver_cvm.fundos` | dbt `ref()` → PostgreSQL table | `ref('fundos')` — JOIN para `gestor` em `fundo_mensal` |
| `gold_bcb.macro_mensal` | dbt `ref()` cross-domain → PostgreSQL table | `ref('macro_mensal')` — LEFT JOIN por `ano_mes = m.date` |
| `dag_silver_cvm` | Airflow ExternalTaskSensor | `mode=reschedule`, `timeout=3600` |
| `dag_gold_bcb` | Airflow ExternalTaskSensor | `mode=reschedule`, `timeout=3600` |

---

## Pipeline Architecture

### DAG Diagram

```text
dag_silver_cvm (@daily)  ─── wait_silver_cvm (ExternalTaskSensor) ─┐
                                                                     ├──► dbt_run_gold_cvm
dag_gold_bcb   (@daily)  ─── wait_gold_bcb   (ExternalTaskSensor) ─┘
                                                                          │
                                                               ┌──────────┴──────────┐
                                                               ▼                     ▼
                                                         fundo_diario.sql    fundo_mensal.sql
                                                         (~6.5M rows)        (~1.560 rows)
```

### Estratégia de Materialização

| Model | Strategy | Rationale |
|-------|----------|-----------|
| `fundo_diario` | `table` (full refresh) | 6.5M rows em PostgreSQL local — incremental não justificado no MVP; full refresh idempotente |
| `fundo_mensal` | `table` (full refresh) | ~1.560 rows — trivial para full refresh; evita complexidade incremental |

> **Por que `table` e não `incremental` para `fundo_diario`?** Em PostgreSQL local com 6.5M rows, full refresh leva ~10-20s — aceitável para MVP. Incremental com `delete+insert` exigiria lookback de 30 dias e gerenciamento de `vl_quota_anterior` no join com registros fora da janela (problema de LAG cross-batch). `table` elimina essa classe de bugs.

### Schema Evolution Plan

| Tipo de Mudança | Handling | Rollback |
|-----------------|----------|---------|
| Nova coluna em `fundo_diario` | Adicionar no SELECT; dbt recria a table | Remover do SELECT |
| Nova coluna em `fundo_mensal` | Adicionar no SELECT + CTE relevante; dbt recria | Remover do SELECT |
| `macro_mensal` adiciona coluna BCB | Adicionar ao `enriched` CTE + SELECT | Remover referência |
| Novo valor de `tp_fundo` | Sem impacto — string passada diretamente | N/A |

### Data Quality Gates

| Gate | Ferramenta | Threshold | Ação em Falha |
|------|-----------|-----------|---------------|
| `cnpj_fundo NOT NULL` em `fundo_diario` | dbt test | 0 nulls | Bloqueia (severity: error) |
| `dt_comptc NOT NULL` em `fundo_diario` | dbt test | 0 nulls | Bloqueia (severity: error) |
| `(cnpj_fundo, ano_mes) NOT NULL` em `fundo_mensal` | dbt test | 0 nulls | Bloqueia (severity: error) |
| `meses_com_dados NOT NULL` em `fundo_mensal` | dbt test | 0 nulls | Bloqueia (severity: error) |
| FK `fundo_diario.cnpj_fundo` → `fundos` | dbt test | N/A | Warn (severity: warn) |
| `alpha_selic` não-nulo ≥ 95% | Smoke test manual | Fora do range | Investigar LEFT JOIN `macro_mensal` |
| Zero divisões por zero | Smoke test manual | 0 rows com anomalia | Verificar NULLIF |

---

## Testing Strategy

| Tipo | Escopo | Arquivos | Ferramentas | Meta |
|------|--------|----------|-------------|------|
| dbt tests (schema) | Todos os modelos | `schema.yml` | `dbt test --select fundo_diario fundo_mensal` | 100% colunas críticas |
| Smoke: AT-001 | Rentabilidade diária correta | Query manual PostgreSQL | psql | `(1050-1000)/1000*100 = 5.0` |
| Smoke: AT-002 | Zero divisões por zero | Query manual | psql | 0 rows com `vl_quota_anterior=0` e rentabilidade calculada |
| Smoke: AT-003 | `alpha_selic` correto | Query manual | psql | `1.5 - (10.xx / 12) ≈ valor esperado` |
| Smoke: AT-004 | `meses_com_dados` correto | Query manual | psql | COUNT DISTINCT por fundo no resultado |
| Smoke: AT-005 | Grain `fundo_mensal` | Query deduplicação | psql | 0 duplicatas em `(cnpj_fundo, ano_mes)` |
| Idempotência | `table` full refresh | `dbt run` × 2 | dbt | Row count idêntico |
| DAG E2E | Airflow | `dag_gold_cvm` | Airflow UI | Status success |
| Migration | `006_gold_cvm.sql` × 2 | psql | PostgreSQL | Zero erros na 2ª execução |

---

## Error Handling

| Tipo de Erro | Estratégia | Retry? |
|-------------|------------|--------|
| `dag_silver_cvm` ou `dag_gold_bcb` ainda rodando | ExternalTaskSensor aguarda até 3600s; timeout falha a task | Sim (Airflow retry: 1 vez, 10 min) |
| `macro_mensal` sem match para um mês | LEFT JOIN → `alpha_selic = NULL` — pipeline não falha | N/A |
| `vl_quota = 0` no Silver | NULLIF → `rentabilidade = NULL` — sem erro | N/A |
| dbt compilation error | Build falha explicitamente; sem silêncio | Não (fix manual) |
| `ref('macro_mensal')` indisponível (dag_gold_bcb falhou) | ExternalTaskSensor falha por timeout → DAG falha com erro explícito | Sim (retry) |

---

## Configuration

| Config Key | Tipo | Valor | Descrição |
|-----------|------|-------|-----------|
| `schema` (`fundo_diario`) | string | `gold_cvm` | Schema destino via `dbt_project.yml` |
| `schema` (`fundo_mensal`) | string | `gold_cvm` | Schema destino via `dbt_project.yml` |
| `materialized` (ambos) | string | `table` | Full refresh — sem incremental no MVP |
| `ExternalTaskSensor.timeout` | int | `3600` | Timeout em segundos (cada sensor) |
| `ExternalTaskSensor.poke_interval` | int | `60` | Frequência de verificação (cada sensor) |
| `retries` (DAG) | int | `1` | Retry automático Airflow em falha |
| `retry_delay` (DAG) | timedelta | `10 min` | Intervalo entre retries |
| `alpha_selic` divisor | float | `taxa_anual_bcb / 12` | Conversão anual → mensal (linear) |

---

## Security Considerations

- Credenciais PostgreSQL via env vars — sem hardcoding
- Cross-domain read-only: `dag_gold_cvm` lê `gold_bcb.macro_mensal` mas não escreve no schema BCB
- `gold_cvm` schema separado: modelos Gold não têm permissão de escrita no Silver por design

---

## Observability

| Aspecto | Implementação |
|---------|---------------|
| Logging (dbt) | `dbt run` produz logs no stdout; capturado pelo BashOperator |
| Logging (Airflow) | Logs de task na UI `http://localhost:8080` |
| doc_md (Airflow) | `dag_gold_cvm` tem `doc_md` com tabela de modelos e dependências |
| Row counts | Smoke tests pós-run: `COUNT(*) FROM gold_cvm.fundo_diario` e `fundo_mensal` |
| alpha coverage | `SELECT COUNT(*) FILTER (WHERE alpha_selic IS NOT NULL) / COUNT(*) FROM gold_cvm.fundo_mensal` |

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-30 | design-agent | Versão inicial — 7 artefatos, 5 ADRs inline |
| 1.0 | 2026-04-30 | design-agent | A-002 e A-004 confirmadas pré-design; join key `ON a.ano_mes = m.date` validada |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_GOLD_CVM.md`

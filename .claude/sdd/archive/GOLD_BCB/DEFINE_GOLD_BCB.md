# DEFINE: Gold BCB — Métricas Analíticas Cross-Série

> Modelos dbt Gold no schema gold_bcb do PostgreSQL existente — SELIC real,
> PTAX variação mensal, e expand diário via ref() Silver — consumíveis pelo
> Metabase sem configuração adicional.

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | GOLD_BCB                                         |
| **Data**          | 2026-04-24                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | ✅ Shipped                                       |
| **Clarity Score** | 14/15                                            |
| **Origem**        | BRAINSTORM_GOLD_BCB.md (2026-04-24)              |
| **Upstream**      | SILVER_BCB (shipped 2026-04-24)                  |

---

## Problem Statement

A camada Gold do domínio BCB está ausente: dados da Silver (`silver_bcb`)
contêm indicadores por série mas não métricas cross-série que cruzam SELIC,
IPCA e PTAX. Analistas e dashboards Metabase precisam de `selic_real`
(SELIC acima da inflação), câmbio médio mensal e variação cambial MoM em
tabelas prontas para consumo — não de joins manuais na ferramenta de BI.
Adicionalmente, o projeto dbt `finlake` não tem um mecanismo de schema
customizado (`generate_schema_name`), necessário para materializar Gold em
`gold_bcb` sem concatenar o schema Silver.

---

## Target Users

| Usuário | Papel | Pain Point |
|---------|-------|------------|
| Nilton Coura | Data Engineer / dono da plataforma | Silver sem métricas cross-série; Gold inexistente bloqueia dashboards Metabase |
| Dashboard / Metabase | Consumidor de análise macro | Sem `selic_real` e `ptax_variacao_mensal_pct` pré-calculados, análise requer joins manuais |
| Pipeline futuro | Downstream cross-domain | Gold BCB será fonte para modelos que cruzam com domínio CVM |

---

## Goals

| Prioridade | Goal |
|------------|------|
| **MUST** | Macro `generate_schema_name` em `transform/macros/` para schema exato sem concatenação |
| **MUST** | `dbt_project.yml` com `gold: +schema: gold_bcb` |
| **MUST** | Migration `003_gold_bcb.sql` criando schema `gold_bcb` (idempotente) |
| **MUST** | Modelo `macro_mensal` grain mensal em `gold_bcb` com 7 colunas |
| **MUST** | Modelo `macro_diario` grain diário em `gold_bcb` com 7 colunas via `ref(macro_mensal)` |
| **MUST** | `schema.yml` com `not_null` + `unique` em `date` para ambos os modelos |
| **MUST** | DAG `dag_gold_bcb` com `ExternalTaskSensor` (dag_silver_bcb) + `BashOperator` |
| **SHOULD** | `Makefile` atualizado para rodar `003_gold_bcb.sql` em `make migrate` |
| **COULD** | Metabase verificação manual de visibilidade do schema `gold_bcb` |

---

## Success Criteria

- [ ] `dbt run --select macro_mensal macro_diario --target airflow` executa sem erros — `2 of 2 OK`
- [ ] `gold_bcb.macro_mensal` criada com 7 colunas e tipos corretos
- [ ] `gold_bcb.macro_diario` criada com 7 colunas e tipos corretos
- [ ] `dbt test` retorna `0 failures, 0 errors` para ambos os modelos
- [ ] `gold_bcb.macro_mensal` com ~315 registros (2000-01 a 2026-03)
- [ ] `gold_bcb.macro_mensal.selic_real` ≈ `10.51` para março/2026 (`taxa_anual=14.65 - acumulado_12m=4.14`)
- [ ] `gold_bcb.macro_mensal.ptax_variacao_mensal_pct` IS NULL apenas em 2000-01-01 (primeiro mês)
- [ ] `gold_bcb.macro_diario` com ~6.600 registros (dias úteis desde 2000-01-03)
- [ ] `gold_bcb.macro_diario.acumulado_12m` idêntico ao `macro_mensal.acumulado_12m` do mesmo mês
- [ ] DAG `dag_gold_bcb` aparece na UI do Airflow sem erros de parse
- [ ] `ExternalTaskSensor` aguarda conclusão de `dag_silver_bcb` antes do `dbt run`

---

## Acceptance Tests

| ID | Cenário | Given | When | Then |
|----|---------|-------|------|------|
| AT-001 | `dbt run` cria tabelas Gold | Schema `gold_bcb` existe, Silver populada | `dbt run --select macro_mensal macro_diario` | 2 tabelas criadas, `2 of 2 OK` |
| AT-002 | `dbt test` 0 failures | Tabelas Gold criadas (AT-001) | `dbt test --select macro_mensal macro_diario` | `0 failures, 0 errors, 0 warnings` |
| AT-003 | `selic_real` validada | `taxa_anual=14.6499, acumulado_12m=4.1428` em março/2026 | Query em `gold_bcb.macro_mensal` | `selic_real` entre `10.50` e `10.51` |
| AT-004 | `ptax_variacao_mensal_pct` NULL apenas no primeiro mês | `macro_mensal` com dados desde 2000-01-01 | `SELECT COUNT(*) WHERE ptax_variacao_mensal_pct IS NULL` | `1` (registro de 2000-01-01) |
| AT-005 | Carry forward correto no diário | `macro_diario` com dados de março/2026 | Query `acumulado_12m` para dias de março/2026 | Todos os dias de março têm `acumulado_12m = 4.1428` |
| AT-006 | `macro_diario` grain diário correto | `macro_diario` criada | `SELECT COUNT(*)` | ~6.600 registros (dias úteis SELIC desde 2000) |
| AT-007 | `ExternalTaskSensor` aguarda Silver | `dag_silver_bcb` ainda em execução | `dag_gold_bcb` triggada | `wait_silver_bcb` permanece em `up_for_reschedule` |
| AT-008 | BashOperator executa `dbt run` Gold | Silver completa, sensor success | Task `dbt_run_gold_bcb` executa | Log mostra `2 of 2 OK`, task finaliza como success |
| AT-009 | Schema correto: `gold_bcb` (não `silver_bcb_gold_bcb`) | Macro `generate_schema_name` instalada | `dbt run` executado | Tabelas em `gold_bcb.*`, não em `silver_bcb_gold_bcb.*` |
| AT-010 | Migration idempotente | Schema `gold_bcb` já existente | `003_gold_bcb.sql` executado novamente | Nenhum erro — `IF NOT EXISTS` |

---

## Out of Scope

- **DuckDB como engine Gold** — descartado: complexidade não justificada para ~7k registros
- **`selic_deflacionada_ptax`** — retorno para investidor estrangeiro; concern analítico específico, não macro
- **Correlações pré-computadas** — janela temporal é decisão analítica; `CORR()` ad-hoc no Metabase
- **Dashboards Metabase** — esta feature entrega dados; dashboards são concern de produto
- **`dbt docs generate/serve`** — documentação de portfólio, não pipeline
- **`astronomer-cosmos`** — deferido para 10+ modelos com domínio CVM
- **Gold cross-domain (BCB × CVM)** — feature futura quando BRONZE_CVM estiver na Silver
- **Metabase nova conexão** — Metabase já conecta ao PostgreSQL; apenas verificar visibilidade de `gold_bcb`

---

## Constraints

| Tipo | Constraint | Impacto |
|------|------------|---------|
| Técnico | `generate_schema_name` macro obrigatório — sem ele dbt concatena schemas (`silver_bcb_gold_bcb`) | Tabelas criadas no schema errado, invisíveis para Metabase |
| Técnico | `--select macro_mensal macro_diario` na BashOperator — não `--select domain_bcb` (re-rodaria Silver) | Airflow re-executaria todos os modelos incluindo Silver desnecessariamente |
| Técnico | `date_trunc('month', s.date) = i.date` depende de `i.date` ser sempre o primeiro dia do mês na Bronze | DDL `bronze_bcb.ipca_monthly` confirma: `date` sempre primeiro dia do mês via comment |
| Portfólio | `selic_real` com grounding validado (10.5071%) demonstra domínio financeiro no portfólio | Fórmula deve ser comentada nos modelos SQL |

---

## Technical Context

| Aspecto | Valor | Notas |
|---------|-------|-------|
| **Engine** | PostgreSQL 15 | Mesmo banco Bronze e Silver |
| **Schema** | `gold_bcb` | Criado via `003_gold_bcb.sql` |
| **dbt project** | `transform/` (existente) | Subdiretório `models/domain_bcb/gold/` |
| **dbt adapter** | `dbt-postgres` | Já instalado — zero nova dependência |
| **Macro necessária** | `generate_schema_name` | Padrão dbt para multi-schema sem concatenação |
| **DAG Location** | `dags/domain_bcb/dag_gold_bcb.py` | Mesmo pacote do domínio BCB |
| **Migration Location** | `docker/postgres/migrations/003_gold_bcb.sql` | Segue convenção 001 e 002 |
| **IaC Impact** | Modify existing | `dbt_project.yml`, `Makefile` |

---

## Data Contract

### Source Inventory

| Source | Tipo | Volume | Freshness | Owner |
|--------|------|--------|-----------|-------|
| `silver_bcb.selic_daily` (via `ref`) | PostgreSQL | ~6.606 rows | D-1 | domain_bcb |
| `silver_bcb.ipca_monthly` (via `ref`) | PostgreSQL | ~381 rows | Mensal | domain_bcb |
| `silver_bcb.ptax_daily` (via `ref`) | PostgreSQL | ~6.856 rows | D-1 | domain_bcb |

### Schema Contract — `gold_bcb.macro_mensal`

| Coluna | Tipo | Constraints | Origem | PII? |
|--------|------|-------------|--------|------|
| `date` | DATE | NOT NULL, PK | `date_trunc('month', selic.date)` | Não |
| `taxa_anual` | NUMERIC(8,4) | NOT NULL | `AVG(selic_daily.taxa_anual)` | Não |
| `acumulado_12m` | NUMERIC(8,4) | NOT NULL | `MAX(ipca_monthly.acumulado_12m)` | Não |
| `selic_real` | NUMERIC(8,4) | NOT NULL | `taxa_anual - acumulado_12m` | Não |
| `ptax_media` | NUMERIC(8,4) | NOT NULL | `AVG(ptax_daily.taxa_cambio)` | Não |
| `ptax_variacao_mensal_pct` | NUMERIC(8,4) | NULL no primeiro mês | `LAG(ptax_media)` | Não |
| `transformed_at` | TIMESTAMP | NOT NULL | `current_timestamp` | Não |

### Schema Contract — `gold_bcb.macro_diario`

| Coluna | Tipo | Constraints | Origem | PII? |
|--------|------|-------------|--------|------|
| `date` | DATE | NOT NULL, PK | `selic_daily.date` | Não |
| `taxa_anual` | NUMERIC(8,4) | NOT NULL | `ref('selic_daily')` | Não |
| `taxa_cambio` | NUMERIC(8,4) | NOT NULL | `ref('ptax_daily')` | Não |
| `variacao_diaria_pct` | NUMERIC(8,4) | NULL no primeiro registro | `ref('ptax_daily')` | Não |
| `acumulado_12m` | NUMERIC(8,4) | NOT NULL | `ref('macro_mensal')` carry forward | Não |
| `selic_real` | NUMERIC(8,4) | NOT NULL | `taxa_anual - acumulado_12m` | Não |
| `transformed_at` | TIMESTAMP | NOT NULL | `current_timestamp` | Não |

### Lineage

```
silver_bcb.selic_daily   ──┐
silver_bcb.ipca_monthly  ──┼──▶ gold_bcb.macro_mensal ──┐
silver_bcb.ptax_daily    ──┘                              ├──▶ gold_bcb.macro_diario
silver_bcb.selic_daily   ─────────────────────────────────┤
silver_bcb.ptax_daily    ─────────────────────────────────┘
```

---

## Assumptions

| ID | Assumption | Se errada, impacto | Validado? |
|----|------------|-------------------|-----------|
| A-001 | `date_trunc('month', s.date) = i.date` funciona como join SELIC × IPCA | Join produz resultado incorreto — testar com query direta antes do build | [ ] |
| A-002 | `LAG(ptax_media)` IS NULL apenas em 2000-01-01 (primeiro registro de macro_mensal) | NULL em múltiplos registros — verificar com AT-004 | [ ] |
| A-003 | dbt executa `macro_diario` após `macro_mensal` com `--select macro_mensal macro_diario` | Erro de dependência — dbt respeita grafo de ref() automaticamente | [x] |
| A-004 | `gold_bcb` schema visível no Metabase após criação sem reconfiguração da conexão | Metabase não sincroniza schemas automaticamente — verificar UI após AT-001 | [ ] |

---

## Pré-requisitos Bloqueantes

### PRE-01 — Migration `003_gold_bcb.sql`

```sql
CREATE SCHEMA IF NOT EXISTS gold_bcb;
```

Atualizar `Makefile` target `migrate` para incluir `003_gold_bcb.sql`.

### PRE-02 — Macro `generate_schema_name` em `transform/macros/generate_schema_name.sql`

```sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

Sem este arquivo: `dbt run` com `+schema: gold_bcb` cria tabelas em
`silver_bcb_gold_bcb` (concatenação indesejada) em vez de `gold_bcb`.

### PRE-03 — `dbt_project.yml` atualizado

```yaml
models:
  finlake:
    domain_bcb:
      +materialized: table
      gold:
        +schema: gold_bcb
```

> Não há novos PRE de dependência Python, bind mount ou infraestrutura:
> `dbt-postgres` já instalado, `transform/` já montado no container Airflow.

---

## Clarity Score Breakdown

| Elemento | Score | Justificativa |
|----------|-------|---------------|
| Problem | 3/3 | Gold ausente + dbt sem multi-schema bloqueiam Metabase — específico |
| Users | 2/3 | Data Engineer explícito; Metabase e pipeline CVM como consumidores downstream |
| Goals | 3/3 | MUST/SHOULD/COULD priorizados, fórmulas validadas com dados reais |
| Success | 3/3 | `selic_real ≈ 10.51`, `dbt test 0 failures`, AT-009 valida schema correto |
| Scope | 3/3 | DuckDB e 6 features explicitamente descartadas; YAGNI bem aplicado |
| **Total** | **14/15** | |

**Mínimo para prosseguir: 12/15 ✅**

---

## Open Questions

Nenhuma — pronto para Design.

A-001 e A-004 devem ser validadas no início do Build com query direta e
verificação do Metabase, mas não bloqueiam a especificação.

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-24 | define-agent | Versão inicial from BRAINSTORM_GOLD_BCB.md |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_GOLD_BCB.md`

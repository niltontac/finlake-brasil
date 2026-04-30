# BRAINSTORM: GOLD_CVM

> Exploratory session to clarify intent and approach before requirements capture

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | GOLD_CVM |
| **Date** | 2026-04-29 |
| **Author** | brainstorm-agent |
| **Status** | Ready for Define |

---

## Initial Idea

**Raw Input:** Construir a camada Gold do domínio CVM com métricas de performance de
fundos de investimento, comparativo cross-domain com SELIC e IPCA, e visão por segmento.

**Context Gathered:**
- Gold BCB já existe como padrão de referência: `macro_diario` + `macro_mensal`,
  schema `gold_bcb`, DAG com `ExternalTaskSensor` aguardando Silver antes do `dbt run`
- Silver CVM disponível: `silver_cvm.informe_diario` (6.514.571 registros, 2024 completo,
  grain `cnpj_fundo + dt_comptc`) e `silver_cvm.fundos` (130 fundos operacionais)
- Silver BCB disponível para cross-domain: `selic_daily`, `ipca_monthly`, `ptax_daily`
- Gold BCB `macro_mensal` já consolida SELIC anualizada + IPCA acumulado 12m — reutilizável
- `silver_cvm.informe_diario` é incremental (delete+insert, lookback 30 dias)
- Dados de cota incluem zeros (28.443 registros) e valores negativos (min = -8.701.472)

**Technical Context Observed (for Define):**

| Aspect | Observation | Implication |
|--------|-------------|-------------|
| Likely Location | `transform/models/domain_cvm/gold/` | Espelha estrutura `domain_bcb/gold/` |
| DAG Location | `dags/domain_cvm/dag_gold_cvm.py` | Espelha `dag_gold_bcb.py` |
| Schema override | `dbt_project.yml` com `+schema: gold_cvm` | Requer bloco `gold:` na config `domain_cvm` |
| Migration | `docker/postgres/migrations/006_gold_cvm.sql` | `CREATE SCHEMA IF NOT EXISTS gold_cvm` |
| dbt version | dbt-core 1.11.8 + dbt-postgres 1.10.0 | Window functions PostgreSQL nativas |
| Padrão ref() | `macro_diario` deriva de `macro_mensal` via `ref()` | Para CVM: sem `ref()` entre Gold do mesmo domínio |

---

## Discovery Questions & Answers

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | Granularidade temporal: diário, mensal ou ambos? | Diário + Mensal — replica padrão Gold BCB | Define 2 modelos: `fundo_diario` e `fundo_mensal` |
| 2 | Cross-domain com BCB: embutido no modelo ou schema separado? | `ref('macro_mensal')` no `fundo_mensal` via LEFT JOIN | Dependência dbt explícita; sem duplicação de lógica BCB |
| 3 | Fundos com histórico incompleto: filtrar ou flag? | Incluir tudo + coluna `meses_com_dados` | Metabase controla threshold; Gold não impõe opinião |
| 4 | `fundo_mensal` deriva de `fundo_diario` ou direto do Silver? | Direto do Silver — FIRST/LAST VALUE na cota | Sem acoplamento entre Gold do mesmo domínio |

---

## Sample Data Inventory

| Type | Location | Count | Notes |
|------|----------|-------|-------|
| Query Silver PostgreSQL | `silver_cvm.informe_diario` | 6.514.571 rows | 2024 completo, grain cnpj_fundo + dt_comptc |
| Stats de vl_quota | Resultado de consulta | 28.443 zeros, min = -8.701.472 | Zeros e negativos existem — NULLIF obrigatório |
| Distribuição classe_anbima | `silver_cvm.fundos` | 109/130 sem valor | Campo não confiável para segmentação primária |
| Fundos com dados parciais | `silver_cvm.informe_diario` | Vários com 1 mês | Confirma necessidade de `meses_com_dados` |
| Série temporal de vl_quota | Exemplo fundo FI | Crescimento monotônico | LAG por fundo funciona — gaps são fins de semana (não aparecem na série) |

**Como os dados foram usados:**
- `NULLIF(vl_quota_inicial, 0)` torna-se obrigatório em ambos os modelos
- `classe_anbima` descartada como coluna de segmentação primária no Gold
- LAG confirmado sem necessidade de fill de datas (série já é de dias úteis)
- `meses_com_dados` confirmada como coluna necessária no `fundo_mensal`

---

## Approaches Explored

### Approach A: Dois modelos Gold independentes, ambos do Silver ⭐ Recommended

**Description:** `fundo_diario` e `fundo_mensal` buscam dados diretamente de
`silver_cvm.informe_diario`. Sem `ref()` entre modelos Gold do mesmo domínio.
`fundo_mensal` faz LEFT JOIN em `ref('macro_mensal')` para cross-domain.

**Pros:**
- Sem acoplamento interno entre modelos Gold — falha em um não bloqueia o outro
- SQL limpo: FIRST/LAST VALUE para mensal, LAG para diário — sem `EXP(SUM(LN()))` frágil
- Lineage dbt claro: Silver → Gold (cada modelo tem 1–2 fontes explícitas)
- Espelha exatamente o padrão Gold BCB: modelos independentes, mesma fonte Silver

**Cons:**
- `informe_diario` lido duas vezes (diário e mensal) — custo de I/O duplicado
- Rentabilidade mensal não é derivada dos retornos diários calculados (matematicamente equivalente, porém semanticamente desconectado)

**Why Recommended:** Com 6.5M rows e PostgreSQL local, leitura dupla é irrelevante.
A simplicidade e segurança do FIRST/LAST VALUE supera qualquer ganho semântico do
encadeamento via `ref()`. Zeros e negativos confirmados tornam o `EXP(SUM(LN()))` perigoso.

---

### Approach B: `fundo_mensal` deriva de `ref('fundo_diario')`

**Description:** `fundo_mensal` agrega os retornos diários já calculados em `fundo_diario`
via `ref()`. Rentabilidade mensal = `EXP(SUM(LN(1 + rentabilidade_diaria_pct/100))) - 1`.

**Pros:**
- Lineage explícito: Silver → fundo_diario → fundo_mensal → macro_mensal
- Rentabilidade mensal é produto composto dos retornos diários (matematicamente preciso)

**Cons:**
- `EXP(SUM(LN()))` quebra com zeros e negativos — 28k zeros confirmados
- Dependência interna Gold: falha em `fundo_diario` bloqueia `fundo_mensal`
- Overhead de `ref()` intra-domínio sem benefício prático neste contexto

---

### Approach C: Modelo cross-domain separado `gold_cvm.fundo_benchmark`

**Description:** Um terceiro modelo Gold dedicado ao cruzamento CVM × BCB,
separado dos modelos de performance pura.

**Pros:**
- Cross-domain explicitamente isolado e nomeado

**Cons:**
- Fragmenta análise que o consumidor (Metabase) quer em uma única view mensal
- Duplica colunas de `fundo_mensal` desnecessariamente
- Mais complexidade de DAG e lineage sem ganho real

---

## Data Engineering Context

### Source Systems

| Source | Type | Volume | Freshness |
|--------|------|--------|-----------|
| `silver_cvm.informe_diario` | PostgreSQL 15 | 6.514.571 rows / 2024 | Diário (incremental D-1) |
| `silver_cvm.fundos` | PostgreSQL 15 | 130 rows | Diário (full refresh) |
| `gold_bcb.macro_mensal` | PostgreSQL 15 | ~300 rows | Diário (produzido por dag_gold_bcb) |

### Data Flow

```text
silver_cvm.informe_diario ──┬──► gold_cvm.fundo_diario
                             │     grain: (cnpj_fundo, dt_comptc)
                             │
                             └──► gold_cvm.fundo_mensal
silver_cvm.fundos ──────────────► gold_cvm.fundo_mensal
gold_bcb.macro_mensal ──────────► gold_cvm.fundo_mensal (LEFT JOIN por ano_mes)

DAG: dag_gold_cvm
  ExternalTaskSensor(dag_silver_cvm) ─┐
  ExternalTaskSensor(dag_gold_bcb)  ──┴──► dbt run --select fundo_diario fundo_mensal
```

### Key Data Questions Explored

| # | Question | Answer | Impact |
|---|----------|--------|--------|
| 1 | `vl_quota` tem zeros ou negativos? | Sim — 28.443 zeros, mín = -8.701.472 | `NULLIF(vl_quota_inicial, 0)` obrigatório em ambos os modelos |
| 2 | `classe_anbima` é confiável para segmentação? | Não — 109/130 fundos sem valor | Segmentação primária por `tp_fundo` e `gestor` |
| 3 | LAG precisa de fill de datas (fins de semana)? | Não — série já é de dias úteis | LAG por fundo funciona diretamente |
| 4 | `fundo_mensal` depende de `dag_gold_bcb`? | Sim — `ref('macro_mensal')` | DAG precisa de 2 ExternalTaskSensors |

---

## Selected Approach

| Attribute | Value |
|-----------|-------|
| **Chosen** | Approach A |
| **User Confirmation** | 2026-04-29 (Validação 2) |
| **Reasoning** | Simplicidade, segurança com zeros/negativos, espelha padrão Gold BCB |

---

## Key Decisions Made

| # | Decision | Rationale | Alternative Rejected |
|---|----------|-----------|----------------------|
| 1 | Dois modelos: `fundo_diario` + `fundo_mensal` | Replica padrão Gold BCB (diário + mensal) | Um único modelo abrangente |
| 2 | `fundo_mensal` faz `ref('macro_mensal')` para cross-domain | Reutiliza lógica BCB existente sem duplicação | Modelo cross-domain separado |
| 3 | FIRST/LAST VALUE para rentabilidade mensal | Robusto com zeros e negativos confirmados | `EXP(SUM(LN()))` — frágil com zeros |
| 4 | `NULLIF(vl_quota_inicial, 0)` em ambos os modelos | 28.443 zeros confirmados na Silver | Sem proteção — geraria divisão por zero |
| 5 | `meses_com_dados` como window COUNT DISTINCT | Metabase controla threshold; Gold não impõe | Filtro mínimo fixo no modelo Gold |
| 6 | Segmentação por `tp_fundo` e `gestor` | `classe_anbima` ausente em 84% dos fundos | `classe_anbima` como atributo primário |
| 7 | Dois ExternalTaskSensors no DAG | `fundo_mensal` depende de `macro_mensal` (gold_bcb) | Sensor único só para Silver — race condition com BCB |

---

## Features Removed (YAGNI)

| Feature Suggested | Reason Removed | Can Add Later? |
|-------------------|----------------|----------------|
| `gold_cvm.fundo_benchmark` — modelo cross-domain separado | LEFT JOIN no `fundo_mensal` resolve sem modelo extra | Sim |
| `classe_anbima` como coluna de segmentação primária Gold | 84% dos fundos sem valor — dado não confiável | Sim, se CVM melhorar dados |
| `rentabilidade_anual_pct` acumulada no ano | Derivável no Metabase com `PRODUCT(1 + rentabilidade_mes_pct)` | Sim |
| Volatilidade (desvio padrão dos retornos diários) | Não solicitada — análise avançada | Sim |
| Comparação PTAX (retorno em USD) | Fora do escopo declarado | Sim |
| PySpark para histórico pré-2024 | Silver tem 2024 completo; bulk é fase separada | Sim — já planejado |
| `ref('fundo_diario')` no `fundo_mensal` | `EXP(SUM(LN()))` quebra com zeros; sem benefício real | Não — Approach A é superior |

---

## Incremental Validations

| Section | Presented | User Feedback | Adjusted? |
|---------|-----------|---------------|-----------|
| Arquitetura completa (data flow + DAG) | Validação 1 | Aprovada; confirmou necessidade de 2 sensores | Não |
| Escopo final do MVP + features YAGNI | Validação 2 | Aprovada sem ressalvas | Não |

---

## Suggested Requirements for /define

### Problem Statement (Draft)

Construir a camada Gold do domínio CVM com dois modelos dbt em PostgreSQL: métricas
de performance diária por fundo (`fundo_diario`) e métricas mensais com comparativo
cross-domain contra SELIC e IPCA (`fundo_mensal`), orquestrados por `dag_gold_cvm`
no Airflow, consumíveis pelo Metabase.

### Target Users (Draft)

| User | Pain Point |
|------|------------|
| Analista financeiro (Metabase) | Sem visão consolidada de performance de fundos vs benchmark |
| Engenheiro de dados (portfólio) | Demonstrar pipeline Medallion completo com cross-domain Data Mesh |

### Success Criteria (Draft)

- [ ] `gold_cvm.fundo_diario` populado com rentabilidade diária para todos os 130 fundos
- [ ] `gold_cvm.fundo_mensal` com `alpha_selic` e `alpha_ipca` calculados para 2024
- [ ] `dag_gold_cvm` executa com sucesso aguardando `dag_silver_cvm` e `dag_gold_bcb`
- [ ] `dbt test` passa em todos os modelos Gold CVM
- [ ] Nenhuma divisão por zero — `NULLIF` aplicado onde `vl_quota = 0`
- [ ] Metabase consegue filtrar por `meses_com_dados >= N` e por `tp_fundo` / `gestor`

### Constraints Identified

- PostgreSQL 15 — sem DuckDB (decisão arquitetural consolidada)
- dbt-core 1.11.8 + dbt-postgres 1.10.0
- Silver CVM cobre apenas 2024 — Gold CVM também será 2024
- `vl_quota` tem zeros e negativos — proteção `NULLIF` é requisito, não opcional
- `dag_gold_cvm` depende de `dag_gold_bcb` para o cross-domain — ordem de execução é crítica

### Out of Scope (Confirmed)

- Modelo de segmento Gold por `classe_anbima` / `gestor` / `tp_fundo` (feito via filtro Metabase)
- `rentabilidade_anual_pct` acumulada (derivável no Metabase)
- Volatilidade e drawdown de fundos
- Comparação em USD via PTAX
- Reprocessamento histórico pré-2024 com PySpark

---

## Session Summary

| Metric | Value |
|--------|-------|
| Questions Asked | 4 |
| Approaches Explored | 3 (A ⭐, B, C) |
| Features Removed (YAGNI) | 7 |
| Validations Completed | 2 |
| Sample Data Collected | Sim — stats de vl_quota, distribuição classe_anbima, série temporal |

---

## Next Step

**Ready for:** `/define .claude/sdd/features/BRAINSTORM_GOLD_CVM.md`

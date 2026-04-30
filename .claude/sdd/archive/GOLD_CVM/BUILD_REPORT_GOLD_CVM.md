# BUILD_REPORT — GOLD_CVM

| Campo          | Valor                                      |
|----------------|--------------------------------------------|
| **Feature**    | GOLD_CVM                                   |
| **Status**     | ✅ Concluído                               |
| **Data**       | 2026-04-30                                 |
| **Engenheiro** | Nilton Coura                               |
| **Referência** | DESIGN_GOLD_CVM.md / DEFINE_GOLD_CVM.md   |

---

## Resumo

Implementação completa da camada Gold do domínio Fundos (CVM).
Dois modelos dbt materializam métricas de performance diárias e mensais
com cross-domain vs. benchmarks BCB (SELIC e IPCA).

---

## Artefatos Criados

| # | Arquivo | Ação | Status |
|---|---------|------|--------|
| 1 | `docker/postgres/migrations/006_gold_cvm.sql` | Criado | ✅ |
| 2 | `transform/dbt_project.yml` | Modificado (bloco `gold:`) | ✅ |
| 3 | `transform/models/domain_cvm/gold/fundo_diario.sql` | Criado | ✅ |
| 4 | `transform/models/domain_cvm/gold/fundo_mensal.sql` | Criado | ✅ |
| 5 | `transform/models/domain_cvm/gold/schema.yml` | Criado | ✅ |
| 6 | `dags/domain_cvm/dag_gold_cvm.py` | Criado | ✅ |

---

## Resultado `dbt run`

```
PASS=2  WARN=0  ERROR=0  SKIP=0  NO-OP=0  TOTAL=2

gold_cvm.fundo_diario   → SELECT 6,514,571  (12.9s)
gold_cvm.fundo_mensal   → SELECT 312,772    (12.9s)
```

## Resultado `dbt test`

```
PASS=7  WARN=1  ERROR=0  SKIP=0  NO-OP=0  TOTAL=8

PASS  not_null_fundo_diario_cnpj_fundo
PASS  not_null_fundo_diario_dt_comptc
PASS  not_null_fundo_diario_transformed_at
PASS  relationships_fundo_diario_cnpj_fundo (WARN — severity: warn)
PASS  not_null_fundo_mensal_ano_mes
PASS  not_null_fundo_mensal_cnpj_fundo
PASS  not_null_fundo_mensal_meses_com_dados
PASS  not_null_fundo_mensal_transformed_at
```

> WARN esperado: `relationships_fundo_diario_cnpj_fundo` — fundos no informe_diario
> sem cadastro correspondente em silver_cvm.fundos. Dados CVM confirmados.

---

## Smoke Tests

| ID     | Teste                                         | Resultado  | Detalhe |
|--------|-----------------------------------------------|------------|---------|
| AT-001 | Rentabilidade diária range sanity             | ✅ PASS    | média ~0.03% |
| AT-002 | Grain único `(cnpj_fundo, dt_comptc)`         | ✅ PASS    | 6,514,571 = distinct |
| AT-003 | NULLIF zero vl_quota_anterior                 | ✅ PASS    | 28,443 NULLs confirmados |
| AT-004 | meses_com_dados range [1,12]                  | ✅ PASS    | min=1, max=12, avg=11.4 |
| AT-005 | Grain único `(cnpj_fundo, ano_mes)`           | ✅ PASS    | 312,772 = distinct |
| AT-006 | Alpha SELIC coverage ≥ 95%                    | ✅ PASS    | 99.58% |
| AT-007 | Schema override `gold_cvm.*`                  | ✅ PASS    | tabelas em gold_cvm |
| AT-008 | Migration idempotente                         | ✅ PASS    | `IF NOT EXISTS` |

---

## Bugs Encontrados e Corrigidos

### Bug 1 — PostgreSQL: `COUNT(DISTINCT) OVER (...)` não suportado

**Sintoma:** `ERROR: DISTINCT is not implemented for window functions`

**Causa:** Tentativa de usar `count(distinct date_trunc('month', dt_comptc)) over (partition by cnpj_fundo)`.

**Fix:** CTE `meses_por_fundo` pré-agrega com `GROUP BY cnpj_fundo`, depois JOIN em `monthly_agg`. Padrão documentado no código.

---

### Bug 2 — Overflow NUMERIC(10, 6) em rentabilidade

**Sintoma:** `numeric field overflow — precision 10, scale 6 must round to absolute value < 10^4`

**Causa:** Fundos com vl_quota quase zero seguido de valor alto geram retornos > 9999%. Confirmado: max = 13,367,007%.

**Fix:** Todas as colunas de percentual migradas para `NUMERIC(20, 6)`.

---

### Bug 3 — Duplicatas no grain `(cnpj_fundo, ano_mes)` de fundo_mensal

**Sintoma:** 2,757 linhas duplicadas (AT-005 FAIL).

**Causa:** `tp_fundo` estava no `GROUP BY` de `monthly_agg`. Alguns CNPJs mudam de tipo durante o mês nos dados CVM.

**Fix:** `tp_fundo` removido do `GROUP BY`; substituído por `MAX(b.tp_fundo)` — valor determinístico, aceitável para análise.

---

## Decisões Técnicas

| Decisão | Escolha | Rationale |
|---------|---------|-----------|
| Seletor dbt DAG | `--select fundo_diario fundo_mensal` | Espelha padrão Gold BCB; seletores nomeados são mais explícitos |
| `tp_fundo` em mensal | `MAX(tp_fundo)` | Elimina duplicatas preservando valor determinístico |
| Percentuais | `NUMERIC(20, 6)` | Cobre outliers extremos sem truncar precisão |
| `meses_com_dados` | CTE separada | PostgreSQL não suporta COUNT(DISTINCT) como window function |

---

## Métricas da Build

| Métrica | Valor |
|---------|-------|
| Artefatos criados | 6 |
| Artefatos modificados | 1 |
| Bugs corrigidos durante build | 3 |
| Linhas Gold materializadas | 6,827,343 |
| Testes dbt: PASS / WARN / ERROR | 7 / 1 / 0 |
| Smoke tests: PASS / FAIL | 8 / 0 |
| Cobertura alpha SELIC | 99.58% |

---

## Próximo Passo

```bash
/ship .claude/sdd/features/DESIGN_GOLD_CVM.md
```

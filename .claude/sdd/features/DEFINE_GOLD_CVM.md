# DEFINE: Gold CVM — Métricas de Performance e Cross-Domain de Fundos

> Construir dois modelos Gold dbt em `gold_cvm` — `fundo_diario` (rentabilidade diária por fundo) e `fundo_mensal` (métricas mensais com alpha vs. SELIC e IPCA) — orquestrados por `dag_gold_cvm` e consumíveis pelo Metabase.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | GOLD_CVM |
| **Data** | 2026-04-30 |
| **Autor** | define-agent |
| **Status** | Pronto para Design |
| **Clarity Score** | 15/15 |
| **Origem** | BRAINSTORM_GOLD_CVM.md (2026-04-29) |

---

## Problem Statement

O domínio `domain_funds` tem dados Silver limpos e validados (`silver_cvm.fundos` e `silver_cvm.informe_diario`) mas nenhuma métrica de performance calculada — analistas no Metabase não conseguem responder perguntas básicas como "quais fundos superaram a SELIC em 2024?" sem SQL manual sobre dados brutos de cota e captação. A camada Gold CVM fecha esse gap: calcula rentabilidade diária e mensal por fundo, agrega captação e PL, e entrega comparativo cross-domain com SELIC e IPCA do domínio BCB.

---

## Target Users

| Usuário | Papel | Necessidade |
|---------|-------|-------------|
| Analista financeiro (Metabase) | Consumidor analítico | Visão de performance de fundos vs. benchmark (SELIC, IPCA) sem SQL manual — filtrar por `tp_fundo`, `gestor`, `meses_com_dados` |
| Engenheiro de dados (portfólio) | Builder / demonstração | Demonstrar pipeline Medallion completo com cross-domain Data Mesh (CVM × BCB) em ambiente de produção |

---

## Goals

O que sucesso significa, em ordem de prioridade:

| Prioridade | Goal |
|------------|------|
| **MUST** | `gold_cvm.fundo_diario` materializado como `table` com `rentabilidade_diaria_pct` calculada via LAG para todos os 130 fundos do Silver |
| **MUST** | `gold_cvm.fundo_mensal` materializado como `table` com `rentabilidade_mes_pct`, `captacao_liquida_acumulada`, `vl_patrim_liq_medio`, `meses_com_dados`, `alpha_selic` e `alpha_ipca` |
| **MUST** | `NULLIF(vl_quota_anterior, 0)` aplicado em ambos os modelos — zero divisões por zero (28.443 zeros confirmados na Silver) |
| **MUST** | `dag_gold_cvm` executa com sucesso com 2 `ExternalTaskSensor` (aguardando `dag_silver_cvm` + `dag_gold_bcb`) |
| **MUST** | `dbt test --select domain_cvm` passa com zero errors (warnings aceitos) |
| **SHOULD** | `fundo_mensal` inclui `LEFT JOIN ref('macro_mensal')` para `alpha_selic` e `alpha_ipca` — NULL para meses sem match BCB |
| **SHOULD** | `meses_com_dados` calculado via `COUNT(DISTINCT ano_mes) OVER (PARTITION BY cnpj_fundo)` para permitir filtro no Metabase |
| **COULD** | `dbt source freshness` verificado em `gold_cvm` como parte do pipeline de qualidade |

---

## Success Criteria

Resultados mensuráveis que definem "done":

- [ ] `gold_cvm.fundo_diario` contém rows para os 130 fundos com `rentabilidade_diaria_pct` não-nula onde `vl_quota` e `LAG(vl_quota)` são ambos > 0
- [ ] `gold_cvm.fundo_mensal` contém entre 130 e 1.560 rows (130 fundos × até 12 meses de 2024)
- [ ] Zero rows em `gold_cvm.fundo_diario` com `vl_quota_anterior = 0` e `rentabilidade_diaria_pct` calculada (divisão por zero impossível)
- [ ] `alpha_selic` não-nulo em ≥ 95% das rows de `fundo_mensal` onde `rentabilidade_mes_pct` é não-nulo (LEFT JOIN com `macro_mensal` bem-sucedido para 2024)
- [ ] `dbt test --select domain_cvm` retorna exit code 0 (failures=0; warnings aceitos)
- [ ] `dag_gold_cvm` completa com status `success` na UI do Airflow após `dag_silver_cvm` e `dag_gold_bcb` concluírem
- [ ] Migration `006_gold_cvm.sql` idempotente: executar duas vezes não gera erros

---

## Acceptance Tests

| ID | Cenário | Given | When | Then |
|----|---------|-------|------|------|
| AT-001 | Rentabilidade diária calculada corretamente | Fundo com `vl_quota = 1.050` hoje e `vl_quota = 1.000` ontem | `dbt run --select fundo_diario` | `rentabilidade_diaria_pct = 5.0` para esse registro |
| AT-002 | Zero divisões por zero | `silver_cvm.informe_diario` com 28.443 registros onde `vl_quota = 0` | `dbt run --select fundo_diario` | `rentabilidade_diaria_pct IS NULL` para todos os registros com `vl_quota_anterior = 0`; zero erros de divisão |
| AT-003 | `alpha_selic` calculado no mensal | Fundo com `rentabilidade_mes_pct = 1.5%` em Jan/2024; `macro_mensal` tem SELIC anualizada para Jan/2024 | `dbt run --select fundo_mensal` | `alpha_selic = rentabilidade_mes_pct - (taxa_anual / 12)` para esse fundo/mês |
| AT-004 | `meses_com_dados` correto | Fundo com dados em apenas 3 dos 12 meses de 2024 | `dbt run --select fundo_mensal` | `meses_com_dados = 3` para todas as rows desse fundo |
| AT-005 | `fundo_mensal` grain correto | Silver com múltiplos dias por mês para cada fundo | `dbt run --select fundo_mensal` | Exatamente uma row por `(cnpj_fundo, ano_mes)`; sem duplicatas |
| AT-006 | DAG com 2 sensores | `dag_silver_cvm` e `dag_gold_bcb` concluídas no dia corrente | `dag_gold_cvm` trigger | Ambos os sensores detectam conclusão; `dbt_run_gold_cvm` executa em seguida |
| AT-007 | Schema override `gold_cvm` | `profiles.yml` com `schema: silver_bcb` como default | `dbt run --select domain_cvm` | Ambos os modelos materializados em `gold_cvm.*` — não em `silver_bcb.*` nem `silver_cvm.*` |
| AT-008 | Migration idempotente | `006_gold_cvm.sql` já executada | Executar `006_gold_cvm.sql` pela segunda vez | Zero erros; schema `gold_cvm` intacto com `NOTICE: schema "gold_cvm" already exists, skipping` |
| AT-009 | LEFT JOIN com `macro_mensal` — mês sem match | Mês de 2024 ausente no `gold_bcb.macro_mensal` (improvável mas possível) | `dbt run --select fundo_mensal` | `alpha_selic = NULL`, `alpha_ipca = NULL` para esse mês; pipeline não falha |

---

## Out of Scope

Explicitamente **não incluído** nesta feature:

- **`gold_cvm.fundo_benchmark`** — modelo cross-domain separado: LEFT JOIN em `fundo_mensal` resolve sem artefato extra
- **`classe_anbima` como coluna de segmentação primária**: 84% dos 130 fundos sem valor — dado não confiável; segmentação via `tp_fundo` e `gestor`
- **`rentabilidade_anual_pct` acumulada no ano**: derivável no Metabase com `PRODUCT(1 + rentabilidade_mes_pct)` — sem cálculo no Gold
- **Volatilidade e drawdown**: análise avançada não solicitada — fase futura se necessário
- **Comparação em USD via PTAX**: fora do escopo declarado no brainstorm
- **Reprocessamento histórico pré-2024 com PySpark**: Silver cobre apenas 2024; bulk load é feature separada já planejada
- **`ref('fundo_diario')` no `fundo_mensal`**: rejeitado — `EXP(SUM(LN()))` quebra com zeros e negativos confirmados; FIRST/LAST VALUE direto do Silver é a abordagem correta

---

## Constraints

| Tipo | Restrição | Impacto |
|------|-----------|---------|
| Técnico | PostgreSQL 15 — sem DuckDB para este domínio | Window functions (LAG, FIRST_VALUE, LAST_VALUE, COUNT DISTINCT OVER) disponíveis nativamente no PG |
| Técnico | `dbt_project.yml` precisa de bloco `gold:` dentro de `domain_cvm` com `+schema: gold_cvm` | Sem override, modelos iriam para `silver_cvm` (schema default do profile) |
| Técnico | `vl_quota` tem 28.443 zeros e valores negativos (mín = -8.701.472) | `NULLIF(vl_quota_anterior, 0)` é requisito em ambos os modelos — não opcional |
| Técnico | `fundo_mensal` depende de `gold_bcb.macro_mensal` (cross-domain) | `dag_gold_cvm` precisa de 2 ExternalTaskSensors: um para `dag_silver_cvm` e outro para `dag_gold_bcb` |
| Técnico | dbt-core 1.11.8 requer `data_tests:` + `arguments:` nested | Padrão já estabelecido na Silver CVM — replicar |
| Operacional | Silver CVM cobre apenas 2024 | Gold CVM será exclusivamente 2024 — sem dados históricos nesta feature |
| Operacional | `dag_gold_cvm` é `@daily` mas informe Bronze é mensal | Gold diário é no-op em dias sem novos dados Silver — por design correto |

---

## Technical Context

| Aspecto | Valor | Notas |
|---------|-------|-------|
| **Localização dbt models** | `transform/models/domain_cvm/gold/` | Espelha `transform/models/domain_bcb/gold/` |
| **Schema destino** | `gold_cvm` | Override via `+schema: gold_cvm` no bloco `gold:` dentro de `domain_cvm` em `dbt_project.yml` |
| **DAG location** | `dags/domain_cvm/dag_gold_cvm.py` | Espelha `dags/domain_bcb/dag_gold_bcb.py` |
| **Migration** | `docker/postgres/migrations/006_gold_cvm.sql` | Numeração sequencial após `005_silver_cvm.sql` |
| **Padrão de referência** | `transform/models/domain_bcb/gold/` + `dags/domain_bcb/dag_gold_bcb.py` | Replicar schema.yml, SQL e DAG |
| **Cross-domain ref** | `ref('macro_mensal')` em `fundo_mensal` | Source do modelo Gold BCB — requer `dag_gold_bcb` ativa antes de `dag_gold_cvm` |
| **IaC Impact** | Modificar `Makefile` target `migrate` + `dbt_project.yml` | Adicionar `006_gold_cvm.sql` ao target `migrate`; adicionar bloco `gold:` em `domain_cvm` no `dbt_project.yml` |

---

## Data Contract

### Source Inventory

| Fonte | Tipo | Volume | Freshness | Owner |
|-------|------|--------|-----------|-------|
| `silver_cvm.informe_diario` | PostgreSQL table (incremental) | 6.514.571 rows (2024) | Diário (dag_silver_cvm) | domain_funds |
| `silver_cvm.fundos` | PostgreSQL table | 130 rows | Diário (dag_silver_cvm) | domain_funds |
| `gold_bcb.macro_mensal` | PostgreSQL table | ~315 rows | Diário (dag_gold_bcb) | domain_macro |

### Schema Contract — `gold_cvm.fundo_diario`

| Coluna | Tipo | Restrições | Derivação |
|--------|------|------------|-----------|
| `cnpj_fundo` | `VARCHAR(18)` | `NOT NULL` | Silver direto |
| `dt_comptc` | `DATE` | `NOT NULL` | Silver direto |
| `tp_fundo` | `VARCHAR(50)` | — | Silver direto |
| `vl_quota` | `NUMERIC(22,8)` | — | Silver direto |
| `vl_quota_anterior` | `NUMERIC(22,8)` | — | `LAG(vl_quota) OVER (PARTITION BY cnpj_fundo ORDER BY dt_comptc)` |
| `vl_patrim_liq` | `NUMERIC(22,6)` | — | Silver direto |
| `captacao_liquida` | `NUMERIC(22,6)` | — | Silver direto |
| `rentabilidade_diaria_pct` | `NUMERIC(10,6)` | NULL quando vl_quota_anterior = 0 ou NULL | `(vl_quota - vl_quota_anterior) / NULLIF(vl_quota_anterior, 0) * 100` |
| `transformed_at` | `TIMESTAMP` | `NOT NULL` | `current_timestamp` |

### Schema Contract — `gold_cvm.fundo_mensal`

| Coluna | Tipo | Restrições | Derivação |
|--------|------|------------|-----------|
| `cnpj_fundo` | `VARCHAR(18)` | `NOT NULL` | Agrupamento |
| `ano_mes` | `DATE` | `NOT NULL` | `DATE_TRUNC('month', dt_comptc)` |
| `tp_fundo` | `VARCHAR(50)` | — | Silver direto |
| `gestor` | `TEXT` | — | JOIN `silver_cvm.fundos` |
| `vl_quota_inicial` | `NUMERIC(22,8)` | — | `FIRST_VALUE(vl_quota) OVER (PARTITION BY cnpj_fundo, ano_mes ORDER BY dt_comptc)` |
| `vl_quota_final` | `NUMERIC(22,8)` | — | `LAST_VALUE(vl_quota) OVER (PARTITION BY cnpj_fundo, ano_mes ORDER BY dt_comptc ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)` |
| `rentabilidade_mes_pct` | `NUMERIC(10,6)` | NULL quando vl_quota_inicial = 0 ou NULL | `(vl_quota_final - vl_quota_inicial) / NULLIF(vl_quota_inicial, 0) * 100` |
| `captacao_liquida_acumulada` | `NUMERIC(22,6)` | — | `SUM(captacao_liquida)` |
| `vl_patrim_liq_medio` | `NUMERIC(22,6)` | — | `AVG(vl_patrim_liq)` |
| `nr_cotst_medio` | `NUMERIC(10,2)` | — | `AVG(nr_cotst)` |
| `meses_com_dados` | `INTEGER` | `NOT NULL` | `COUNT(DISTINCT ano_mes) OVER (PARTITION BY cnpj_fundo)` |
| `taxa_anual_bcb` | `NUMERIC(8,4)` | NULL se sem match BCB | LEFT JOIN `macro_mensal.taxa_anual` |
| `acumulado_12m_ipca` | `NUMERIC(8,4)` | NULL se sem match BCB | LEFT JOIN `macro_mensal.acumulado_12m` |
| `alpha_selic` | `NUMERIC(10,6)` | NULL se `rentabilidade_mes_pct` ou `taxa_anual_bcb` for NULL | `rentabilidade_mes_pct - (taxa_anual_bcb / 12)` |
| `alpha_ipca` | `NUMERIC(10,6)` | NULL se `rentabilidade_mes_pct` ou `acumulado_12m_ipca` for NULL | `rentabilidade_mes_pct - (acumulado_12m_ipca / 12)` |
| `transformed_at` | `TIMESTAMP` | `NOT NULL` | `current_timestamp` |

### Freshness SLAs

| Camada | Target | Medição |
|--------|--------|---------|
| `gold_cvm.fundo_diario` | Atualizado até 03:00 UTC diariamente | Conclusão de `dag_gold_cvm` |
| `gold_cvm.fundo_mensal` | Atualizado até 03:00 UTC diariamente (no-op em dias sem novos dados Silver) | Conclusão de `dag_gold_cvm` |

### Completeness Metrics

- `gold_cvm.fundo_diario`: zero rows com `cnpj_fundo` nulo; `rentabilidade_diaria_pct` nula apenas quando `vl_quota_anterior` é NULL ou zero
- `gold_cvm.fundo_mensal`: exatamente uma row por `(cnpj_fundo, ano_mes)` — zero duplicatas; `alpha_selic` não-nulo em ≥ 95% dos meses com rentabilidade calculada

### Lineage Requirements

- `gold_cvm.fundo_diario` ← `silver_cvm.informe_diario` (window LAG + derivação)
- `gold_cvm.fundo_mensal` ← `silver_cvm.informe_diario` (agregação mensal) + `silver_cvm.fundos` (atributos) + `gold_bcb.macro_mensal` (cross-domain LEFT JOIN)

---

## Assumptions

| ID | Assumption | Se Errado, Impacto | Validado? |
|----|------------|-------------------|-----------|
| A-001 | Bloco `gold:` dentro de `domain_cvm` no `dbt_project.yml` com `+schema: gold_cvm` sobrescreve o schema default (`silver_bcb`) e o schema do bloco pai (`silver_cvm`) | Modelos Gold CVM materializariam no schema errado | [ ] Validar com `dbt compile --select domain_cvm` |
| A-002 | `gold_bcb.macro_mensal` tem cobertura para todos os 12 meses de 2024 | `alpha_selic` / `alpha_ipca` NULL em meses sem cobertura (aceitável via LEFT JOIN, mas esperado que seja completo) | [ ] `SELECT COUNT(DISTINCT DATE_TRUNC('month', date)) FROM gold_bcb.macro_mensal WHERE date >= '2024-01-01' AND date < '2025-01-01'` |
| A-003 | `FIRST_VALUE` / `LAST_VALUE` com frame `ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING` funciona corretamente no PostgreSQL 15 para grain mensal | Rentabilidade mensal calculada incorretamente | [ ] Validar com query manual em 1 fundo conhecido |
| A-004 | `date_trunc('month', date)::date` em `macro_mensal` é a chave de join correta (produz primeiro dia do mês) | JOIN falha — nenhum match cross-domain | [ ] `SELECT date, date_trunc('month', date)::date FROM gold_bcb.macro_mensal LIMIT 3` |
| A-005 | Volume de `fundo_diario` (~6.5M rows, table full refresh) é executado dentro do timeout razoável do Airflow | Precisaria de `dagrun_timeout` explícito | [ ] Monitorar duração no primeiro run |

---

## Clarity Score Breakdown

| Elemento | Score (0-3) | Notas |
|----------|-------------|-------|
| Problem | 3 | Problema específico com causa raiz (Gold ausente), impacto mensurável (analistas sem métricas de performance), usuários identificados |
| Users | 3 | 2 usuários com necessidades distintas e pain points explícitos — analista financeiro + engenheiro de portfólio |
| Goals | 3 | 5 MUSTs não-negociáveis + 2 SHOULDs; `NULLIF` como requisito, não opção; dependência cross-domain explícita |
| Success | 3 | 7 critérios testáveis com números (130 fundos, 1.560 rows máx, ≥95% alpha_selic, zero divisões) |
| Scope | 3 | 7 features YAGNI explicitamente excluídas com justificativa; `ref()` intra-Gold rejeitado com razão técnica (zeros/negativos) |
| **Total** | **15/15** | Pronto para Design |

---

## Open Questions

Nenhuma — pronto para Design.

As assumptions A-001 a A-005 são validações de infraestrutura a confirmar durante o Build (via smoke tests), não bloqueadores do Design.

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-30 | define-agent | Versão inicial a partir de BRAINSTORM_GOLD_CVM.md (2026-04-29) |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_GOLD_CVM.md`

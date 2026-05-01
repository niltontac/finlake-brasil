# Metabase CVM — Setup Guide

## Pré-requisitos

- `make up PROFILE=full` rodando
- `gold_cvm.fundo_mensal` populada com 312.772 registros (`make migrate` + `dbt run --select fundo_diario fundo_mensal --target airflow`)
- `gold_bcb.macro_mensal` populada com 315 registros (✅ já disponível do GOLD_BCB)
- Conexão `db_finlake_brasil` configurada no Metabase (✅ já existente do METABASE_BCB)

## 1. Verificar conexão com gold_cvm

Antes de criar os dashboards, confirmar que a conexão aceita o schema `gold_cvm`:

Admin panel → **Browse data → db_finlake_brasil** — ou abrir um SQL Question e executar:

```sql
SELECT COUNT(*) FROM gold_cvm.fundo_mensal WHERE meses_com_dados >= 6;
-- Deve retornar: 276.786 (aprox.)
```

## 2. Criar os dashboards

Criar os 3 dashboards na ordem abaixo. **Os nomes devem ser exatos** — o script de export busca por string exata.

### Dashboard 1: `CVM — Visão Geral`

New dashboard → Nome: **CVM — Visão Geral**

Adicionar 4 cards via **New question → SQL question → db_finlake_brasil**:

---

**Card 1.1 — PL total por tipo de fundo** · Stacked bar · X: `ano_mes` · Color: `tp_fundo`

```sql
SELECT
    ano_mes,
    tp_fundo,
    SUM(vl_patrim_liq_medio)            AS pl_total
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
GROUP BY ano_mes, tp_fundo
ORDER BY ano_mes;
```

---

**Card 1.2 — Captação líquida total por mês** · Line · X: `ano_mes` · Y: `captacao_total`

```sql
SELECT
    ano_mes,
    SUM(captacao_liquida_acumulada)     AS captacao_total
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
GROUP BY ano_mes
ORDER BY ano_mes;
```

---

**Card 1.3 — Nº médio de cotistas por tipo** · Line · X: `ano_mes` · Color: `tp_fundo`

```sql
SELECT
    ano_mes,
    tp_fundo,
    ROUND(AVG(nr_cotst_medio)::numeric, 0)  AS cotistas_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
GROUP BY ano_mes, tp_fundo
ORDER BY ano_mes;
```

---

**Card 1.4 — Fundos com dados suficientes** · Scalar

```sql
SELECT COUNT(DISTINCT cnpj_fundo) AS fundos_com_dados
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6;
```

---

**Filtros globais do Dashboard 1:**

Dashboard → pencil (✏️) → **Add a filter**:

| Filtro | Tipo | Campo |
|--------|------|-------|
| Tipo de fundo | String | `tp_fundo` |
| Período | Date | `ano_mes` |

---

### Dashboard 2: `CVM — Rentabilidade`

New dashboard → Nome: **CVM — Rentabilidade**

---

**Card 2.1 — Top 10 fundos por rentabilidade no mês** · Table · Order: `rentabilidade_mes_pct DESC`

```sql
SELECT
    cnpj_fundo,
    COALESCE(gestor, 'Não informado')        AS gestor,
    ano_mes,
    ROUND(rentabilidade_mes_pct::numeric, 4) AS rentabilidade_mes_pct
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500
ORDER BY rentabilidade_mes_pct DESC
LIMIT 10;
```

---

**Card 2.2 — Alpha SELIC médio por tipo de fundo** · Horizontal bar · X: `alpha_selic_medio`

```sql
SELECT
    tp_fundo,
    ROUND(AVG(alpha_selic)::numeric, 4)  AS alpha_selic_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND alpha_selic IS NOT NULL
GROUP BY tp_fundo
ORDER BY alpha_selic_medio DESC;
```

> Adicionar linha de referência em Y=0: Settings → Add a goal line → Value: 0.

---

**Card 2.3 — Alpha IPCA médio por tipo de fundo** · Horizontal bar · X: `alpha_ipca_medio`

```sql
SELECT
    tp_fundo,
    ROUND(AVG(alpha_ipca)::numeric, 4)   AS alpha_ipca_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND alpha_ipca IS NOT NULL
GROUP BY tp_fundo
ORDER BY alpha_ipca_medio DESC;
```

---

**Card 2.4 — Distribuição de rentabilidade mensal** · Distribution

```sql
SELECT rentabilidade_mes_pct
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500;
```

> Visualização: após executar a query, selecionar **Distribution** no seletor de tipo de gráfico.

---

**Card 2.5 — Top 10 gestores por Alpha SELIC** · Table · Order: `alpha_selic_medio DESC`

```sql
SELECT
    COALESCE(gestor, 'Não informado')        AS gestor,
    COUNT(DISTINCT cnpj_fundo)               AS qtd_fundos,
    ROUND(AVG(alpha_selic)::numeric, 4)      AS alpha_selic_medio,
    ROUND(AVG(vl_patrim_liq_medio)::numeric, 0) AS pl_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND alpha_selic IS NOT NULL
  AND gestor IS NOT NULL
GROUP BY gestor
HAVING COUNT(DISTINCT cnpj_fundo) >= 2
ORDER BY alpha_selic_medio DESC
LIMIT 10;
```

---

**Filtros globais do Dashboard 2:**

Dashboard → pencil (✏️) → **Add a filter**:

| Filtro | Tipo | Campo |
|--------|------|-------|
| Tipo de fundo | String | `tp_fundo` |
| Período | Date | `ano_mes` |

> **Nota:** O filtro `rentabilidade_mes_pct BETWEEN -100 AND 500` está embutido no SQL dos cards — não é filtro de dashboard.

---

### Dashboard 3: `CVM — Fundos vs Macro`

New dashboard → Nome: **CVM — Fundos vs Macro**

> **Nota de arquitetura:** Todos os cards usam apenas `gold_cvm.fundo_mensal`. As colunas
> `taxa_anual_bcb` e `acumulado_12m_ipca` já estão materializadas na tabela Gold (o dbt
> fez o JOIN com `gold_bcb.macro_mensal`). Nenhum JOIN adicional é necessário no Metabase.

---

**Card 3.1 — Rentabilidade média de mercado vs SELIC mensal** · Line · X: `ano_mes`

```sql
SELECT
    ano_mes,
    ROUND(AVG(rentabilidade_mes_pct)::numeric, 4)     AS rent_media_mercado,
    ROUND(MAX(taxa_anual_bcb / 12)::numeric, 4)       AS selic_mensal
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500
  AND taxa_anual_bcb IS NOT NULL
GROUP BY ano_mes
ORDER BY ano_mes;
```

> Configurar duas séries no gráfico: selecionar **Line** e ativar ambas as métricas.

---

**Card 3.2 — Alpha SELIC médio por categoria** · Bar · X: `tp_fundo` · Y: `alpha_selic_medio`

```sql
SELECT
    tp_fundo,
    ROUND(AVG(alpha_selic)::numeric, 4)  AS alpha_selic_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND alpha_selic IS NOT NULL
GROUP BY tp_fundo
ORDER BY alpha_selic_medio DESC;
```

> Adicionar linha de referência em Y=0: Settings → Add a goal line → Value: 0.

---

**Card 3.3 — % fundos que bateram a SELIC no mês** ★ · Line · X: `ano_mes` · Y: `pct_bateu_selic`

```sql
SELECT
    ano_mes,
    ROUND(
        100.0 * SUM(CASE WHEN alpha_selic > 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0)
    ::numeric, 1)                        AS pct_bateu_selic
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND alpha_selic IS NOT NULL
GROUP BY ano_mes
ORDER BY ano_mes;
```

> Card destaque de portfólio: responde "qual % dos fundos bateu a SELIC em cada mês de 2024?".

---

**Card 3.4 — IPCA 12m vs rentabilidade média** · Line · X: `ano_mes`

```sql
SELECT
    ano_mes,
    ROUND(AVG(rentabilidade_mes_pct)::numeric, 4)     AS rent_media_mercado,
    ROUND(MAX(acumulado_12m_ipca / 12)::numeric, 4)   AS ipca_mensal
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500
  AND acumulado_12m_ipca IS NOT NULL
GROUP BY ano_mes
ORDER BY ano_mes;
```

---

**Filtros globais do Dashboard 3:**

Dashboard → pencil (✏️) → **Add a filter**:

| Filtro | Tipo | Campo |
|--------|------|-------|
| Tipo de fundo | String | `tp_fundo` |
| Período | Date | `ano_mes` |

---

## 3. Export e versionamento

Após criar os 3 dashboards com os nomes exatos, executar:

```bash
make metabase-export-cvm
```

Verificar que os 3 JSONs foram gerados:

```bash
python3 -m json.tool docs/metabase/dashboard_cvm_visao_geral.json > /dev/null && echo "OK visao_geral"
python3 -m json.tool docs/metabase/dashboard_cvm_rentabilidade.json > /dev/null && echo "OK rentabilidade"
python3 -m json.tool docs/metabase/dashboard_cvm_fundos_macro.json > /dev/null && echo "OK fundos_macro"
```

Versionar:

```bash
git add docs/metabase/dashboard_cvm_*.json
git commit -m "docs: export Metabase CVM dashboards"
```

## 4. Persistência

Setup e dashboards persistem via volume Docker `metabase-data`. Sobrevive a `make down && make up`. Perdido apenas com `make reset` (remove volumes com `-v`).

## 5. Troubleshooting

| Problema | Causa provável | Solução |
|----------|----------------|---------|
| `gold_cvm.` não encontrado no SQL Question | Permissão de schema | `GRANT USAGE ON SCHEMA gold_cvm TO postgres;` no PostgreSQL |
| Script: "Dashboard X não encontrado" | Nome divergente | Verificar nome exato no Metabase; listar via `GET /api/dashboard` |
| Card não carrega | Tabela vazia | Verificar `SELECT COUNT(*) FROM gold_cvm.fundo_mensal` |
| Histograma Distribution não aparece | Versão Metabase | Usar Bar com bins manuais como alternativa |

# DESIGN: METABASE_CVM — Dashboards de Fundos de Investimento

> Especificação técnica completa para 3 dashboards Metabase, script de export e targets Makefile.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | METABASE_CVM |
| **Data** | 2026-05-01 |
| **Autor** | design-agent |
| **DEFINE** | [DEFINE_METABASE_CVM.md](./DEFINE_METABASE_CVM.md) |
| **Status** | Pronto para Build |

---

## Validações Pré-Design Confirmadas

| Assumption | Status | Evidência |
|------------|--------|-----------|
| A-001: conexão aceita `gold_cvm.` como prefixo | ✅ Confirmado | `SELECT * FROM gold_cvm.fundo_mensal LIMIT 5` → 5 linhas em 50ms |
| Nome da conexão | ✅ Confirmado | `db_finlake_brasil` (renomeada no admin panel) |
| `taxa_anual_bcb` / `acumulado_12m_ipca` em `fundo_mensal` | ✅ Confirmado | Colunas materializadas no Gold — JOIN Metabase desnecessário |

---

## Arquitetura

```
PostgreSQL (finlake)
  ├── gold_cvm.fundo_mensal    (312.772 rows)  ─────────────────────────────┐
  │     taxa_anual_bcb ◄── desnormalizado do Gold JOIN com macro_mensal     │
  │     acumulado_12m_ipca ◄── idem                                         │
  └── gold_bcb.macro_mensal    (315 rows — não usado direto no Metabase)     │
                                                                             │
  Metabase (localhost:3030)  ◄──────── conexão: db_finlake_brasil ──────────┘
    ├── Dashboard: CVM — Visão Geral      (4 SQL Questions)
    ├── Dashboard: CVM — Rentabilidade    (5 SQL Questions)
    └── Dashboard: CVM — Fundos vs Macro  (4 SQL Questions)
                │
                ▼
  scripts/export_metabase_cvm.sh  →  docs/metabase/dashboard_cvm_*.json
                │
                ▼
  Makefile: metabase-export-cvm / metabase-export-all
```

**Insight arquitetural:** `taxa_anual_bcb` e `acumulado_12m_ipca` já estão materializados
em `gold_cvm.fundo_mensal` (Gold JOIN feito pelo dbt). Nenhum card do Dashboard 3 precisa
de JOIN no Metabase — todos os 13 cards usam apenas `gold_cvm.fundo_mensal`.

---

## Decisões Técnicas (ADRs)

### ADR-001 — SQL Question para todos os cards

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-05-01 |

**Contexto:** Metabase oferece Query Builder (GUI) e SQL Question (SQL manual).

**Escolha:** SQL Question para todos os 13 cards.

**Rationale:** SQL é reproduzível — qualquer pessoa que clonar o repo consegue recriar os cards colando o SQL do DESIGN. Query Builder gera metadados opacos que não se traduzem em documentação. Cards com filtros (`BETWEEN`, `IS NOT NULL`) ou `CASE WHEN` exigem SQL de qualquer forma.

**Alternativa rejeitada:** Query Builder para cards simples — rejeitado porque mistura dois modos e reduz reprodutibilidade do setup.

**Consequências:** Setup mais lento (13 passos manuais), mas SETUP_CVM.md cobre tudo com SQL copy-paste.

---

### ADR-002 — Sem JOIN no Metabase

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-05-01 |

**Contexto:** Dashboard 3 (Fundos vs Macro) originalmente planejado com 2 cards usando JOIN `fundo_mensal × macro_mensal` no Metabase.

**Escolha:** Todos os cards usam apenas `gold_cvm.fundo_mensal` — sem JOIN no Metabase.

**Rationale:** `taxa_anual_bcb` e `acumulado_12m_ipca` já estão materializados na tabela Gold (dbt fez o JOIN). JOIN no Metabase seria redundante e mais lento. Princípio: a camada Gold deve entregar dados prontos para consumo sem transformação adicional.

**Consequências:** Queries mais simples, performance melhor, separação limpa de camadas.

---

### ADR-003 — Script seguindo padrão export_metabase.sh

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-05-01 |

**Contexto:** `export_metabase.sh` (BCB) é artefato em produção com padrão estabelecido.

**Escolha:** `export_metabase_cvm.sh` segue o mesmo padrão: autenticação via `/api/session`, busca por nome exato via `/api/dashboard`, download via `/api/dashboard/{id}`.

**Diferença:** array `DASHBOARDS` com 3 entradas (nome:arquivo) em vez de variáveis simples — loop sobre o array reduz duplicação para N dashboards.

**Consequências:** Zero risco de regressão no BCB; padrão extensível para futuros domínios.

---

## File Manifest

| # | Arquivo | Ação | Propósito | Dependências |
|---|---------|------|-----------|--------------|
| 1 | `scripts/export_metabase_cvm.sh` | Criar | Script de export dos 3 dashboards CVM | Nenhuma |
| 2 | `docs/metabase/SETUP_CVM.md` | Criar | Guia de criação manual dos dashboards + SQL de todos os cards | Nenhuma |
| 3 | `Makefile` | Modificar | Adicionar targets `metabase-export-cvm` e `metabase-export-all` | 1 |

> **Artefatos gerados após setup manual** (não são código — produzidos pelo script):
> - `docs/metabase/dashboard_cvm_visao_geral.json`
> - `docs/metabase/dashboard_cvm_rentabilidade.json`
> - `docs/metabase/dashboard_cvm_fundos_macro.json`

---

## Padrões de Código

### Artefato 1 — `scripts/export_metabase_cvm.sh`

```bash
#!/usr/bin/env bash
# Exporta 3 dashboards CVM do Metabase para docs/metabase/
# Uso: make metabase-export-cvm
# Requer: METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env

set -euo pipefail

METABASE_URL="${METABASE_URL:-http://localhost:3030}"
EMAIL="${METABASE_ADMIN_EMAIL:?Defina METABASE_ADMIN_EMAIL no .env}"
PASSWORD="${METABASE_ADMIN_PASSWORD:?Defina METABASE_ADMIN_PASSWORD no .env}"
OUTPUT_DIR="docs/metabase"

# Formato: "Nome do Dashboard:nome_do_arquivo.json"
DASHBOARDS=(
    "CVM — Visão Geral:dashboard_cvm_visao_geral.json"
    "CVM — Rentabilidade:dashboard_cvm_rentabilidade.json"
    "CVM — Fundos vs Macro:dashboard_cvm_fundos_macro.json"
)

mkdir -p "${OUTPUT_DIR}"

echo "→ Autenticando em ${METABASE_URL}..."
TOKEN=$(curl -sf -X POST "${METABASE_URL}/api/session" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

for entry in "${DASHBOARDS[@]}"; do
    NAME="${entry%%:*}"
    FILE="${OUTPUT_DIR}/${entry##*:}"

    echo "→ Buscando dashboard '${NAME}'..."
    DASHBOARD_ID=$(curl -sf "${METABASE_URL}/api/dashboard" \
        -H "X-Metabase-Session: ${TOKEN}" \
        | python3 -c "
import sys, json
dashboards = json.load(sys.stdin)
match = next((d for d in dashboards if d['name'] == '${NAME}'), None)
if not match:
    names = [d['name'] for d in dashboards]
    raise SystemExit(f'Dashboard \"${NAME}\" nao encontrado. Disponiveis: {names}')
print(match['id'])
")

    echo "→ Exportando dashboard ID=${DASHBOARD_ID}..."
    curl -sf "${METABASE_URL}/api/dashboard/${DASHBOARD_ID}" \
        -H "X-Metabase-Session: ${TOKEN}" \
        | python3 -m json.tool > "${FILE}"

    echo "✓ ${FILE}"
done

echo ""
echo "Commit com:"
echo "  git add docs/metabase/dashboard_cvm_*.json"
echo "  git commit -m 'docs: export Metabase CVM dashboards'"
```

---

### Artefato 3 — Makefile (targets a adicionar)

Localizar bloco `metabase-export:` e adicionar após ele:

```makefile
metabase-export-cvm: ## Exporta 3 dashboards CVM para docs/metabase/ (requer 'make up PROFILE=full' e .env)
	@set -a && . ./.env && set +a && bash scripts/export_metabase_cvm.sh

metabase-export-all: ## Exporta todos os dashboards BCB + CVM (requer 'make up PROFILE=full' e .env)
	@set -a && . ./.env && set +a && bash scripts/export_metabase.sh
	@set -a && . ./.env && set +a && bash scripts/export_metabase_cvm.sh
```

---

## SQL de todos os cards (copy-paste ready)

### Dashboard 1: `CVM — Visão Geral`

**Configuração global:** Filtro `meses_com_dados >= 6` em todos os cards.

**Card 1.1 — PL total por tipo de fundo** · Stacked bar · X: `ano_mes` · Y: `pl_total` · Color: `tp_fundo`
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

**Card 1.3 — Nº médio de cotistas por tipo** · Line · X: `ano_mes` · Y: `cotistas_medio` · Color: `tp_fundo`
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

**Card 1.4 — Fundos com dados suficientes** · Scalar
```sql
SELECT COUNT(DISTINCT cnpj_fundo) AS fundos_com_dados
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6;
```

---

### Dashboard 2: `CVM — Rentabilidade`

**Configuração global:** Filtro `meses_com_dados >= 6`. Cards de rentabilidade têm `BETWEEN -100 AND 500` embutido no SQL.

**Card 2.1 — Top 10 fundos por rentabilidade no mês** · Table · Order: `rentabilidade_mes_pct DESC`
```sql
SELECT
    cnpj_fundo,
    COALESCE(gestor, 'Não informado')       AS gestor,
    ano_mes,
    ROUND(rentabilidade_mes_pct::numeric, 4) AS rentabilidade_mes_pct
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500
ORDER BY rentabilidade_mes_pct DESC
LIMIT 10;
```

**Card 2.2 — Alpha SELIC médio por tipo de fundo** · Horizontal bar · X: `alpha_selic_medio` · Y: `tp_fundo`
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

**Card 2.3 — Alpha IPCA médio por tipo de fundo** · Horizontal bar · X: `alpha_ipca_medio` · Y: `tp_fundo`
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

**Card 2.4 — Distribuição de rentabilidade mensal** · Bar (distribution) · X: `rentabilidade_mes_pct`
```sql
SELECT rentabilidade_mes_pct
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500;
```
> Visualização: selecionar **Distribution** no tipo de gráfico do Metabase.

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

### Dashboard 3: `CVM — Fundos vs Macro`

**Nota de arquitetura:** Todos os cards usam apenas `gold_cvm.fundo_mensal` — `taxa_anual_bcb` e `acumulado_12m_ipca` já estão materializados (ADR-002).

**Card 3.1 — Rentabilidade média de mercado vs SELIC mensal** · Line (dual axis) · X: `ano_mes`
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
> Configurar duas séries: `rent_media_mercado` (eixo Y esq.) + `selic_mensal` (eixo Y dir. ou sobreposta).

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
> Adicionar linha de referência em Y=0 ("Goal line" nas configurações do card).

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

**Card 3.4 — IPCA 12m vs rentabilidade média** · Line (dual axis) · X: `ano_mes`
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

## Estratégia de Testes

| AT | Tipo | Como executar |
|----|------|---------------|
| AT-001 | Manual — Dashboard carrega | Abrir Metabase → "CVM — Visão Geral" → todos os 4 cards visíveis |
| AT-002 | Manual — Outliers ausentes | Visualizar histograma (Card 2.4) — escala deve ser -100% a 500% |
| AT-003 | Manual — Top gestores | Card 2.5 retorna tabela com `gestor`, `qtd_fundos`, `alpha_selic_medio` |
| AT-004 | Manual — Card estrela | Card 3.3 retorna série temporal de 12 pontos entre 0% e 100% |
| AT-005 | Manual — Linha dupla SELIC | Card 3.1 exibe duas séries para jan-dez 2024 |
| AT-006 | Script — Export válido | `make metabase-export-cvm` → `python3 -m json.tool docs/metabase/dashboard_cvm_*.json` sem erro |
| AT-007 | Script — Idempotência | Re-executar `make metabase-export-cvm` → sem erro, arquivos sobrescritos |
| AT-008 | Script — Zero regressão BCB | `make metabase-export-all` → BCB JSON e CVM JSONs gerados sem erro |

**Ordem de execução sugerida:**
1. Criar dashboards na UI (SETUP_CVM.md)
2. Validar AT-001 a AT-005 navegando os dashboards
3. Executar `make metabase-export-cvm` (AT-006, AT-007)
4. Executar `make metabase-export-all` (AT-008)

---

## Conteúdo de SETUP_CVM.md

O guia deve conter (na ordem de execução):

1. **Pré-requisitos** — `make up PROFILE=full`, tabelas Gold populadas
2. **Conexão** — confirmar que `db_finlake_brasil` está ativa; testar `SELECT * FROM gold_cvm.fundo_mensal LIMIT 5` em SQL Question
3. **Ordem de criação** — Dashboard 1, 2, 3 (nomes exatos — script busca por nome)
4. **SQL de cada card** — copiar do DESIGN (seção acima), com nome do card, tipo de visualização e configuração de eixos
5. **Filtros globais** — como adicionar filtro de dashboard no Metabase (Dashboard → Edit → Add a filter)
6. **Export** — `make metabase-export-cvm` e commit
7. **Troubleshooting** — se `gold_cvm.` não for reconhecido, verificar permissões PostgreSQL; se script não encontrar dashboard, verificar nome exato

---

## Notas de Implementação

- **Nomes dos dashboards:** exatos como definidos — script usa match exato por string
- **Conexão nos SQL Questions:** selecionar `db_finlake_brasil` na dropdown de database
- **Filtros de dashboard:** adicionar após criar todos os cards — "meses_com_dados >= 6" e "tp_fundo" como filtros interativos de dashboard; o filtro `BETWEEN -100 AND 500` fica embutido no SQL (não como filtro de dashboard)
- **Ordem de criação dos filtros globais:** Dashboard → pencil icon → "Add a filter" → Field Filter → `meses_com_dados` (Number) + `tp_fundo` (String) + `ano_mes` (Date)
- **Card 3.3 (% fundos):** `NULLIF(COUNT(*), 0)` protege contra divisão por zero em meses sem dados

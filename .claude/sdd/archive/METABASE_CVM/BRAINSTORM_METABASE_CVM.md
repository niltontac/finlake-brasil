# BRAINSTORM: METABASE_CVM

> Phase 0 — Exploração e decisões arquiteturais
> Data: 2026-04-30
> Autor: Nilton Coura

---

## Metadata

| Atributo         | Valor                                               |
|------------------|-----------------------------------------------------|
| **Feature**      | METABASE_CVM                                        |
| **Domínio**      | domain_funds (CVM)                                  |
| **Fase**         | Visualização — fechando o ciclo Medallion CVM       |
| **Upstream**     | GOLD_CVM (shipped 2026-04-30)                       |
| **Referência**   | METABASE_BCB (shipped 2026-04-26) — padrão visual   |
| **Próxima fase** | `/define .claude/sdd/features/BRAINSTORM_METABASE_CVM.md` |

---

## Objetivo

Fechar o ciclo completo Bronze → Silver → Gold → Visualização do domínio CVM.
Metabase já está configurado e operacional com o dashboard BCB como referência visual.
A feature entrega: 3 dashboards temáticos CVM com 13 cards totais, script de export
dedicado (`export_metabase_cvm.sh`), guia de setup (`SETUP_CVM.md`) e JSON versionados
em `docs/metabase/` — artefatos de portfólio para quem clonar o repositório.

O **Dashboard 3 (Fundos vs Macro)** é o destaque: cross-domain BCB × CVM com JOIN
SQL no Metabase, mostrando a porcentagem de fundos que bateram a SELIC por mês —
o card mais analítico e diferenciador do portfólio.

---

## Contexto do Projeto

Gold CVM operacional (shipped 2026-04-30):

| Tabela | Rows | Grain | Destaques |
|--------|------|-------|-----------|
| `gold_cvm.fundo_diario` | 6.514.571 | (cnpj_fundo, dt_comptc) | vl_quota, vl_patrim_liq, captacao_liquida, rentabilidade_diaria_pct |
| `gold_cvm.fundo_mensal` | 312.772 | (cnpj_fundo, ano_mes) | alpha_selic, alpha_ipca, taxa_anual_bcb, acumulado_12m_ipca, gestor |

**Dados validados:**
- 29.164 fundos distintos no informe (maioria cancelados com histórico em 2024)
- 130 fundos com sit `EM FUNCIONAMENTO NORMAL` ou `LIQUIDAÇÃO` (silver_cvm.fundos)
- `meses_com_dados`: min=1, max=12, avg=11.4 — filtro padrão: `>= 6`
- `rentabilidade_mes_pct`: max = 13.367.007% — outlier real (fundos com cota ~zero)
- `alpha_selic` e `alpha_ipca` pré-calculados no Gold: positivo = fundo superou o benchmark

Gold BCB disponível para cross-domain:

| Tabela | Rows | Grain | Colunas chave |
|--------|------|-------|---------------|
| `gold_bcb.macro_mensal` | 315 | Mensal | `taxa_anual`, `acumulado_12m`, `ptax_media` |
| `gold_bcb.macro_diario` | 6.592 | Diário | `selic_real`, `taxa_cambio` |

**Infraestrutura Metabase (herdada do METABASE_BCB):**
- Container: `finlake-metabase`, porta `3000` interna → `3030` host
- Banco de metadados: H2 embarcado com volume Docker `metabase-data` (persiste entre `down/up`)
- Conexão `FinLake Brasil` já configurada: `postgres:5432`, database `finlake`, schema `gold_bcb`
- Dashboards BCB já existem como referência de layout e estilo visual

---

## Discovery Questions & Answers

| # | Pergunta | Resposta | Impacto |
|---|----------|----------|---------|
| 1 | Quantos dashboards e qual estrutura? | 3 dashboards temáticos | Define escopo de cards e SETUP_CVM.md |
| 2 | Como tratar outliers de rentabilidade? | Filtro hard no SQL dos cards (BETWEEN -100, 500) + Gold intacto | Sem view adicional; filtro documentado no SETUP |
| 3 | Como fazer cross-domain no Dashboard 3? | Alpha pré-calculado do Gold + taxa_anual_bcb como linha de referência | 2 cards com JOIN SQL; 2 cards sem JOIN |
| 4 | Estratégia de export/versionamento? | Script dedicado `export_metabase_cvm.sh`; não alterar script BCB | Zero risco de regressão no METABASE_BCB |

---

## Sample Data Inventory

| Tipo | Fonte | Rows | Notas |
|------|-------|------|-------|
| Tabela Gold mensal | `gold_cvm.fundo_mensal` | 312.772 | Fonte primária dos dashboards |
| Tabela Gold diário | `gold_cvm.fundo_diario` | 6.514.571 | Não usado nos dashboards MVP — granularidade diária desnecessária |
| Tabela macro BCB | `gold_bcb.macro_mensal` | 315 | JOIN no Dashboard 3 via `ano_mes` |
| Dashboard referência | `docs/metabase/dashboard_bcb_macro.json` | — | Padrão visual e de export a seguir |

---

## Abordagens Exploradas

### Abordagem A: 3 Dashboards Temáticos com filtro SQL embutido ⭐ Selecionada

**Descrição:** 3 dashboards independentes, cada um com foco analítico específico.
Filtros de outlier aplicados diretamente no SQL dos cards de rentabilidade.
Gold intacto com dados reais. Script de export dedicado, separado do BCB.

**Pros:**
- Separação limpa por audiência/pergunta analítica
- Gold preservado — decisão de visualização não contamina dados
- Sem artefatos novos no PostgreSQL (sem views extras)
- Escalável: cada dashboard pode evoluir independentemente

**Cons:**
- 13 cards para criar manualmente na UI (vs 3 do BCB)
- 2 cards do Dashboard 3 exigem SQL manual com JOIN (não Query Builder simples)

**Por que selecionada:** Alinha com o padrão METABASE_BCB (semi-automatizado),
demonstra capacidade analítica cross-domain e é o modelo mais didático para portfólio.

---

### Abordagem B: View Analítica no PostgreSQL

**Descrição:** Criar `gold_cvm.fundo_mensal_analytic` como VIEW com filtro embutido
(`rentabilidade_mes_pct BETWEEN -100 AND 500`, `meses_com_dados >= 6`). Metabase
aponta para a view.

**Por que rejeitada:** Adiciona artefato fora do ciclo dbt sem ganho real — o filtro
no card SQL é equivalente e mais transparente. Qualquer alteração futura no filtro
exigiria migration adicional.

---

### Abordagem C: Script Genérico Substituindo export_metabase.sh

**Descrição:** Refatorar `export_metabase.sh` em script genérico para todos os dashboards.

**Por que rejeitada:** Altera artefato já em produção do METABASE_BCB sem ganho funcional.
Script dedicado `export_metabase_cvm.sh` é mais seguro e segue o princípio de separação
de responsabilidades entre domínios.

---

## Dashboards e Cards

### Dashboard 1: CVM — Visão Geral

**Fonte:** `gold_cvm.fundo_mensal`
**Filtros globais:** `meses_com_dados >= 6`, `tp_fundo` (multi-select), `ano_mes` range

| Card | Tipo | Métrica | Eixo X |
|------|------|---------|--------|
| PL total por tipo de fundo | Stacked bar | `sum(vl_patrim_liq_medio)` por `tp_fundo` | `ano_mes` |
| Captação líquida acumulada | Linha | `sum(captacao_liquida_acumulada)` | `ano_mes` |
| Nº médio de cotistas por tipo | Linha | `avg(nr_cotst_medio)` por `tp_fundo` | `ano_mes` |
| Fundos com dados suficientes | Escalar | `count(distinct cnpj_fundo) WHERE meses_com_dados >= 6` | — |

---

### Dashboard 2: CVM — Rentabilidade

**Fonte:** `gold_cvm.fundo_mensal`
**Filtros globais:** `meses_com_dados >= 6`, `tp_fundo` (multi-select), `ano_mes` range
**Filtro adicional nos cards de rentabilidade:** `rentabilidade_mes_pct BETWEEN -100 AND 500`

| Card | Tipo | Métrica | Notas |
|------|------|---------|-------|
| Top 10 fundos por rentabilidade | Tabela | `cnpj_fundo`, `gestor`, `rentabilidade_mes_pct` | Filtro BETWEEN obrigatório |
| Alpha SELIC médio por tp_fundo | Barra horizontal | `avg(alpha_selic)` por `tp_fundo` | Linha de base em 0 |
| Alpha IPCA médio por tp_fundo | Barra horizontal | `avg(alpha_ipca)` por `tp_fundo` | Linha de base em 0 |
| Distribuição de rentabilidade | Histograma | `rentabilidade_mes_pct` | Filtro BETWEEN obrigatório |
| Top 10 gestores por Alpha SELIC | Tabela | `gestor`, `count(distinct cnpj_fundo)`, `avg(alpha_selic)`, `avg(vl_patrim_liq_medio)` | Responde: quem bate a SELIC consistentemente? |

---

### Dashboard 3: CVM — Fundos vs Macro ★ Destaque de Portfólio

**Fontes:** `gold_cvm.fundo_mensal` JOIN `gold_bcb.macro_mensal` via `ano_mes`
**Filtros globais:** `meses_com_dados >= 6`, `tp_fundo` (multi-select), `ano_mes` range
**Filtro adicional:** `rentabilidade_mes_pct BETWEEN -100 AND 500`

| Card | Tipo | Métrica | JOIN? |
|------|------|---------|-------|
| Rentabilidade média de mercado vs SELIC | Linha dupla | `avg(rentabilidade_mes_pct)` + `taxa_anual` | Sim — SQL manual |
| Alpha SELIC médio por categoria | Barra | `avg(alpha_selic)` por `tp_fundo` | Não — pré-calculado |
| % fundos que bateram SELIC no mês ★ | Linha temporal | `count(alpha_selic > 0) / count(*)` por `ano_mes` | Não — pré-calculado |
| IPCA 12m vs rentabilidade média | Linha dual | `avg(rentabilidade_mes_pct)` + `acumulado_12m_ipca` | Sim — SQL manual |

> **Card Estrela:** "% fundos que bateram SELIC no mês" — pergunta direta ao mercado,
> usa `alpha_selic` já calculado no Gold, sem JOIN. Melhor card para demo de portfólio.

---

## Conexão PostgreSQL → Metabase (CVM)

A conexão `FinLake Brasil` já existe (schema default: `gold_bcb`).
Para acessar `gold_cvm`, os cards SQL devem referenciar o schema explicitamente:

```sql
-- Exemplo: sem trocar a conexão padrão
SELECT * FROM gold_cvm.fundo_mensal WHERE meses_com_dados >= 6
```

Alternativa: criar segunda conexão com `default schema = gold_cvm` no admin panel.
**Decisão MVP:** usar a conexão existente com prefixo `gold_cvm.` no SQL — sem nova conexão.

---

## Script de Export

```bash
# scripts/export_metabase_cvm.sh
# Exporta 3 dashboards CVM para docs/metabase/
# Uso: make metabase-export-cvm

set -euo pipefail

METABASE_URL="${METABASE_URL:-http://localhost:3030}"
EMAIL="${METABASE_ADMIN_EMAIL:?Defina METABASE_ADMIN_EMAIL no .env}"
PASSWORD="${METABASE_ADMIN_PASSWORD:?Defina METABASE_ADMIN_PASSWORD no .env}"

DASHBOARDS=(
  "CVM — Visão Geral:dashboard_cvm_visao_geral.json"
  "CVM — Rentabilidade:dashboard_cvm_rentabilidade.json"
  "CVM — Fundos vs Macro:dashboard_cvm_fundos_macro.json"
)

mkdir -p docs/metabase

TOKEN=$(curl -sf -X POST "${METABASE_URL}/api/session" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

for entry in "${DASHBOARDS[@]}"; do
  NAME="${entry%%:*}"
  FILE="docs/metabase/${entry##*:}"

  ID=$(curl -sf "${METABASE_URL}/api/dashboard" \
    -H "X-Metabase-Session: ${TOKEN}" \
    | python3 -c "
import sys, json
ds = json.load(sys.stdin)
m = next((d for d in ds if d['name'] == '${NAME}'), None)
if not m: raise SystemExit(f'Não encontrado: ${NAME}')
print(m['id'])")

  curl -sf "${METABASE_URL}/api/dashboard/${ID}" \
    -H "X-Metabase-Session: ${TOKEN}" \
    | python3 -m json.tool > "${FILE}"
  echo "✓ ${FILE}"
done
```

**Makefile targets:**
```makefile
metabase-export-cvm: ## Exporta 3 dashboards CVM (requer 'make up PROFILE=full' e .env)
	@bash scripts/export_metabase_cvm.sh

metabase-export-all: ## Exporta todos os dashboards (BCB + CVM)
	@bash scripts/export_metabase.sh
	@bash scripts/export_metabase_cvm.sh
```

---

## Estrutura de Arquivos

```
scripts/
├── export_metabase.sh              ← EXISTENTE (BCB — não alterar)
└── export_metabase_cvm.sh          ← NOVO: exporta 3 dashboards CVM

docs/metabase/
├── SETUP.md                        ← EXISTENTE (BCB)
├── SETUP_CVM.md                    ← NOVO: guia de conexão + filtros + card SQL
├── dashboard_bcb_macro.json        ← EXISTENTE
├── dashboard_cvm_visao_geral.json      ← GERADO manualmente após setup
├── dashboard_cvm_rentabilidade.json    ← GERADO manualmente após setup
└── dashboard_cvm_fundos_macro.json     ← GERADO manualmente após setup

Makefile
  ├── metabase-export-cvm           ← NOVO
  └── metabase-export-all           ← NOVO
```

---

## YAGNI — Features Removidas

| Feature | Decisão | Motivo |
|---------|---------|--------|
| Automação via API (criar cards por script) | Removida | UI faz em 15 min; API são 300+ linhas sem ganho de portfólio |
| Script de import/restore | Removida | JSON exportado já é o artefato de reprodutibilidade |
| Dashboard fundo individual (drill por CNPJ) | Deferida | 6.5M rows em fundo_diario; escopo de feature separada se necessário |
| Card de gestor por PL no Dashboard 1 | Removida | Volume por tp_fundo já representa a visão de mercado; gestor fica no Dashboard 2 por alpha |
| `fundo_diario` como fonte de cards | Removida | 6.5M rows; fundo_mensal (312K) tem granularidade suficiente para todos os MVPs |
| Segunda conexão no Metabase para gold_cvm | Removida | Prefixo `gold_cvm.` no SQL é suficiente; sem overhead de configuração |
| Collections e permissões Metabase | Removida | Ambiente local single-user |
| Relatórios agendados | Removida | Fora do escopo de portfólio local |

---

## Assumptions

| ID | Assumption | Impacto se errada |
|----|------------|-------------------|
| A-001 | Conexão `FinLake Brasil` existente aceita `gold_cvm.` como prefixo de schema nos cards SQL | Precisar criar segunda conexão com `default schema = gold_cvm` |
| A-002 | JOIN `fundo_mensal × macro_mensal` via `ano_mes` funciona no SQL Question do Metabase sem ambiguidade | Verificar se Metabase exige `CAST(ano_mes AS text)` em algum dialeto |
| A-003 | `alpha_selic` e `alpha_ipca` têm valores numéricos válidos para fundos com `meses_com_dados >= 6` | Verificar NULLs — pode precisar de `COALESCE(alpha_selic, 0)` |
| A-004 | Volume Docker `metabase-data` persiste dashboards BCB existentes — nenhum reset necessário | Se wizard precisar ser refeito, BCB dashboards também serão perdidos |
| A-005 | Script `export_metabase_cvm.sh` encontra dashboards pelos nomes exatos usados na criação | Se nomes divergirem, listar dashboards disponíveis para debug |

---

## Pré-requisitos

- **PRE-01:** `make up PROFILE=full` — Metabase rodando em `localhost:3030`
- **PRE-02:** `gold_cvm.fundo_mensal` populada com 312.772 registros (✅ validado)
- **PRE-03:** `gold_bcb.macro_mensal` populada com 315 registros (✅ validado — GOLD_BCB)
- **PRE-04:** `.env` com `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD` (já existe do BCB)
- **PRE-05:** Conexão `FinLake Brasil` já configurada no Metabase (✅ do METABASE_BCB)

---

## Requisitos Rascunho para `/define`

### Funcionais

- **RF-01:** Dashboard `CVM — Visão Geral` com 4 cards de `fundo_mensal` (PL, captação, cotistas, contagem).
- **RF-02:** Dashboard `CVM — Rentabilidade` com 5 cards (top 10 fundos, alpha SELIC/IPCA por tipo, histograma, top gestores).
- **RF-03:** Dashboard `CVM — Fundos vs Macro` com 4 cards cross-domain (linha dupla mercado vs SELIC, alpha por categoria, % que bateu SELIC, IPCA overlay).
- **RF-04:** Filtros globais em todos os dashboards: `meses_com_dados >= 6`, `tp_fundo`, `ano_mes` range.
- **RF-05:** Cards de rentabilidade com `rentabilidade_mes_pct BETWEEN -100 AND 500` — documentado no SETUP_CVM.md como decisão de visualização.
- **RF-06:** Script `scripts/export_metabase_cvm.sh` autenticando via API e exportando 3 JSONs para `docs/metabase/`.
- **RF-07:** `make metabase-export-cvm` executando o script com vars do `.env`.
- **RF-08:** `make metabase-export-all` executando BCB + CVM em sequência.
- **RF-09:** `docs/metabase/SETUP_CVM.md` com valores de conexão, filtros, SQL de exemplo para cards com JOIN.

### Não-Funcionais

- **RNF-01:** 3 JSONs exportados são válidos — `python3 -m json.tool` sem erro.
- **RNF-02:** Script idempotente — re-executar sobrescreve os JSONs sem criar duplicatas.
- **RNF-03:** Nenhuma credencial hardcoded no script — tudo via variáveis de ambiente.
- **RNF-04:** Script BCB existente (`export_metabase.sh`) não é alterado — zero regressão.
- **RNF-05:** Cards do Dashboard 3 com JOIN retornam em < 5s (fundo_mensal: 312K rows; macro_mensal: 315 rows).

---

## Validações Realizadas

| Seção | Apresentada | Feedback | Ajustada? |
|-------|-------------|----------|-----------|
| Estrutura de 3 dashboards + cards | ✅ Checkpoint 1 | Adicionar card de top gestores por alpha_selic no Dashboard 2 | Sim — Dashboard 2 passou de 4 para 5 cards |
| Artefatos finais + YAGNI | ✅ Checkpoint 2 | Aprovado sem alterações | Não |

---

## Próximos Passos

```
/define .claude/sdd/features/BRAINSTORM_METABASE_CVM.md
```

---

## Session Summary

| Métrica | Valor |
|---------|-------|
| Perguntas de descoberta | 5 (estrutura, outliers, cross-domain, export, refinamento gestor) |
| Abordagens exploradas | 3 (A selecionada, B e C rejeitadas) |
| Features removidas (YAGNI) | 8 |
| Validações realizadas | 2 |
| Dashboards definidos | 3 |
| Cards totais | 13 |

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-30 | brainstorm-agent | Versão inicial |

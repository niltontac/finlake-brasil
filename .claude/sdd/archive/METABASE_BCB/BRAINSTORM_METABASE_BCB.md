# BRAINSTORM: METABASE_BCB

> Phase 0 — Exploração e decisões arquiteturais
> Data: 2026-04-25
> Autor: Nilton Coura

---

## Metadata

| Atributo         | Valor                                            |
|------------------|--------------------------------------------------|
| **Feature**      | METABASE_BCB                                     |
| **Domínio**      | domain_macro (BCB)                               |
| **Fase**         | Visualização — fechando o ciclo Medallion        |
| **Upstream**     | GOLD_BCB (shipped 2026-04-24)                    |
| **Próxima fase** | `/define BRAINSTORM_METABASE_BCB.md`             |

---

## Objetivo

Fechar o ciclo completo Bronze → Silver → Gold → Visualização do domínio BCB.
Metabase já está declarado no `compose.metabase.yml` (profile `full`, porta 3030).
A feature entrega: setup inicial via wizard UI, conexão ao `gold_bcb` configurada,
1 dashboard com os KPIs macroeconômicos mais visíveis, e um script de export que
versiona o dashboard como JSON em `docs/metabase/` — artefato de reprodutibilidade
para recrutadores que clonarem o repositório.

---

## Contexto do Projeto

Gold BCB operacional (shipped 2026-04-24, ATs validados no container):

| Tabela | Rows | Grain | Métricas |
|--------|------|-------|---------|
| `gold_bcb.macro_mensal` | 315 | Mensal (2000-01 → 2026-03) | `selic_real`, `taxa_anual`, `acumulado_12m`, `ptax_media`, `ptax_variacao_mensal_pct` |
| `gold_bcb.macro_diario` | 6.592 | Diário (dias úteis SELIC) | `selic_real`, `taxa_anual`, `taxa_cambio`, `variacao_diaria_pct`, `acumulado_12m` |

**Grounding — selic_real validada:** `10.6549%` em março/2026 (AT-003 ✅).

**Infraestrutura Metabase:**
```yaml
# docker/compose.metabase.yml
image: metabase/metabase:latest
profiles: ["full"]
container_name: finlake-metabase
environment:
  MB_DB_TYPE: h2          # metadados Metabase em H2 embarcado (sem PostgreSQL externo)
  JAVA_TIMEZONE: America/Sao_Paulo
ports:
  - "${METABASE_PORT:-3030}:3000"
networks:
  - finlake-net            # mesma rede do PostgreSQL
depends_on:
  postgres:
    condition: service_healthy
```

**Estado atual:** Fresh install — wizard de primeiro acesso em `localhost:3030/setup`.

---

## Decisões Exploradas

### Q1 — Estado do Metabase

**Decisão: Fresh install** — wizard de primeiro acesso não executado.
Nenhuma configuração prévia existe no H2 embarcado.

---

### Q2 — Nível de automação

**Decisão: Semi-automatizado**

| Etapa | Método | Justificativa |
|-------|--------|---------------|
| Setup inicial (admin, org) | Manual — wizard UI | One-time, 5 campos, sem valor em automatizar |
| Conexão ao PostgreSQL | Manual — admin panel | One-time, valores do `.env` |
| Criação do dashboard | Manual — UI Metabase | Drag-and-drop é mais rápido que API |
| Export do dashboard | Script `export_metabase.sh` | Reprodutibilidade — JSON versionado no repo |
| Makefile target | `make metabase-export` | Integra ao workflow do projeto |

**Alternativa rejeitada:** Automação completa via API (`POST /api/database`, `POST /api/card`,
`POST /api/dashboard`) — 200+ linhas de Python/shell para criar algo que a UI faz em 10 minutos.
Sem valor adicional para o portfólio além da reprodutibilidade que o JSON já garante.

**Alternativa rejeitada:** Export manual via browser (botão "Export" da UI) — sem Makefile target,
sem script documentado, sem reprodutibilidade garantida para quem clonar o repo.

---

### Q3 — Escopo do dashboard

**Decisão: 1 dashboard com KPIs de `macro_mensal`**

| Chart | Tipo | Métrica | Grain |
|-------|------|---------|-------|
| SELIC real histórica | Linha | `selic_real` (%) | Mensal |
| SELIC vs Inflação | Dual series (linha) | `taxa_anual` + `acumulado_12m` (%) | Mensal |
| PTAX médio mensal | Linha | `ptax_media` (R$/USD) | Mensal |

Fonte única: `gold_bcb.macro_mensal` (315 registros) — grain mensal é suficiente para
análise histórica. `macro_diario` fica disponível para exploração ad-hoc no Metabase
(Query Builder), não entra no dashboard MVP.

**Alternativa rejeitada:** Dashboard duplo (mensal + diário) — complexidade sem ganho
analítico adicional para o portfólio. Layout e refinamento são decisões de produto.

---

## Conexão PostgreSQL → Metabase

**Valores corretos para o admin panel:**

| Campo | Valor | Observação |
|-------|-------|------------|
| Display name | FinLake Brasil | Nome livre |
| Host | `postgres` | Rede Docker interna — NÃO `localhost` |
| Port | `5432` | Porta interna — NÃO `5433` |
| Database name | `finlake` | Valor de `POSTGRES_DB` no `.env` |
| Username | `postgres` | Valor de `POSTGRES_USER` no `.env` |
| Password | `supabase123` | Valor de `POSTGRES_PASSWORD` no `.env` |
| Default schema | `gold_bcb` | Metabase lista `macro_mensal` e `macro_diario` diretamente |

> **Atenção:** `host=localhost` é o erro mais comum — não funciona dentro da rede Docker.
> O container Metabase acessa o PostgreSQL pelo nome do serviço (`postgres`), não pelo host.

---

## Script de Export

```bash
# scripts/export_metabase.sh
# Autentica no Metabase, lista dashboards, exporta o primeiro para docs/metabase/

METABASE_URL="http://localhost:3030"
EMAIL="${METABASE_ADMIN_EMAIL}"
PASSWORD="${METABASE_ADMIN_PASSWORD}"

# 1. Autenticar — obter session token
TOKEN=$(curl -s -X POST "$METABASE_URL/api/session" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Listar dashboards — pegar ID do primeiro
DASHBOARD_ID=$(curl -s "$METABASE_URL/api/dashboard" \
  -H "X-Metabase-Session: $TOKEN" \
  | python3 -c "import sys,json; ds=json.load(sys.stdin); print(ds[0]['id'])")

# 3. Exportar dashboard como JSON
mkdir -p docs/metabase
curl -s "$METABASE_URL/api/dashboard/$DASHBOARD_ID" \
  -H "X-Metabase-Session: $TOKEN" \
  | python3 -m json.tool > docs/metabase/dashboard_bcb_macro.json

echo "Dashboard exportado: docs/metabase/dashboard_bcb_macro.json"
```

**Variáveis novas no `.env`:**
```dotenv
METABASE_ADMIN_EMAIL=admin@finlake.local
METABASE_ADMIN_PASSWORD=<senha_escolhida_no_wizard>
```

**Makefile target:**
```makefile
metabase-export: ## Exporta dashboard Metabase para docs/metabase/ (requer 'make up PROFILE=full')
	@bash scripts/export_metabase.sh
```

---

## Estrutura de Arquivos

```
scripts/
└── export_metabase.sh          ← NOVO: script de export via API

docs/
└── metabase/
    ├── SETUP.md                ← NOVO: guia de conexão (host, port, schema)
    └── dashboard_bcb_macro.json ← NOVO: JSON exportado (gerado manualmente após setup)

Makefile                        ← MODIFICADO: target metabase-export
.env.example                    ← MODIFICADO: METABASE_ADMIN_EMAIL + METABASE_ADMIN_PASSWORD
```

---

## YAGNI — Features Removidas

| Feature | Decisão | Motivo |
|---------|---------|--------|
| Script de import/restore | Removido | Export já garante reprodutibilidade; import via UI é trivial |
| Automação completa via API | Removido | 200+ linhas para substituir 10 min de UI — desproporcional |
| Dashboard `macro_diario` | Deferido | MVP é `macro_mensal`; diário fica para exploração ad-hoc |
| Collections e permissões | Removido | Ambiente local single-user — sem necessidade |
| Relatórios agendados (email) | Removido | Fora do escopo de portfólio local |
| PTAX variação MoM no dashboard | Removido | `ptax_variacao_mensal_pct` entra depois; 3 charts é suficiente para MVP |

---

## Assumptions

| ID | Assumption | Impacto se errada |
|----|------------|-------------------|
| A-001 | `host=postgres` resolve dentro da rede Docker `finlake-net` | Conexão falha — usar IP do container como fallback |
| A-002 | H2 embarcado do Metabase persiste entre restarts do container (`unless-stopped`) | Wizard e conexão precisam ser refeitos após `make down` |
| A-003 | `GET /api/dashboard/:id` retorna JSON completo com cards e layout para import | JSON incompleto — verificar com Metabase 0.50+ que tem export nativo |
| A-004 | `default schema = gold_bcb` no admin panel faz Metabase listar `macro_mensal` sem browse manual | Pode precisar de sync manual — verificar em "Browse data" após salvar conexão |

---

## Pré-requisitos

- **PRE-01:** `make up PROFILE=full` — Metabase rodando em `localhost:3030`
- **PRE-02:** `gold_bcb.macro_mensal` populada com 315 registros (✅ validado)
- **PRE-03:** Admin email e senha definidos no wizard (geram `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD` para o `.env`)

---

## Requisitos Rascunho para `/define`

### Funcionais

- **RF-01:** Wizard completado: admin email, senha, org name, timezone (`America/Sao_Paulo`).
- **RF-02:** Conexão `FinLake Brasil` configurada: `postgres:5432`, database `finlake`, schema `gold_bcb`.
- **RF-03:** 1 dashboard `BCB Macro` com 3 charts de `macro_mensal`: SELIC real (linha), taxa_anual vs acumulado_12m (dual), ptax_media (linha).
- **RF-04:** Script `scripts/export_metabase.sh` autenticando via API e exportando para `docs/metabase/dashboard_bcb_macro.json`.
- **RF-05:** `make metabase-export` executando o script com vars do `.env`.
- **RF-06:** `docs/metabase/SETUP.md` com os valores de conexão e instrução de reprodução.
- **RF-07:** `.env.example` atualizado com `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD`.

### Não-Funcionais

- **RNF-01:** JSON exportado é válido — `python3 -m json.tool` não retorna erro.
- **RNF-02:** Script idempotente — re-executar sobrescreve o JSON sem criar duplicatas.
- **RNF-03:** Nenhuma credencial hardcoded no script — tudo via variáveis de ambiente.

---

## Próximos Passos

```
/define .claude/sdd/features/BRAINSTORM_METABASE_BCB.md
```

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-25 | brainstorm-agent | Versão inicial |

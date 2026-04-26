# DESIGN: Metabase BCB — Visualização Macroeconômica

> Especificação técnica para fechar o ciclo Bronze → Silver → Gold → Visualização:
> volume H2 para persistência, script de export via API, guia de conexão e
> Makefile target. Dashboard criado manualmente via UI, JSON versionado no repo.

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | METABASE_BCB                                     |
| **Data**          | 2026-04-26                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | ✅ Shipped                                       |
| **Origem**        | DEFINE_METABASE_BCB.md (2026-04-26)             |
| **Upstream**      | GOLD_BCB (shipped 2026-04-24)                    |

---

## Arquitetura

### Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│  Host: localhost                                                     │
│                                                                     │
│  Browser ──:3030──▶ finlake-metabase (container)                   │
│                            │                                        │
│                            │ finlake-net (Docker bridge)            │
│                            ▼                                        │
│                     finlake-postgres:5432                           │
│                            │                                        │
│                            ├── schema: gold_bcb                     │
│                            │     ├── macro_mensal (315 rows)        │
│                            │     └── macro_diario (6592 rows)       │
│                            └── schema: silver_bcb, bronze_bcb       │
│                                                                     │
│  finlake-metabase                                                   │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │  Metabase (metabase/metabase:latest)                     │      │
│  │  MB_DB_TYPE: h2                                           │      │
│  │  H2 data: /metabase-data/ ──▶ volume: metabase-data      │      │
│  │                                                          │      │
│  │  Conexão: "FinLake Brasil"                               │      │
│  │    host=postgres, port=5432, db=finlake                  │      │
│  │    schema=gold_bcb                                       │      │
│  │                                                          │      │
│  │  Dashboard: "BCB Macro"                                  │      │
│  │    Chart 1: SELIC real histórica (linha)                 │      │
│  │    Chart 2: SELIC vs Inflação (dual line)                │      │
│  │    Chart 3: PTAX médio mensal (linha)                    │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                     │
│  scripts/export_metabase.sh                                         │
│    POST /api/session ──▶ token                                      │
│    GET  /api/dashboard ──▶ id de "BCB Macro"                        │
│    GET  /api/dashboard/:id ──▶ JSON                                 │
│    python3 -m json.tool ──▶ docs/metabase/dashboard_bcb_macro.json  │
└─────────────────────────────────────────────────────────────────────┘
```

### Fluxo de Setup (Build Order)

```
1. Modify compose.metabase.yml + docker-compose.yml → volume H2
2. Criar scripts/export_metabase.sh
3. Criar docs/metabase/SETUP.md
4. Modify Makefile → metabase-export target
5. Modify .env.example → METABASE_ADMIN_EMAIL + PASSWORD

--- MANUAL (não executável pelo build agent) ---
6. make down && make up PROFILE=full  (aplica novo volume)
7. Wizard UI: localhost:3030/setup
8. Admin panel: add database "FinLake Brasil"
9. UI: criar dashboard "BCB Macro" com 3 charts
10. Adicionar ao .env: METABASE_ADMIN_EMAIL + METABASE_ADMIN_PASSWORD
11. make metabase-export → docs/metabase/dashboard_bcb_macro.json
```

---

## Decisões Arquiteturais (ADRs)

### ADR-1: Volume H2 declarado no `docker-compose.yml` raiz

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-26 |

**Contexto:** `docker-compose.yml` usa `include:` para montar os compose parciais e
declara volumes globais na seção `volumes:`. O volume `postgres-data` já está lá.

**Decisão:** `metabase-data:` vai no `docker-compose.yml` raiz (seção `volumes:`).
`docker/compose.metabase.yml` recebe apenas o mount `metabase-data:/metabase-data`.

**Rationale:** Volumes nomeados com `driver: local` devem ser declarados no escopo
global do compose que os gerencia. Se declarado apenas no `compose.metabase.yml`
(arquivo `include`d), o volume fica sem driver explícito e pode causar conflitos.

**Alternativa rejeitada:** Declarar volume em `compose.metabase.yml` diretamente —
o padrão do projeto centraliza volumes globais no arquivo raiz.

---

### ADR-2: H2 embarcado para metadados Metabase (vs PostgreSQL externo)

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-26 |

**Contexto:** Metabase pode usar H2 (embarcado) ou PostgreSQL externo para seus
próprios metadados (dashboards, conexões, usuários).

**Decisão:** H2 com volume nomeado (`metabase-data`).

**Rationale:** PostgreSQL externo adiciona database separado ou schema dedicado,
complicando `init.sql` e migrations. H2 com volume nomeado é suficiente para
ambiente local: persiste entre `down/up`, só é perdido com `down -v` (reset
explícito). Para portfólio, o JSON exportado é o artefato primário — não o H2.

**Alternativa rejeitada:** PostgreSQL externo (`MB_DB_TYPE: postgres`) — overhead
de configuração sem benefício para ambiente local.

---

### ADR-3: Shell script (`curl` + `python3`) vs Python `requests` para export

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-26 |

**Contexto:** O script de export precisa autenticar na API Metabase e salvar JSON.

**Decisão:** Bash com `curl` para chamadas HTTP e `python3` stdlib para parse JSON.
Zero dependências além do que já existe no projeto.

**Rationale:**
- `curl` é universal em macOS/Linux — sem `pip install`
- `python3 -m json.tool` para pretty-print é stdlib pura
- `python3 -c "..."` para parse inline é suficiente para 3 campos
- Script de ~50 linhas com `set -euo pipefail` é mais transparente que módulo Python

**Alternativa rejeitada:** Python com `requests` — dependência adicional, overhead
de módulo para o que é essencialmente um one-shot script de 3 chamadas curl.

---

### ADR-4: Busca de dashboard por nome vs por ID fixo

| Atributo | Valor |
|----------|-------|
| **Status** | Accepted |
| **Data** | 2026-04-26 |

**Contexto:** O script de export precisa encontrar o dashboard "BCB Macro" para
exportar. Pode usar o ID numérico fixo (ex: `1`) ou buscar pelo nome.

**Decisão:** Busca pelo nome `BCB Macro` via `GET /api/dashboard` + filter.

**Rationale:**
- ID `1` assume que "BCB Macro" é o primeiro dashboard criado — frágil se o wizard
  criar dashboards de exemplo antes
- Nome é estável e auto-documentado: `DASHBOARD_NAME="BCB Macro"` no script
- Erro informativo quando não encontrado: lista dashboards disponíveis

**Alternativa rejeitada:** ID fixo `1` — frágil e não documenta intenção.

---

## File Manifest

| # | Arquivo | Ação | Propósito | Dependências |
|---|---------|------|-----------|--------------|
| 1 | `docker/compose.metabase.yml` | Modify | Volume mount `metabase-data:/metabase-data` | None |
| 2 | `docker-compose.yml` | Modify | Declarar `metabase-data:` em `volumes:` globais | 1 |
| 3 | `scripts/export_metabase.sh` | Create | Export dashboard JSON via API Metabase | None |
| 4 | `docs/metabase/SETUP.md` | Create | Guia de conexão e reprodução do dashboard | None |
| 5 | `Makefile` | Modify | Target `metabase-export` chamando o script | 3 |
| 6 | `.env.example` | Modify | `METABASE_ADMIN_EMAIL` + `METABASE_ADMIN_PASSWORD` | None |
| 7 | `docs/metabase/dashboard_bcb_macro.json` | **Gerado pós-build** | JSON do dashboard exportado — artefato de portfólio | Manual: requer Metabase configurado |

> **Item 7** não é criado pelo build agent — é gerado por `make metabase-export`
> após o setup manual. O build agent verifica que o script funciona; o JSON é
> commitado pelo usuário após execução manual.

**Ordem de execução no Build:** 1 → 2 → 3 → 4 → 5 → 6 (todos em paralelo exceto 2 que depende de 1)

---

## Code Patterns

### 1. `docker/compose.metabase.yml` (modificação)

```yaml
services:
  metabase:
    image: metabase/metabase:latest
    profiles: ["full"]
    container_name: finlake-metabase
    restart: unless-stopped
    environment:
      MB_DB_TYPE: h2
      JAVA_TIMEZONE: America/Sao_Paulo
    ports:
      - "${METABASE_PORT:-3030}:3000"
    volumes:
      - metabase-data:/metabase-data
    networks:
      - finlake-net
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s
```

---

### 2. `docker-compose.yml` (modificação)

Adicionar `metabase-data:` ao bloco `volumes:` existente:

```yaml
# Antes:
volumes:
  postgres-data:
    driver: local

# Depois:
volumes:
  postgres-data:
    driver: local
  metabase-data:
    driver: local
```

---

### 3. `scripts/export_metabase.sh`

```bash
#!/usr/bin/env bash
# Exporta dashboard Metabase "BCB Macro" para docs/metabase/dashboard_bcb_macro.json
# Uso: make metabase-export (ou bash scripts/export_metabase.sh)
# Requer: METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env

set -euo pipefail

METABASE_URL="${METABASE_URL:-http://localhost:3030}"
EMAIL="${METABASE_ADMIN_EMAIL:?Defina METABASE_ADMIN_EMAIL no .env}"
PASSWORD="${METABASE_ADMIN_PASSWORD:?Defina METABASE_ADMIN_PASSWORD no .env}"
DASHBOARD_NAME="BCB Macro"
OUTPUT_DIR="docs/metabase"
OUTPUT_FILE="${OUTPUT_DIR}/dashboard_bcb_macro.json"

mkdir -p "${OUTPUT_DIR}"

echo "→ Autenticando em ${METABASE_URL}..."
TOKEN=$(curl -sf -X POST "${METABASE_URL}/api/session" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

echo "→ Buscando dashboard '${DASHBOARD_NAME}'..."
DASHBOARD_ID=$(curl -sf "${METABASE_URL}/api/dashboard" \
  -H "X-Metabase-Session: ${TOKEN}" \
  | python3 -c "
import sys, json
dashboards = json.load(sys.stdin)
match = next((d for d in dashboards if d['name'] == '${DASHBOARD_NAME}'), None)
if not match:
    names = [d['name'] for d in dashboards]
    raise SystemExit(f'Dashboard \"${DASHBOARD_NAME}\" não encontrado. Disponíveis: {names}')
print(match['id'])
")

echo "→ Exportando dashboard ID=${DASHBOARD_ID}..."
curl -sf "${METABASE_URL}/api/dashboard/${DASHBOARD_ID}" \
  -H "X-Metabase-Session: ${TOKEN}" \
  | python3 -m json.tool > "${OUTPUT_FILE}"

echo "✓ Dashboard exportado: ${OUTPUT_FILE}"
echo "  Commit com: git add ${OUTPUT_FILE} && git commit -m 'docs: export Metabase BCB Macro dashboard'"
```

---

### 4. `docs/metabase/SETUP.md`

```markdown
# Metabase BCB — Setup Guide

## Pré-requisitos

- `make up PROFILE=full` rodando
- `gold_bcb.macro_mensal` populada (`make migrate` + `dbt run`)

## Conexão ao PostgreSQL

No admin panel → **Add a database**:

| Campo         | Valor          | Atenção                          |
|---------------|----------------|----------------------------------|
| Database type | PostgreSQL     |                                  |
| Display name  | FinLake Brasil |                                  |
| Host          | `postgres`     | ⚠️ Nunca `localhost` — rede Docker |
| Port          | `5432`         | ⚠️ Nunca `5433` — porta interna   |
| Database name | `finlake`      | Valor de `POSTGRES_DB` no `.env` |
| Username      | `postgres`     | Valor de `POSTGRES_USER`         |
| Password      | (ver `.env`)   | Valor de `POSTGRES_PASSWORD`     |
| Default schema| `gold_bcb`     | Lista macro_mensal diretamente   |

## Dashboard "BCB Macro"

3 charts de `gold_bcb.macro_mensal`:

| Chart               | Tipo         | Eixo X | Eixo Y                            |
|---------------------|--------------|--------|-----------------------------------|
| SELIC real histórica| Line         | `date` | `selic_real` (%)                  |
| SELIC vs Inflação   | Line (dual)  | `date` | `taxa_anual` + `acumulado_12m` (%) |
| PTAX médio mensal   | Line         | `date` | `ptax_media` (R$/USD)             |

## Export do Dashboard

Após criar o dashboard:

```bash
# Adicionar ao .env:
METABASE_ADMIN_EMAIL=admin@finlake.local
METABASE_ADMIN_PASSWORD=<senha_do_wizard>

# Exportar:
make metabase-export
git add docs/metabase/dashboard_bcb_macro.json
git commit -m "docs: export Metabase BCB Macro dashboard"
```

## Persistência

O setup (wizard, conexão, dashboards) persiste via volume Docker `metabase-data`.
Sobrevive a `make down && make up`. Só é perdido com `make reset` (remove volumes).
```

---

### 5. `Makefile` (modificação — novo target)

Adicionar após o target `test:`:

```makefile
metabase-export: ## Exporta dashboard "BCB Macro" para docs/metabase/ (requer 'make up PROFILE=full' e .env com METABASE_ADMIN_EMAIL)
	@bash scripts/export_metabase.sh
```

---

### 6. `.env.example` (modificação)

Adicionar na seção Metabase existente:

```dotenv
# ------------------------------------------------------------
# Metabase
# ------------------------------------------------------------
METABASE_PORT=3030

# Definir após completar o wizard em localhost:3030/setup
METABASE_ADMIN_EMAIL=admin@finlake.local
METABASE_ADMIN_PASSWORD=<METABASE_ADMIN_PASSWORD>
```

---

## Guia de Setup Manual (pós-build)

Após o build, executar nesta ordem:

```bash
# 1. Aplicar volume H2 (make down necessário para recriar o container com novo volume)
make down
make up PROFILE=full

# 2. Wizard: localhost:3030/setup
#    - Email: admin@finlake.local
#    - Password: <escolher>
#    - Org: FinLake Brasil
#    - Timezone: America/Sao_Paulo
#    - "Add data later"

# 3. Admin panel → Add a database
#    (usar valores de docs/metabase/SETUP.md)

# 4. New dashboard → "BCB Macro"
#    (criar 3 charts de gold_bcb.macro_mensal)

# 5. Adicionar ao .env:
#    METABASE_ADMIN_EMAIL=admin@finlake.local
#    METABASE_ADMIN_PASSWORD=<senha_escolhida>

# 6. Exportar e versionar
make metabase-export
git add docs/metabase/dashboard_bcb_macro.json
git commit -m "docs: export Metabase BCB Macro dashboard"
```

---

## Validação do Script

```bash
# Verificar sintaxe bash sem executar
bash -n scripts/export_metabase.sh

# Verificar JSON após export
python3 -m json.tool docs/metabase/dashboard_bcb_macro.json > /dev/null && echo "JSON válido"

# Verificar cards no JSON
jq '.dashcards | length' docs/metabase/dashboard_bcb_macro.json
# Esperado: 3

# Verificar nome do dashboard no JSON
jq '.name' docs/metabase/dashboard_bcb_macro.json
# Esperado: "BCB Macro"
```

---

## Estratégia de Testes

| Tipo | Escopo | Ferramenta | Quando |
|------|--------|------------|--------|
| **Sintaxe** | `export_metabase.sh` | `bash -n` | Durante build, após criar o script |
| **Lint** | YAML dos composes | `python3 -c "import yaml"` | Após modificar compose files |
| **AT-001** | Health Metabase | `curl localhost:3030/api/health` | Após `make up PROFILE=full` |
| **AT-002** | Conexão PostgreSQL | UI manual | Após wizard e add database |
| **AT-003** | Schema visível | UI manual — Browse data | Após salvar conexão |
| **AT-004** | Dashboard com dados | UI manual | Após criar charts |
| **AT-005/006/007** | Export + JSON | `make metabase-export` + `jq` | Após criar dashboard |
| **AT-008** | Persistência H2 | `make down && make up` | Após AT-007 |

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-26 | design-agent | Versão inicial from DEFINE_METABASE_BCB.md |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_METABASE_BCB.md`

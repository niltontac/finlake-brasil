# DESIGN: METABASE_CVM — Dashboards de Fundos de Investimento

> Especificação técnica completa para 3 dashboards Metabase criados via automação Python API, script de export e targets Makefile.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | METABASE_CVM |
| **Data** | 2026-05-01 |
| **Autor** | design-agent |
| **DEFINE** | [DEFINE_METABASE_CVM.md](./DEFINE_METABASE_CVM.md) |
| **Status** | ✅ Shipped |

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
  scripts/setup_metabase_cvm.py  ──────────────────────────────────────────┐
    POST /api/card (×13) + POST /api/dashboard (×3) + PUT cards           │
                                                                           ▼
  Metabase (localhost:3030)  ◄──────── conexão: db_finlake_brasil ──────────┘
    ├── Dashboard: CVM — Visão Geral      (4 SQL Questions)
    ├── Dashboard: CVM — Rentabilidade    (5 SQL Questions)
    └── Dashboard: CVM — Fundos vs Macro  (4 SQL Questions)
                │
                ▼
  scripts/export_metabase_cvm.sh  →  docs/metabase/dashboard_cvm_*.json
                │
                ▼
  Makefile: metabase-setup-cvm / metabase-export-cvm / metabase-export-all
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

### ADR-004 — Automação de criação dos dashboards via script Python

| Atributo | Valor |
|----------|-------|
| **Status** | Aceito |
| **Data** | 2026-05-01 |

**Contexto:** A criação manual de 13 cards em 3 dashboards via UI do Metabase é sequencial, propensa a erro e não reproduzível por quem clonar o repo.

**Escolha:** `scripts/setup_metabase_cvm.py` — script Python que usa a API REST do Metabase para criar todos os cards e dashboards programaticamente em uma execução.

**Rationale:** Reprodutibilidade é um requisito de portfólio. Um script que roda em segundos e produz resultados idênticos toda vez é mais valioso para demonstrar maturidade de engenharia do que instruções manuais. A API do Metabase (`POST /api/card`, `POST /api/dashboard`, `PUT /api/dashboard/{id}/cards`) suporta exatamente esse fluxo.

**Alternativa rejeitada (v1.0):** Criação manual via UI + SETUP_CVM.md como guia passo a passo — rejeitado porque não é reproduzível e viola o princípio de infrastructure-as-code.

**Consequências:** SETUP_CVM.md passa de guia de criação manual para guia de execução do script + troubleshooting. Setup reduz de ~30 min manual para ~30 segundos de execução automatizada.

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
| 1 | `scripts/export_metabase_cvm.sh` | ~~Criar~~ ✅ Criado | Script de export dos 3 dashboards CVM | Nenhuma |
| 2 | `scripts/setup_metabase_cvm.py` | Criar | Automação Python: cria 13 cards + 3 dashboards via API REST | Nenhuma |
| 3 | `docs/metabase/SETUP_CVM.md` | ~~Criar~~ ✅ Criado → Modificar | Atualizar: de guia manual para guia de execução do script + troubleshooting | 2 |
| 4 | `Makefile` | ~~Modificar~~ ✅ Parcial → Completar | Adicionar target `metabase-setup-cvm` (targets de export já adicionados) | 2 |

> **Artefatos gerados após `make metabase-setup-cvm` + `make metabase-export-cvm`** (produzidos pelo script):
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

### Artefato 2 — `scripts/setup_metabase_cvm.py`

```python
#!/usr/bin/env python3
"""Cria 3 dashboards CVM com 13 cards SQL no Metabase via API REST.

Uso: make metabase-setup-cvm
Requer: METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

import requests

METABASE_URL = os.getenv("METABASE_URL", "http://localhost:3030")
DB_NAME = "db_finlake_brasil"

DASHBOARD_NAMES = [
    "CVM — Visão Geral",
    "CVM — Rentabilidade",
    "CVM — Fundos vs Macro",
]


@dataclass
class CardSpec:
    """Especificação de um card SQL para o Metabase."""

    name: str
    sql: str
    display: str  # "line", "bar", "scalar", "table"
    dashboard: str
    row: int
    col: int
    size_x: int = 18
    size_y: int = 8


# ─── SQL de cada card (ver seção "SQL de todos os cards") ────────────────────

_SQL_1_1 = """SELECT
    ano_mes, tp_fundo, SUM(vl_patrim_liq_medio) AS pl_total
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
GROUP BY ano_mes, tp_fundo ORDER BY ano_mes"""

_SQL_1_2 = """SELECT
    ano_mes, SUM(captacao_liquida_acumulada) AS captacao_total
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
GROUP BY ano_mes ORDER BY ano_mes"""

_SQL_1_3 = """SELECT
    ano_mes, tp_fundo, ROUND(AVG(nr_cotst_medio)::numeric, 0) AS cotistas_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
GROUP BY ano_mes, tp_fundo ORDER BY ano_mes"""

_SQL_1_4 = """SELECT COUNT(DISTINCT cnpj_fundo) AS fundos_com_dados
FROM gold_cvm.fundo_mensal WHERE meses_com_dados >= 6"""

_SQL_2_1 = """SELECT cnpj_fundo, COALESCE(gestor, 'Não informado') AS gestor,
    ano_mes, ROUND(rentabilidade_mes_pct::numeric, 4) AS rentabilidade_mes_pct
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND rentabilidade_mes_pct BETWEEN -100 AND 500
ORDER BY rentabilidade_mes_pct DESC LIMIT 10"""

_SQL_2_2 = """SELECT tp_fundo, ROUND(AVG(alpha_selic)::numeric, 4) AS alpha_selic_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL
GROUP BY tp_fundo ORDER BY alpha_selic_medio DESC"""

_SQL_2_3 = """SELECT tp_fundo, ROUND(AVG(alpha_ipca)::numeric, 4) AS alpha_ipca_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND alpha_ipca IS NOT NULL
GROUP BY tp_fundo ORDER BY alpha_ipca_medio DESC"""

_SQL_2_4 = """SELECT rentabilidade_mes_pct FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND rentabilidade_mes_pct BETWEEN -100 AND 500"""

_SQL_2_5 = """SELECT COALESCE(gestor, 'Não informado') AS gestor,
    COUNT(DISTINCT cnpj_fundo) AS qtd_fundos,
    ROUND(AVG(alpha_selic)::numeric, 4) AS alpha_selic_medio,
    ROUND(AVG(vl_patrim_liq_medio)::numeric, 0) AS pl_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL AND gestor IS NOT NULL
GROUP BY gestor HAVING COUNT(DISTINCT cnpj_fundo) >= 2
ORDER BY alpha_selic_medio DESC LIMIT 10"""

_SQL_3_1 = """SELECT ano_mes,
    ROUND(AVG(rentabilidade_mes_pct)::numeric, 4) AS rent_media_mercado,
    ROUND(MAX(taxa_anual_bcb / 12)::numeric, 4)   AS selic_mensal
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500 AND taxa_anual_bcb IS NOT NULL
GROUP BY ano_mes ORDER BY ano_mes"""

_SQL_3_2 = """SELECT tp_fundo, ROUND(AVG(alpha_selic)::numeric, 4) AS alpha_selic_medio
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL
GROUP BY tp_fundo ORDER BY alpha_selic_medio DESC"""

_SQL_3_3 = """SELECT ano_mes,
    ROUND(
        100.0 * SUM(CASE WHEN alpha_selic > 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0)
    ::numeric, 1) AS pct_bateu_selic
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL
GROUP BY ano_mes ORDER BY ano_mes"""

_SQL_3_4 = """SELECT ano_mes,
    ROUND(AVG(rentabilidade_mes_pct)::numeric, 4)   AS rent_media_mercado,
    ROUND(MAX(acumulado_12m_ipca / 12)::numeric, 4) AS ipca_mensal
FROM gold_cvm.fundo_mensal
WHERE meses_com_dados >= 6
  AND rentabilidade_mes_pct BETWEEN -100 AND 500 AND acumulado_12m_ipca IS NOT NULL
GROUP BY ano_mes ORDER BY ano_mes"""


CARDS: list[CardSpec] = [
    # ── Dashboard 1: CVM — Visão Geral (4 cards) ─────────────────────────────
    CardSpec("Fundos com dados suficientes",   _SQL_1_4, "scalar", "CVM — Visão Geral",    row=0,  col=0, size_x=6, size_y=4),
    CardSpec("PL total por tipo de fundo",     _SQL_1_1, "bar",    "CVM — Visão Geral",    row=4,  col=0),
    CardSpec("Captação líquida total por mês", _SQL_1_2, "line",   "CVM — Visão Geral",    row=12, col=0),
    CardSpec("Nº médio de cotistas por tipo",  _SQL_1_3, "line",   "CVM — Visão Geral",    row=20, col=0),
    # ── Dashboard 2: CVM — Rentabilidade (5 cards) ───────────────────────────
    CardSpec("Top 10 fundos por rentabilidade",       _SQL_2_1, "table", "CVM — Rentabilidade", row=0,  col=0),
    CardSpec("Alpha SELIC médio por tipo de fundo",   _SQL_2_2, "bar",   "CVM — Rentabilidade", row=8,  col=0, size_x=9),
    CardSpec("Alpha IPCA médio por tipo de fundo",    _SQL_2_3, "bar",   "CVM — Rentabilidade", row=8,  col=9, size_x=9),
    CardSpec("Distribuição de rentabilidade mensal",  _SQL_2_4, "bar",   "CVM — Rentabilidade", row=16, col=0),
    CardSpec("Top 10 gestores por Alpha SELIC",       _SQL_2_5, "table", "CVM — Rentabilidade", row=24, col=0),
    # ── Dashboard 3: CVM — Fundos vs Macro (4 cards) ─────────────────────────
    CardSpec("Rentabilidade média vs SELIC mensal",      _SQL_3_1, "line", "CVM — Fundos vs Macro", row=0,  col=0),
    CardSpec("Alpha SELIC médio por categoria",          _SQL_3_2, "bar",  "CVM — Fundos vs Macro", row=8,  col=0),
    CardSpec("% fundos que bateram a SELIC no mês",      _SQL_3_3, "line", "CVM — Fundos vs Macro", row=16, col=0),
    CardSpec("IPCA 12m vs rentabilidade média",          _SQL_3_4, "line", "CVM — Fundos vs Macro", row=24, col=0),
]


# ─── Metabase API client ──────────────────────────────────────────────────────

class MetabaseClient:
    """Client HTTP para a API REST do Metabase."""

    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "X-Metabase-Session": token,
        })

    def get(self, path: str) -> Any:
        """GET request retornando JSON."""
        resp = self._session.get(f"{self._base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        """POST request retornando JSON."""
        resp = self._session.post(f"{self._base_url}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    def put(self, path: str, body: dict[str, Any]) -> Any:
        """PUT request retornando JSON."""
        resp = self._session.put(f"{self._base_url}{path}", json=body)
        resp.raise_for_status()
        return resp.json()


# ─── Operações de domínio ─────────────────────────────────────────────────────

def authenticate(base_url: str, email: str, password: str) -> str:
    """Autentica no Metabase e retorna o session token."""
    resp = requests.post(
        f"{base_url}/api/session",
        json={"username": email, "password": password},
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def find_database_id(client: MetabaseClient, name: str) -> int:
    """Retorna o ID da conexão pelo nome exato."""
    databases = client.get("/api/database")
    data = databases.get("data", databases)  # v0.41+ embute em {"data": [...]}
    match = next((db for db in data if db["name"] == name), None)
    if match is None:
        available = [db["name"] for db in data]
        raise SystemExit(f"Conexão '{name}' não encontrada. Disponíveis: {available}")
    return match["id"]


def create_card(client: MetabaseClient, spec: CardSpec, db_id: int) -> int:
    """Cria um SQL Question (card) e retorna seu ID."""
    result = client.post("/api/card", {
        "name": spec.name,
        "display": spec.display,
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {"query": spec.sql},
        },
        "visualization_settings": {},
    })
    return result["id"]


def create_dashboard(client: MetabaseClient, name: str) -> int:
    """Cria um dashboard e retorna seu ID."""
    result = client.post("/api/dashboard", {"name": name})
    return result["id"]


def add_cards_to_dashboard(
    client: MetabaseClient,
    dashboard_id: int,
    card_entries: list[dict[str, Any]],
) -> None:
    """Adiciona cards ao dashboard via PUT /api/dashboard/{id}/cards."""
    client.put(f"/api/dashboard/{dashboard_id}/cards", {"cards": card_entries})


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Cria 3 dashboards CVM com 13 cards via API do Metabase."""
    email = os.environ.get("METABASE_ADMIN_EMAIL")
    password = os.environ.get("METABASE_ADMIN_PASSWORD")
    if not email or not password:
        print("Erro: defina METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env", file=sys.stderr)
        sys.exit(1)

    print(f"→ Autenticando em {METABASE_URL}...")
    token = authenticate(METABASE_URL, email, password)
    client = MetabaseClient(METABASE_URL, token)

    print(f"→ Buscando conexão '{DB_NAME}'...")
    db_id = find_database_id(client, DB_NAME)
    print(f"  Conexão encontrada: ID={db_id}")

    print("→ Criando 13 cards SQL...")
    card_id_map: dict[str, int] = {}
    for spec in CARDS:
        card_id = create_card(client, spec, db_id)
        card_id_map[spec.name] = card_id
        print(f"  ✓ [{spec.dashboard}] {spec.name} (ID={card_id})")

    print("→ Criando 3 dashboards...")
    dashboard_id_map: dict[str, int] = {}
    for name in DASHBOARD_NAMES:
        dashboard_id = create_dashboard(client, name)
        dashboard_id_map[name] = dashboard_id
        print(f"  ✓ {name} (ID={dashboard_id})")

    print("→ Adicionando cards aos dashboards...")
    for dashboard_name, dashboard_id in dashboard_id_map.items():
        card_entries = [
            {
                "id": -(i + 1),
                "card_id": card_id_map[spec.name],
                "row": spec.row,
                "col": spec.col,
                "size_x": spec.size_x,
                "size_y": spec.size_y,
                "series": [],
                "visualization_settings": {},
                "parameter_mappings": [],
            }
            for i, spec in enumerate(s for s in CARDS if s.dashboard == dashboard_name)
        ]
        add_cards_to_dashboard(client, dashboard_id, card_entries)
        print(f"  ✓ {len(card_entries)} cards adicionados a '{dashboard_name}'")

    print("\n✓ Setup concluído! Dashboards disponíveis em:")
    for name, did in dashboard_id_map.items():
        print(f"  {METABASE_URL}/dashboard/{did} — {name}")
    print("\nPróximo passo: make metabase-export-cvm")


if __name__ == "__main__":
    main()
```

---

### Artefato 4 — Makefile (target adicional — `metabase-setup-cvm`)

Localizar bloco `metabase-export-cvm:` e adicionar **antes** dele:

```makefile
metabase-setup-cvm: ## Cria 3 dashboards CVM via API do Metabase (requer 'make up PROFILE=full' e .env)
	@set -a && . ./.env && set +a && python3 scripts/setup_metabase_cvm.py
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
| AT-009 | Script — Setup cria 3 dashboards e 13 cards | `make metabase-setup-cvm` → saída exibe URLs dos 3 dashboards, exit code 0 |
| AT-001 | Visual — Dashboard carrega | Abrir URL de "CVM — Visão Geral" → 4 cards visíveis |
| AT-002 | Visual — Outliers ausentes | Card 2.4 — escala deve estar entre -100% e 500% |
| AT-003 | Visual — Top gestores | Card 2.5 retorna tabela com `gestor`, `qtd_fundos`, `alpha_selic_medio` |
| AT-004 | Visual — Card estrela | Card 3.3 retorna série temporal de 12 pontos entre 0% e 100% |
| AT-005 | Visual — Linha dupla SELIC | Card 3.1 exibe duas séries sobrepostas para jan-dez 2024 |
| AT-006 | Script — Export válido | `make metabase-export-cvm` → `python3 -m json.tool docs/metabase/dashboard_cvm_*.json` sem erro |
| AT-007 | Script — Idempotência export | Re-executar `make metabase-export-cvm` → sem erro, arquivos sobrescritos |
| AT-008 | Script — Zero regressão BCB | `make metabase-export-all` → BCB JSON e CVM JSONs gerados sem erro |

**Ordem de execução sugerida:**
1. `make metabase-setup-cvm` (AT-009) — cria tudo automaticamente
2. Abrir URLs impressas pelo script e validar AT-001 a AT-005
3. `make metabase-export-cvm` (AT-006, AT-007)
4. `make metabase-export-all` (AT-008)

---

## Conteúdo de SETUP_CVM.md (atualizado — v1.1)

O guia passa de criação manual para execução de script. Deve conter:

1. **Pré-requisitos** — `make up PROFILE=full`, tabelas Gold populadas, `.env` com credenciais
2. **Execução do setup** — `make metabase-setup-cvm` e interpretação da saída (URLs dos dashboards)
3. **Verificação visual** — abrir cada URL e checar cards
4. **Export e commit** — `make metabase-export-cvm` → validar JSONs → commit
5. **Troubleshooting** — erros comuns: conexão não encontrada, `gold_cvm.` sem permissão, requests não instalado (`uv add requests`)

---

## Notas de Implementação

- **`requests` como dependência:** o script usa `requests`; verificar se está disponível (`python3 -c "import requests"`) ou instalar com `uv add requests`
- **Dependência de `requests` no pyproject.toml:** adicionar se não existir — `requests>=2.31`
- **Nomes dos dashboards:** exatos como definidos em `DASHBOARD_NAMES` — export script usa match exato
- **IDs negativos no PUT /api/dashboard/{id}/cards:** Metabase usa IDs negativos para marcar posições novas (ainda não persistidas) no payload — comportamento da API, não bug
- **Filtros de dashboard:** o script não cria filtros interativos de dashboard (tp_fundo, ano_mes) — esses precisam ser adicionados manualmente via UI após `make metabase-setup-cvm`. O filtro `BETWEEN -100 AND 500` fica embutido no SQL dos cards
- **Card 3.3 (% fundos):** `NULLIF(COUNT(*), 0)` protege contra divisão por zero em meses sem dados

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-05-01 | design-agent | Versão inicial — criação manual dos dashboards |
| 1.1 | 2026-05-01 | iterate-agent | Automação via `scripts/setup_metabase_cvm.py` (ADR-004); SETUP_CVM.md convertido de guia manual para guia de script; novo target `metabase-setup-cvm`; AT-009 adicionado |

#!/usr/bin/env python3
"""Cria 3 dashboards CVM com 13 cards SQL no Metabase via API REST.

Uso: make metabase-setup-cvm
Requer: METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
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


# ─── SQL de cada card ─────────────────────────────────────────────────────────

_SQL_1_1 = (
    "SELECT ano_mes, tp_fundo, SUM(vl_patrim_liq_medio) AS pl_total\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6\n"
    "GROUP BY ano_mes, tp_fundo ORDER BY ano_mes"
)

_SQL_1_2 = (
    "SELECT ano_mes, SUM(captacao_liquida_acumulada) AS captacao_total\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6\n"
    "GROUP BY ano_mes ORDER BY ano_mes"
)

_SQL_1_3 = (
    "SELECT ano_mes, tp_fundo,\n"
    "    ROUND(AVG(nr_cotst_medio)::numeric, 0) AS cotistas_medio\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6\n"
    "GROUP BY ano_mes, tp_fundo ORDER BY ano_mes"
)

_SQL_1_4 = (
    "SELECT COUNT(DISTINCT cnpj_fundo) AS fundos_com_dados\n"
    "FROM gold_cvm.fundo_mensal WHERE meses_com_dados >= 6"
)

_SQL_2_1 = (
    "SELECT cnpj_fundo, COALESCE(gestor, 'Não informado') AS gestor,\n"
    "    ano_mes, ROUND(rentabilidade_mes_pct::numeric, 4) AS rentabilidade_mes_pct\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND rentabilidade_mes_pct BETWEEN -100 AND 500\n"
    "ORDER BY rentabilidade_mes_pct DESC LIMIT 10"
)

_SQL_2_2 = (
    "SELECT tp_fundo, ROUND(AVG(alpha_selic)::numeric, 4) AS alpha_selic_medio\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL\n"
    "GROUP BY tp_fundo ORDER BY alpha_selic_medio DESC"
)

_SQL_2_3 = (
    "SELECT tp_fundo, ROUND(AVG(alpha_ipca)::numeric, 4) AS alpha_ipca_medio\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND alpha_ipca IS NOT NULL\n"
    "GROUP BY tp_fundo ORDER BY alpha_ipca_medio DESC"
)

_SQL_2_4 = (
    "SELECT rentabilidade_mes_pct FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND rentabilidade_mes_pct BETWEEN -100 AND 500"
)

_SQL_2_5 = (
    "SELECT COALESCE(gestor, 'Não informado') AS gestor,\n"
    "    COUNT(DISTINCT cnpj_fundo) AS qtd_fundos,\n"
    "    ROUND(AVG(alpha_selic)::numeric, 4) AS alpha_selic_medio,\n"
    "    ROUND(AVG(vl_patrim_liq_medio)::numeric, 0) AS pl_medio\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL AND gestor IS NOT NULL\n"
    "GROUP BY gestor HAVING COUNT(DISTINCT cnpj_fundo) >= 2\n"
    "ORDER BY alpha_selic_medio DESC LIMIT 10"
)

_SQL_3_1 = (
    "SELECT ano_mes,\n"
    "    ROUND(AVG(rentabilidade_mes_pct)::numeric, 4) AS rent_media_mercado,\n"
    "    ROUND(MAX(taxa_anual_bcb / 12)::numeric, 4)   AS selic_mensal\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6\n"
    "  AND rentabilidade_mes_pct BETWEEN -100 AND 500 AND taxa_anual_bcb IS NOT NULL\n"
    "GROUP BY ano_mes ORDER BY ano_mes"
)

_SQL_3_2 = (
    "SELECT tp_fundo, ROUND(AVG(alpha_selic)::numeric, 4) AS alpha_selic_medio\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL\n"
    "GROUP BY tp_fundo ORDER BY alpha_selic_medio DESC"
)

_SQL_3_3 = (
    "SELECT ano_mes,\n"
    "    ROUND(\n"
    "        100.0 * SUM(CASE WHEN alpha_selic > 0 THEN 1 ELSE 0 END)\n"
    "        / NULLIF(COUNT(*), 0)\n"
    "    ::numeric, 1) AS pct_bateu_selic\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6 AND alpha_selic IS NOT NULL\n"
    "GROUP BY ano_mes ORDER BY ano_mes"
)

_SQL_3_4 = (
    "SELECT ano_mes,\n"
    "    ROUND(AVG(rentabilidade_mes_pct)::numeric, 4)   AS rent_media_mercado,\n"
    "    ROUND(MAX(acumulado_12m_ipca / 12)::numeric, 4) AS ipca_mensal\n"
    "FROM gold_cvm.fundo_mensal\n"
    "WHERE meses_com_dados >= 6\n"
    "  AND rentabilidade_mes_pct BETWEEN -100 AND 500 AND acumulado_12m_ipca IS NOT NULL\n"
    "GROUP BY ano_mes ORDER BY ano_mes"
)


CARDS: list[CardSpec] = [
    # ── Dashboard 1: CVM — Visão Geral (4 cards) ─────────────────────────────
    CardSpec("Fundos com dados suficientes",   _SQL_1_4, "scalar", "CVM — Visão Geral",    row=0,  col=0, size_x=6, size_y=4),
    CardSpec("PL total por tipo de fundo",     _SQL_1_1, "bar",    "CVM — Visão Geral",    row=4,  col=0),
    CardSpec("Captação líquida total por mês", _SQL_1_2, "line",   "CVM — Visão Geral",    row=12, col=0),
    CardSpec("Nº médio de cotistas por tipo",  _SQL_1_3, "line",   "CVM — Visão Geral",    row=20, col=0),
    # ── Dashboard 2: CVM — Rentabilidade (5 cards) ───────────────────────────
    CardSpec("Top 10 fundos por rentabilidade",      _SQL_2_1, "table", "CVM — Rentabilidade", row=0,  col=0),
    CardSpec("Alpha SELIC médio por tipo de fundo",  _SQL_2_2, "bar",   "CVM — Rentabilidade", row=8,  col=0, size_x=9),
    CardSpec("Alpha IPCA médio por tipo de fundo",   _SQL_2_3, "bar",   "CVM — Rentabilidade", row=8,  col=9, size_x=9),
    CardSpec("Distribuição de rentabilidade mensal", _SQL_2_4, "bar",   "CVM — Rentabilidade", row=16, col=0),
    CardSpec("Top 10 gestores por Alpha SELIC",      _SQL_2_5, "table", "CVM — Rentabilidade", row=24, col=0),
    # ── Dashboard 3: CVM — Fundos vs Macro (4 cards) ─────────────────────────
    CardSpec("Rentabilidade média vs SELIC mensal",    _SQL_3_1, "line", "CVM — Fundos vs Macro", row=0,  col=0),
    CardSpec("Alpha SELIC médio por categoria",        _SQL_3_2, "bar",  "CVM — Fundos vs Macro", row=8,  col=0),
    CardSpec("% fundos que bateram a SELIC no mês",    _SQL_3_3, "line", "CVM — Fundos vs Macro", row=16, col=0),
    CardSpec("IPCA 12m vs rentabilidade média",        _SQL_3_4, "line", "CVM — Fundos vs Macro", row=24, col=0),
]


# ─── Metabase API client ──────────────────────────────────────────────────────

class MetabaseClient:
    """Client HTTP para a API REST do Metabase."""

    def __init__(self, base_url: str, token: str) -> None:
        """Inicializa com URL base e session token."""
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "X-Metabase-Session": token,
        })

    def get(self, path: str) -> Any:
        """GET request retornando JSON parseado."""
        resp = self._session.get(f"{self._base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        """POST request retornando JSON parseado."""
        resp = self._session.post(f"{self._base_url}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    def put(self, path: str, body: dict[str, Any]) -> Any:
        """PUT request retornando JSON parseado."""
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
    data: list[dict[str, Any]] = databases.get("data", databases)
    match = next((db for db in data if db["name"] == name), None)
    if match is None:
        available = [db["name"] for db in data]
        raise SystemExit(f"Conexão '{name}' não encontrada. Disponíveis: {available}")
    return int(match["id"])


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
    return int(result["id"])


def create_dashboard(client: MetabaseClient, name: str) -> int:
    """Cria um dashboard vazio e retorna seu ID."""
    result = client.post("/api/dashboard", {"name": name})
    return int(result["id"])


def add_cards_to_dashboard(
    client: MetabaseClient,
    dashboard_id: int,
    card_entries: list[dict[str, Any]],
) -> None:
    """Popula dashboard com cards via PUT /api/dashboard/{id}/cards."""
    client.put(f"/api/dashboard/{dashboard_id}/cards", {"cards": card_entries})


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Cria 3 dashboards CVM com 13 cards via API do Metabase."""
    email = os.environ.get("METABASE_ADMIN_EMAIL")
    password = os.environ.get("METABASE_ADMIN_PASSWORD")
    if not email or not password:
        print(
            "Erro: defina METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env",
            file=sys.stderr,
        )
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
        dashboard_cards = [s for s in CARDS if s.dashboard == dashboard_name]
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
            for i, spec in enumerate(dashboard_cards)
        ]
        add_cards_to_dashboard(client, dashboard_id, card_entries)
        print(f"  ✓ {len(card_entries)} cards adicionados a '{dashboard_name}'")

    print("\n✓ Setup concluído! Dashboards disponíveis em:")
    for name, did in dashboard_id_map.items():
        print(f"  {METABASE_URL}/dashboard/{did} — {name}")
    print("\nPróximo passo: make metabase-export-cvm")


if __name__ == "__main__":
    main()

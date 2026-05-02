#!/usr/bin/env python3
"""Cria 1 dashboard BCB Macro com 3 cards SQL no Metabase via API REST.

Uso: make metabase-setup-bcb
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


@dataclass
class CardSpec:
    name: str
    sql: str
    display: str
    dashboard: str
    row: int
    col: int
    size_x: int = 18
    size_y: int = 8


CARDS: list[CardSpec] = [
    CardSpec(
        name="SELIC Real Historica",
        display="line",
        dashboard="BCB Macro",
        row=0, col=0,
        sql="SELECT date, taxa_anual, selic_real FROM gold_bcb.macro_mensal ORDER BY date",
    ),
    CardSpec(
        name="SELIC vs Inflacao",
        display="line",
        dashboard="BCB Macro",
        row=8, col=0,
        sql="SELECT date, taxa_anual AS selic_anual, acumulado_12m AS ipca_12m FROM gold_bcb.macro_mensal ORDER BY date",
    ),
    CardSpec(
        name="PTAX Medio Mensal",
        display="line",
        dashboard="BCB Macro",
        row=16, col=0,
        sql="SELECT date, ptax_media, ptax_variacao_mensal_pct FROM gold_bcb.macro_mensal ORDER BY date",
    ),
]


class MetabaseClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "X-Metabase-Session": token,
        })

    def get(self, path: str) -> Any:
        resp = self._session.get(f"{self._base_url}{path}")
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        resp = self._session.post(f"{self._base_url}{path}", json=body)
        resp.raise_for_status()
        return resp.json()

    def put(self, path: str, body: dict[str, Any]) -> Any:
        resp = self._session.put(f"{self._base_url}{path}", json=body)
        resp.raise_for_status()
        return resp.json()


def authenticate(base_url: str, email: str, password: str) -> str:
    resp = requests.post(
        f"{base_url}/api/session",
        json={"username": email, "password": password},
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def find_database_id(client: MetabaseClient, name: str) -> int:
    databases = client.get("/api/database")
    data = databases.get("data", databases)
    match = next((db for db in data if db["name"] == name), None)
    if match is None:
        available = [db["name"] for db in data]
        raise SystemExit(f"Conexao {name!r} nao encontrada. Disponiveis: {available}")
    return match["id"]


def create_card(client: MetabaseClient, spec: CardSpec, db_id: int) -> int:
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
    result = client.post("/api/dashboard", {"name": name})
    return result["id"]


def add_cards_to_dashboard(
    client: MetabaseClient,
    dashboard_id: int,
    card_entries: list[dict[str, Any]],
) -> None:
    client.put(f"/api/dashboard/{dashboard_id}/cards", {"cards": card_entries})


def main() -> None:
    email = os.environ.get("METABASE_ADMIN_EMAIL")
    password = os.environ.get("METABASE_ADMIN_PASSWORD")
    if not email or not password:
        print("Erro: defina METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env", file=sys.stderr)
        sys.exit(1)

    print(f"-> Autenticando em {METABASE_URL}...")
    token = authenticate(METABASE_URL, email, password)
    client = MetabaseClient(METABASE_URL, token)

    print(f"-> Buscando conexao {DB_NAME!r}...")
    db_id = find_database_id(client, DB_NAME)
    print(f"   Conexao encontrada: ID={db_id}")

    print("-> Criando 3 cards SQL...")
    card_id_map: dict[str, int] = {}
    for spec in CARDS:
        card_id = create_card(client, spec, db_id)
        card_id_map[spec.name] = card_id
        print(f"   OK {spec.name} (ID={card_id})")

    print("-> Criando dashboard BCB Macro...")
    dashboard_id = create_dashboard(client, "BCB Macro")
    print(f"   OK BCB Macro (ID={dashboard_id})")

    print("-> Adicionando cards ao dashboard...")
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
        for i, spec in enumerate(CARDS)
    ]
    add_cards_to_dashboard(client, dashboard_id, card_entries)
    print("   OK 3 cards adicionados")

    print(f"\nSetup concluido! Dashboard disponivel em:")
    print(f"  {METABASE_URL}/dashboard/{dashboard_id} -- BCB Macro")
    print("\nProximo passo: make metabase-export")


if __name__ == "__main__":
    main()

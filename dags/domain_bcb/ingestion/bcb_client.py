"""Wrapper python-bcb para ingestão de séries temporais do BCB SGS.

Responsabilidades:
- SERIES_CONFIG: configuração centralizada de todas as séries do domínio BCB.
- get_load_range: smart first run — detecta tabela vazia (backfill) ou retorna delta.
- fetch_series: busca dados na API BCB SGS via python-bcb.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional

import pandas as pd
from bcb import sgs

if TYPE_CHECKING:
    from airflow.providers.postgres.hooks.postgres import PostgresHook

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeriesConfig:
    """Configuração imutável de uma série temporal BCB."""

    name: str
    code: int
    start_date: date
    table: str
    frequency: str  # "daily" | "monthly"
    value_column: str


SERIES_CONFIG: dict[str, SeriesConfig] = {
    "selic_daily": SeriesConfig(
        name="SELIC",
        code=11,
        start_date=date(2000, 1, 1),
        table="bronze_bcb.selic_daily",
        frequency="daily",
        value_column="SELIC",
    ),
    "ipca_monthly": SeriesConfig(
        name="IPCA",
        code=433,
        start_date=date(1994, 7, 1),
        table="bronze_bcb.ipca_monthly",
        frequency="monthly",
        value_column="IPCA",
    ),
    "ptax_daily": SeriesConfig(
        name="PTAX",
        code=1,
        start_date=date(1999, 1, 1),
        table="bronze_bcb.ptax_daily",
        frequency="daily",
        value_column="PTAX",
    ),
}


def get_load_range(
    config: SeriesConfig,
    hook: "PostgresHook",
) -> Optional[tuple[date, date]]:
    """Determina o intervalo de datas a carregar para uma série BCB.

    Lógica smart first run:
    - Tabela vazia → (start_date configurado, hoje) — backfill completo.
    - Tabela com dados → (max_date + 1 dia, hoje) — delta incremental.
    - Tabela já atualizada para hoje → None (skip).
    - IPCA mensal com mês corrente gravado → None (skip).

    Args:
        config: configuração da série (via SERIES_CONFIG).
        hook: PostgresHook conectado ao banco finlake.

    Returns:
        Tupla (start, end) com intervalo a carregar, ou None se nada a fazer.
    """
    today = date.today()

    row = hook.get_first(f"SELECT MAX(date) FROM {config.table}")
    max_date: Optional[date] = row[0] if row and row[0] else None

    if max_date is None:
        logger.info(
            "%s: tabela vazia — backfill de %s até %s.",
            config.name,
            config.start_date,
            today,
        )
        return (config.start_date, today)

    if config.frequency == "monthly":
        current_month_start = today.replace(day=1)
        if max_date >= current_month_start:
            logger.info(
                "%s: mês %s já gravado — nada a fazer.",
                config.name,
                current_month_start,
            )
            return None

    next_date = max_date + timedelta(days=1)
    if next_date > today:
        logger.info("%s: já atualizado até %s — nada a fazer.", config.name, max_date)
        return None

    logger.info("%s: delta de %s até %s.", config.name, next_date, today)
    return (next_date, today)


def fetch_series(config: SeriesConfig, start: date, end: date) -> pd.DataFrame:
    """Busca série temporal na API SGS do BCB com chunking de 10 anos.

    A API BCB limita consultas de séries diárias a janelas de 10 anos.
    Esta função divide automaticamente o range em chunks e concatena os resultados.
    """
    CHUNK_YEARS = 9  # margem de segurança abaixo do limite de 10 anos

    chunks: list[pd.DataFrame] = []
    chunk_start = start

    while chunk_start <= end:
        chunk_end = min(
            date(chunk_start.year + CHUNK_YEARS, chunk_start.month, chunk_start.day),
            end,
        )
        df_chunk = sgs.get(
            {config.value_column: config.code},
            start=chunk_start,
            end=chunk_end,
        )
        if not df_chunk.empty:
            chunks.append(df_chunk)
        logger.info(
            "%s: chunk %s → %s: %d registros.",
            config.name, chunk_start, chunk_end, len(df_chunk),
        )
        chunk_start = chunk_end + timedelta(days=1)

    if not chunks:
        return pd.DataFrame(columns=[config.value_column])

    result = pd.concat(chunks)
    logger.info("%s: total %d registros obtidos da API BCB.", config.name, len(result))
    return result

"""Funções de ingestão Bronze para o domínio BCB.

Cada função pública é um callable para PythonOperator do Airflow.
Toda a lógica de idempotência, smart first run e upsert é centralizada aqui.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from airflow.exceptions import AirflowSkipException
from airflow.providers.postgres.hooks.postgres import PostgresHook

from domain_bcb.ingestion.bcb_client import (
    SERIES_CONFIG,
    SeriesConfig,
    fetch_series,
    get_load_range,
)

logger = logging.getLogger(__name__)

CONN_ID = "finlake_postgres"

_UPSERT_SQL = "INSERT INTO {table} (date, valor) VALUES (%s, %s) ON CONFLICT (date) DO NOTHING"


def _upsert_dataframe(hook: PostgresHook, config: SeriesConfig, df: pd.DataFrame) -> int:
    """Insere registros do DataFrame no PostgreSQL com idempotência.

    Usa INSERT ... ON CONFLICT (date) DO NOTHING — reprocessamento seguro.

    Args:
        hook: PostgresHook com conexão ativa ao banco finlake.
        config: configuração da série (tabela e coluna de valor).
        df: DataFrame com DatetimeIndex e coluna `config.value_column`.

    Returns:
        Número de linhas processadas (pode ser menor que inseridas por conflito).
    """
    if df.empty:
        logger.warning("%s: DataFrame vazio — nenhum registro para inserir.", config.name)
        return 0

    rows: list[tuple[date, float]] = [
        (idx.date(), float(val))
        for idx, val in zip(df.index, df[config.value_column])
        if pd.notna(val)
    ]

    if not rows:
        logger.warning("%s: todos os valores são nulos — nenhum registro inserido.", config.name)
        return 0

    sql = _UPSERT_SQL.format(table=config.table)
    conn = hook.get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "%s: %d registros processados em %s (ON CONFLICT DO NOTHING ativo).",
        config.name,
        len(rows),
        config.table,
    )
    return len(rows)


def _ingest_series(series_key: str) -> None:
    """Executa o ciclo completo de ingestão para uma série BCB.

    1. Determina intervalo via get_load_range (smart first run ou delta).
    2. Faz skip via AirflowSkipException se não há dados a carregar.
    3. Busca dados da API BCB SGS via python-bcb.
    4. Insere no PostgreSQL com upsert idempotente.

    Args:
        series_key: chave em SERIES_CONFIG (ex: "selic_daily").
    """
    config = SERIES_CONFIG[series_key]
    hook = PostgresHook(postgres_conn_id=CONN_ID)

    load_range = get_load_range(config, hook)
    if load_range is None:
        raise AirflowSkipException(f"{config.name}: nada a carregar — skip.")

    start, end = load_range
    df = fetch_series(config, start, end)
    _upsert_dataframe(hook, config, df)


def ingest_selic(**kwargs: object) -> None:
    """Task Airflow: ingestão diária da taxa SELIC (série BCB SGS 11).

    Frequência: diária (apenas dias úteis).
    Backfill: desde 2000-01-01 na primeira execução.
    """
    _ingest_series("selic_daily")


def ingest_ipca(**kwargs: object) -> None:
    """Task Airflow: ingestão mensal do IPCA (série BCB SGS 433).

    Frequência: mensal (primeiro dia do mês).
    Backfill: desde 1994-07-01 (Plano Real) na primeira execução.
    Aparece como Skipped na maioria dos dias do mês — comportamento esperado.
    """
    _ingest_series("ipca_monthly")


def ingest_ptax(**kwargs: object) -> None:
    """Task Airflow: ingestão diária da PTAX venda USD/BRL (série BCB SGS 1).

    Frequência: diária (apenas dias úteis).
    Backfill: desde 1999-01-01 (câmbio flutuante) na primeira execução.
    """
    _ingest_series("ptax_daily")

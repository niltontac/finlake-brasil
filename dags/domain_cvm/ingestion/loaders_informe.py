"""Callable Airflow para ingestão mensal do informe diário CVM.

Processa sempre o mês anterior ao mês corrente.
Idempotência via ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from airflow.providers.postgres.hooks.postgres import PostgresHook

from domain_cvm.ingestion.cvm_client import (
    _safe_float,
    _safe_int,
    build_informe_url,
    download_bytes,
    parse_csv_bytes,
    unzip_csv,
    validate_informe_rows,
)

logger = logging.getLogger(__name__)

CONN_ID = "finlake_postgres"

_INSERT_SQL = """
    INSERT INTO bronze_cvm.informe_diario
        (tp_fundo, cnpj_fundo, dt_comptc, vl_total, vl_quota,
         vl_patrim_liq, captc_dia, resg_dia, nr_cotst, source_url)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING
"""


def ingest_informe_mensal(**kwargs: object) -> None:
    """Task Airflow: ingestão do informe diário do mês anterior ao corrente.

    Frequência: @monthly, catchup=False.
    Determina automaticamente year/month para garantir que o arquivo
    já esteja disponível na CVM (mês N-1 fica disponível no início de N).
    """
    today = date.today()
    last_month = today.replace(day=1) - timedelta(days=1)
    year, month = last_month.year, last_month.month

    url = build_informe_url(year, month)
    logger.info("Processando informe %d-%02d: %s", year, month, url)

    zip_bytes = download_bytes(url)
    csv_bytes = unzip_csv(zip_bytes)
    df = parse_csv_bytes(csv_bytes)
    df = validate_informe_rows(df)

    if df.empty:
        logger.warning("DataFrame vazio após validação — nenhum registro inserido.")
        return

    hook = PostgresHook(postgres_conn_id=CONN_ID)
    _insert_informe(hook, df, url)


def _insert_informe(hook: PostgresHook, df: pd.DataFrame, source_url: str) -> None:
    """Insere registros do informe com ON CONFLICT DO NOTHING."""
    parsed_dates = pd.to_datetime(df["DT_COMPTC"], errors="coerce")

    rows = [
        (
            row.get("TP_FUNDO") or None,
            str(row["CNPJ_FUNDO"]).strip(),
            parsed_dates.iloc[i].date(),
            _safe_float(row.get("VL_TOTAL")),
            _safe_float(row.get("VL_QUOTA")),
            _safe_float(row.get("VL_PATRIM_LIQ")),
            _safe_float(row.get("CAPTC_DIA")),
            _safe_float(row.get("RESG_DIA")),
            _safe_int(row.get("NR_COTST")),
            source_url,
        )
        for i, (_, row) in enumerate(df.iterrows())
    ]

    conn = hook.get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "bronze_cvm.informe_diario: %d registros processados (ON CONFLICT DO NOTHING).",
        len(rows),
    )

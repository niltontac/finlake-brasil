"""Script PySpark para carga histórica do informe diário CVM.

Uso:
    spark-submit scripts/spark/historical_load_cvm.py \
        --start-year 2000 --end-year 2024

Variáveis de ambiente obrigatórias:
    FINLAKE_JDBC_URL      jdbc:postgresql://localhost:5433/finlake
    FINLAKE_JDBC_USER     postgres
    FINLAKE_JDBC_PASSWORD <senha>
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "dags"))

import psycopg2
from pyspark.sql import SparkSession

from domain_cvm.ingestion.cvm_client import (
    build_informe_url,
    download_bytes,
    unzip_csv,
)
from domain_cvm.ingestion.cvm_client import _safe_float, _safe_int

import io
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_INSERT_SQL = """
  INSERT INTO bronze_cvm.informe_diario
        (tp_fundo, cnpj_fundo, dt_comptc, vl_total, vl_quota,
         vl_patrim_liq, captc_dia, resg_dia, nr_cotst, source_url)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING
"""


def _parse_to_pandas(csv_bytes: bytes, source_url: str) -> pd.DataFrame:
    df = pd.read_csv(
        io.BytesIO(csv_bytes),
        sep=";",
        encoding="latin1",
        dtype=str,
        low_memory=False,
    )
    if "CNPJ_FUNDO_CLASSE" in df.columns:
        df = df.rename(columns={
            "CNPJ_FUNDO_CLASSE": "CNPJ_FUNDO",
            "TP_FUNDO_CLASSE": "TP_FUNDO",
        })
    mask = df["CNPJ_FUNDO"].notna() & df["CNPJ_FUNDO"].str.strip().astype(bool)
    df = df[mask].copy()
    parsed_dates = pd.to_datetime(df["DT_COMPTC"], errors="coerce")
    df = df[parsed_dates.notna()].copy()
    parsed_dates = parsed_dates[parsed_dates.notna()]
    result = pd.DataFrame({
        "tp_fundo":      df.get("TP_FUNDO"),
        "cnpj_fundo":    df["CNPJ_FUNDO"].str.strip(),
        "dt_comptc":     parsed_dates.dt.date,
        "vl_total":      df.get("VL_TOTAL", pd.Series(dtype=str)).apply(_safe_float),
        "vl_quota":      df.get("VL_QUOTA", pd.Series(dtype=str)).apply(_safe_float),
        "vl_patrim_liq": df.get("VL_PATRIM_LIQ", pd.Series(dtype=str)).apply(_safe_float),
        "captc_dia":     df.get("CAPTC_DIA", pd.Series(dtype=str)).apply(_safe_float),
        "resg_dia":      df.get("RESG_DIA", pd.Series(dtype=str)).apply(_safe_float),
        "nr_cotst":      df.get("NR_COTST", pd.Series(dtype=str)).apply(_safe_int),
        "source_url":    source_url,
    })
    return result.drop_duplicates(subset=["cnpj_fundo", "dt_comptc"])


def _load_url(spark: SparkSession, url: str, pg_props: dict) -> int:
    try:
        zip_bytes = download_bytes(url)
        csv_bytes = unzip_csv(zip_bytes)
    except Exception as exc:
        logger.error("Falha no download/unzip %s: %s — pulando.", url, exc)
        return 0

    pdf = _parse_to_pandas(csv_bytes, url)
    if pdf.empty:
        logger.warning("DataFrame vazio para %s.", url)
        return 0

    rows = [
        (
            row.tp_fundo if pd.notna(row.tp_fundo) else None,
            row.cnpj_fundo,
            row.dt_comptc,
            row.vl_total if pd.notna(row.vl_total) else None,
            row.vl_quota if pd.notna(row.vl_quota) else None,
            row.vl_patrim_liq if pd.notna(row.vl_patrim_liq) else None,
            row.captc_dia if pd.notna(row.captc_dia) else None,
            row.resg_dia if pd.notna(row.resg_dia) else None,
            int(row.nr_cotst) if pd.notna(row.nr_cotst) else None,
            url,
        )
        for row in pdf.itertuples(index=False)
    ]

    conn = psycopg2.connect(**pg_props)
    try:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info("Carregado %s: %d registros.", url, len(rows))
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    args = parser.parse_args()

    pg_props = {
        "host":     "localhost",
        "port":     5433,
        "dbname":   "finlake",
        "user":     os.environ["FINLAKE_JDBC_USER"],
        "password": os.environ["FINLAKE_JDBC_PASSWORD"],
    }

    spark = (
        SparkSession.builder
        .master("local[*]")
        .appName("CVM_Historical_Load")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    today = date.today()
    total = 0

    for year in range(args.start_year, args.end_year + 1):
        if year <= 2020:
            url = build_informe_url(year, 1)
            total += _load_url(spark, url, pg_props)
        else:
            max_month = 12 if year < today.year else max(today.month - 1, 1)
            for month in range(1, max_month + 1):
                url = build_informe_url(year, month)
                total += _load_url(spark, url, pg_props)

    logger.info("Concluído. Total: %d registros.", total)
    spark.stop()


if __name__ == "__main__":
    main()

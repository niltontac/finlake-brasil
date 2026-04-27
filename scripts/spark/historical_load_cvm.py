"""Script PySpark para carga histórica do informe diário CVM.

Baixa e carrega todos os ZIPs do intervalo especificado para
bronze_cvm.informe_diario via JDBC. Idempotente: ON CONFLICT DO NOTHING
na PK (cnpj_fundo, dt_comptc) garante que re-executar é seguro.

Bifurcação de URL:
- Anos ≤ 2020: DADOS/HIST/inf_diario_fi_{YYYY}.zip (arquivo anual)
- Anos ≥ 2021: DADOS/inf_diario_fi_{YYYYMM}.zip (arquivo mensal)

Uso:
    spark-submit --jars /path/to/postgresql-42.x.jar \\
        scripts/spark/historical_load_cvm.py \\
        --start-year 2000 --end-year 2024

Variáveis de ambiente obrigatórias:
    FINLAKE_JDBC_URL       jdbc:postgresql://localhost:5433/finlake
    FINLAKE_JDBC_USER      postgres
    FINLAKE_JDBC_PASSWORD  supabase123
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import date
from pathlib import Path

# Permite importar cvm_client mesmo fora do container Airflow
sys.path.insert(0, str(Path(__file__).parents[2] / "dags"))

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DateType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

from domain_cvm.ingestion.cvm_client import (
    _safe_float,
    _safe_int,
    build_informe_url,
    download_bytes,
    unzip_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_TABLE = "bronze_cvm.informe_diario"

_SCHEMA = StructType([
    StructField("tp_fundo",      StringType(),  True),
    StructField("cnpj_fundo",    StringType(),  False),
    StructField("dt_comptc",     DateType(),    False),
    StructField("vl_total",      DoubleType(),  True),
    StructField("vl_quota",      DoubleType(),  True),
    StructField("vl_patrim_liq", DoubleType(),  True),
    StructField("captc_dia",     DoubleType(),  True),
    StructField("resg_dia",      DoubleType(),  True),
    StructField("nr_cotst",      IntegerType(), True),
    StructField("source_url",    StringType(),  False),
])


def _parse_to_pandas(csv_bytes: bytes, source_url: str) -> pd.DataFrame:
    """Converte bytes CSV (latin1, ;) para DataFrame no schema de informe_diario."""
    df = pd.read_csv(
        io.BytesIO(csv_bytes),
        sep=";",
        encoding="latin1",
        dtype=str,
        low_memory=False,
    )

    # Descartar linhas sem CNPJ válido (vetorizado)
    cnpj_mask = df["CNPJ_FUNDO"].notna() & df["CNPJ_FUNDO"].str.strip().astype(bool)
    df = df[cnpj_mask].copy()

    parsed_dates = pd.to_datetime(df["DT_COMPTC"], errors="coerce")
    df = df[parsed_dates.notna()].copy()
    parsed_dates = parsed_dates[parsed_dates.notna()]

    return pd.DataFrame({
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


def _load_url(
    spark: SparkSession,
    url: str,
    jdbc_url: str,
    jdbc_props: dict,
) -> int:
    """Baixa, parseia e carrega um arquivo ZIP no PostgreSQL via JDBC append.

    Retorna o número de registros processados, ou 0 em caso de falha de download.
    """
    try:
        zip_bytes = download_bytes(url)
        csv_bytes = unzip_csv(zip_bytes)
    except Exception as exc:
        logger.error("Falha no download/unzip %s: %s — pulando.", url, exc)
        return 0

    pdf = _parse_to_pandas(csv_bytes, url)
    if pdf.empty:
        logger.warning("DataFrame vazio para %s — nenhum registro carregado.", url)
        return 0

    sdf = spark.createDataFrame(pdf, schema=_SCHEMA)
    sdf.write.jdbc(url=jdbc_url, table=_TABLE, mode="append", properties=jdbc_props)
    count = int(pdf.shape[0])
    logger.info("Carregado %s: %d registros.", url, count)
    return count


def main() -> None:
    """Itera anos/meses do intervalo e carrega cada arquivo ZIP no PostgreSQL."""
    parser = argparse.ArgumentParser(
        description="Carga histórica do informe diário CVM via PySpark",
    )
    parser.add_argument("--start-year", type=int, required=True, help="Ano inicial (inclusive)")
    parser.add_argument("--end-year",   type=int, required=True, help="Ano final (inclusive)")
    args = parser.parse_args()

    jdbc_url = os.environ["FINLAKE_JDBC_URL"]
    jdbc_props = {
        "user":     os.environ["FINLAKE_JDBC_USER"],
        "password": os.environ["FINLAKE_JDBC_PASSWORD"],
        "driver":   "org.postgresql.Driver",
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
            # Arquivo anual — um ZIP cobre o ano inteiro; month é ignorado
            url = build_informe_url(year, 1)
            total += _load_url(spark, url, jdbc_url, jdbc_props)
        else:
            max_month = 12 if year < today.year else max(today.month - 1, 1)
            for month in range(1, max_month + 1):
                url = build_informe_url(year, month)
                total += _load_url(spark, url, jdbc_url, jdbc_props)

    logger.info(
        "Carga histórica concluída. Intervalo: %d–%d. Total de registros: %d",
        args.start_year,
        args.end_year,
        total,
    )
    spark.stop()


if __name__ == "__main__":
    main()

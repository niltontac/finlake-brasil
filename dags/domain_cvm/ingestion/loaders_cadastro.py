"""Callable Airflow para ingestão diária do cadastro de fundos CVM.

SCD Tipo 1: ON CONFLICT (cnpj_fundo) DO UPDATE — espelha estado atual da fonte.
Todas as 40 colunas do cad_fi.csv são mapeadas; colunas ausentes no CSV
são silenciosamente ignoradas.
"""
from __future__ import annotations

import logging

import pandas as pd
from airflow.providers.postgres.hooks.postgres import PostgresHook

from domain_cvm.ingestion.cvm_client import (
    CADASTRO_URL,
    download_bytes,
    parse_csv_bytes,
    validate_cadastro_rows,
)

logger = logging.getLogger(__name__)

CONN_ID = "finlake_postgres"

# Mapeamento CSV (MAIÚSCULAS) → coluna PostgreSQL (minúsculas)
# Cobre todas as 40 colunas confirmadas do cad_fi.csv
_CSV_TO_DB: dict[str, str] = {
    "CNPJ_FUNDO": "cnpj_fundo",
    "TP_FUNDO": "tp_fundo",
    "DENOM_SOCIAL": "denom_social",
    "CD_CVM": "cd_cvm",
    "DT_REG": "dt_reg",
    "DT_CONST": "dt_const",
    "DT_CANCEL": "dt_cancel",
    "DT_INI_ATIV": "dt_ini_ativ",
    "DT_FIM_ATIV": "dt_fim_ativ",
    "SIT": "sit",
    "DT_INI_SIT": "dt_ini_sit",
    "DT_INI_EXERC": "dt_ini_exerc",
    "DT_FIM_EXERC": "dt_fim_exerc",
    "CLASSE": "classe",
    "CLASSE_ANBIMA": "classe_anbima",
    "RENTAB_FUNDO": "rentab_fundo",
    "PUBLICO_ALVO": "publico_alvo",
    "CONDOM": "condom",
    "FUNDO_COTAS": "fundo_cotas",
    "FUNDO_EXCLUSIVO": "fundo_exclusivo",
    "TRIB_LPRAZO": "trib_lprazo",
    "ENTID_INVEST": "entid_invest",
    "INVEST_CEMPR_EXTER": "invest_cempr_exter",
    "TAXA_PERFM": "taxa_perfm",
    "INF_TAXA_PERFM": "inf_taxa_perfm",
    "TAXA_ADM": "taxa_adm",
    "INF_TAXA_ADM": "inf_taxa_adm",
    "VL_PATRIM_LIQ": "vl_patrim_liq",
    "DT_PATRIM_LIQ": "dt_patrim_liq",
    "CNPJ_ADMIN": "cnpj_admin",
    "ADMIN": "admin",
    "DIRETOR": "diretor",
    "PF_PJ_GESTOR": "pf_pj_gestor",
    "CPF_CNPJ_GESTOR": "cpf_cnpj_gestor",
    "GESTOR": "gestor",
    "CNPJ_AUDITOR": "cnpj_auditor",
    "AUDITOR": "auditor",
    "CNPJ_CUSTODIANTE": "cnpj_custodiante",
    "CUSTODIANTE": "custodiante",
    "CNPJ_CONTROLADOR": "cnpj_controlador",
    "CONTROLADOR": "controlador",
}


def ingest_cadastro(**kwargs: object) -> None:
    """Task Airflow: ingestão diária do cadastro de fundos CVM (SCD Tipo 1).

    1. Baixa cad_fi.csv (latin1, separador ;).
    2. Descarta linhas com CNPJ_FUNDO inválido.
    3. Renomeia colunas CSV → PostgreSQL.
    4. Executa upsert: INSERT ... ON CONFLICT (cnpj_fundo) DO UPDATE.

    Colunas presentes no CSV mas ausentes no DDL são ignoradas.
    Colunas do DDL ausentes no CSV não são enviadas (SQL dinâmico).
    """
    content = download_bytes(CADASTRO_URL)
    df = parse_csv_bytes(content)
    df = validate_cadastro_rows(df)

    # Renomear e filtrar apenas colunas mapeadas que existem no CSV
    df = df.rename(columns=_CSV_TO_DB)
    db_cols = [c for c in _CSV_TO_DB.values() if c in df.columns]
    df = df[db_cols].copy()

    # Substituir strings "nan" e vazias por None para insert correto
    df = df.replace({"nan": None, "": None})
    df = df.where(pd.notna(df), other=None)

    hook = PostgresHook(postgres_conn_id=CONN_ID)
    _upsert_cadastro(hook, df)


def _upsert_cadastro(hook: PostgresHook, df: pd.DataFrame) -> None:
    """Executa upsert SCD Tipo 1 para o cadastro de fundos."""
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    update_cols = [c for c in cols if c != "cnpj_fundo"]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    sql = f"""
        INSERT INTO bronze_cvm.cadastro ({", ".join(cols)}, source_url, updated_at)
        VALUES ({placeholders}, %s, NOW())
        ON CONFLICT (cnpj_fundo) DO UPDATE SET
            {updates},
            source_url = EXCLUDED.source_url,
            updated_at  = NOW()
    """

    rows = [(*row, CADASTRO_URL) for row in df.itertuples(index=False, name=None)]

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
        "bronze_cvm.cadastro: %d registros processados (ON CONFLICT DO UPDATE).",
        len(rows),
    )

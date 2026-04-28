"""Módulo de acesso ao portal de dados abertos da CVM.

Responsabilidades:
- build_informe_url: bifurcação HIST/ (≤2020) vs DADOS/ (2021+).
- download_bytes: HTTP GET com timeout configurável.
- unzip_csv: descompressão em memória via BytesIO.
- parse_csv_bytes: parse CSV latin1 em DataFrame com todos os campos como str.
- validate_cadastro_rows: descarta linhas com CNPJ_FUNDO inválido (vetorizado).
- validate_informe_rows: descarta linhas com CNPJ ou data inválidos (vetorizado).
- _safe_float / _safe_int: conversão tolerante para colunas numéricas CVM.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from typing import Optional

import pandas as pd
import requests
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

CVM_BASE = "https://dados.cvm.gov.br/dados/FI"
CADASTRO_URL = f"{CVM_BASE}/CAD/DADOS/cad_fi.csv"
_INFORME_BASE = f"{CVM_BASE}/DOC/INF_DIARIO/DADOS"


def build_informe_url(year: int, month: int) -> str:
    """Retorna URL do ZIP do informe diário para o ano/mês informado.

    Para anos ≤ 2020, retorna arquivo anual (HIST/) — month é ignorado.
    Para 2021+, retorna arquivo mensal (DADOS/).
    """
    if year <= 2020:
        return f"{_INFORME_BASE}/HIST/inf_diario_fi_{year}.zip"
    return f"{_INFORME_BASE}/inf_diario_fi_{year}{month:02d}.zip"


def download_bytes(url: str, timeout: int = 120) -> bytes:
    """Faz download de um arquivo via HTTP GET e retorna os bytes brutos."""
    logger.info("Download: %s", url)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def unzip_csv(zip_bytes: bytes) -> bytes:
    """Descomprime o primeiro .csv encontrado dentro de um ZIP em memória."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        logger.info("Descomprimindo: %s", csv_name)
        return zf.read(csv_name)


def parse_csv_bytes(
    content: bytes,
    sep: str = ";",
    encoding: str = "latin1",
) -> pd.DataFrame:
    """Faz parse de bytes CSV em DataFrame, preservando todos os campos como str."""
    return pd.read_csv(
        io.BytesIO(content),
        sep=sep,
        encoding=encoding,
        dtype=str,
        low_memory=False,
    )


# ---------------------------------------------------------------------------
# Modelos Pydantic — documentação dos campos críticos
# (validação em batch usa operações vetorizadas abaixo)
# ---------------------------------------------------------------------------

class InformeRecord(BaseModel):
    """Modelo de validação de uma linha do informe diário."""

    tp_fundo: Optional[str] = None
    cnpj_fundo: str
    dt_comptc: date
    vl_total: Optional[float] = None
    vl_quota: Optional[float] = None
    vl_patrim_liq: Optional[float] = None
    captc_dia: Optional[float] = None
    resg_dia: Optional[float] = None
    nr_cotst: Optional[int] = None

    @field_validator("cnpj_fundo")
    @classmethod
    def cnpj_nao_vazio(cls, v: str) -> str:
        """CNPJ_FUNDO é a PK — não pode ser vazio."""
        if not v or not v.strip():
            raise ValueError("CNPJ_FUNDO não pode ser vazio")
        return v.strip()


class CadastroRecord(BaseModel):
    """Modelo de validação de uma linha do cadastro — apenas CNPJ_FUNDO (PK)."""

    cnpj_fundo: str

    @field_validator("cnpj_fundo")
    @classmethod
    def cnpj_nao_vazio(cls, v: str) -> str:
        """CNPJ_FUNDO é a PK — não pode ser vazio."""
        if not v or not v.strip():
            raise ValueError("CNPJ_FUNDO não pode ser vazio")
        return v.strip()


# ---------------------------------------------------------------------------
# Validação em batch — operações vetorizadas sobre o DataFrame inteiro
# ---------------------------------------------------------------------------

def validate_cadastro_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Descarta linhas com CNPJ_FUNDO nulo ou em branco.

    Operação vetorizada — sem iterrows. Eficiente para ~30k linhas.
    """
    mask = df["CNPJ_FUNDO"].notna() & df["CNPJ_FUNDO"].str.strip().astype(bool)
    discarded = int((~mask).sum())
    if discarded:
        logger.warning("%d linhas de cadastro descartadas (CNPJ_FUNDO vazio).", discarded)
    return df[mask].copy()


def _normalize_informe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza schema 2024+ da CVM: CNPJ_FUNDO_CLASSE → CNPJ_FUNDO."""
    if "CNPJ_FUNDO_CLASSE" in df.columns:
        df = df.rename(columns={
            "CNPJ_FUNDO_CLASSE": "CNPJ_FUNDO",
            "TP_FUNDO_CLASSE": "TP_FUNDO",
        })
    return df


def validate_informe_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Descarta linhas do informe com CNPJ_FUNDO inválido ou DT_COMPTC não parseável.

    Operação vetorizada — sem iterrows. Eficiente para ~48MB descomprimido.

    Regras:
    - CNPJ_FUNDO: não pode ser nulo nem em branco (é a PK).
    - DT_COMPTC: deve ser uma data válida (pd.to_datetime errors='coerce').
    Linhas que violam qualquer regra são descartadas com logger.warning.
    """
    df = _normalize_informe_columns(df)
    cnpj_mask = df["CNPJ_FUNDO"].notna() & df["CNPJ_FUNDO"].str.strip().astype(bool)

    parsed_dates = pd.to_datetime(df["DT_COMPTC"], errors="coerce")
    date_mask = parsed_dates.notna()

    valid_mask = cnpj_mask & date_mask
    discarded = int((~valid_mask).sum())
    if discarded:
        cnpj_bad = int((~cnpj_mask).sum())
        date_bad = int((cnpj_mask & ~date_mask).sum())
        logger.warning(
            "%d linhas do informe descartadas (CNPJ inválido: %d, data inválida: %d).",
            discarded,
            cnpj_bad,
            date_bad,
        )
    return df[valid_mask].copy()


# ---------------------------------------------------------------------------
# Helpers de conversão tolerante — usados nos loaders e no PySpark script
# ---------------------------------------------------------------------------

def _safe_float(val: object) -> Optional[float]:
    """Converte string/número para float. Aceita vírgula decimal. Retorna None em falha."""
    try:
        s = str(val).replace(",", ".").strip()
        return float(s) if s and s.lower() not in ("nan", "none", "") else None
    except (ValueError, TypeError):
        return None


def _safe_int(val: object) -> Optional[int]:
    """Converte string/número para int via float intermediário. Retorna None em falha."""
    try:
        s = str(val).strip()
        return int(float(s)) if s and s.lower() not in ("nan", "none", "") else None
    except (ValueError, TypeError):
        return None

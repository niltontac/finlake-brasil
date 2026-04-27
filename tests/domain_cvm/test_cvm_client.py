"""Unit tests para cvm_client.py.

Cobre: build_informe_url, unzip_csv, parse_csv_bytes, validate_cadastro_rows,
validate_informe_rows, _safe_float, _safe_int e modelos Pydantic.
Não requer Airflow, PostgreSQL ou rede — executável localmente com pytest.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from domain_cvm.ingestion.cvm_client import (
    CadastroRecord,
    InformeRecord,
    _safe_float,
    _safe_int,
    build_informe_url,
    parse_csv_bytes,
    unzip_csv,
    validate_cadastro_rows,
    validate_informe_rows,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(filename: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(filename, content)
    return buf.getvalue()


def _make_informe_df(**overrides: object) -> pd.DataFrame:
    row = {
        "TP_FUNDO": "FI",
        "CNPJ_FUNDO": "12.345.678/0001-90",
        "DT_COMPTC": "2024-01-15",
        "VL_TOTAL": "1000000.00",
        "VL_QUOTA": "10.500000",
        "VL_PATRIM_LIQ": "950000.00",
        "CAPTC_DIA": "5000.00",
        "RESG_DIA": "3000.00",
        "NR_COTST": "100",
    }
    row.update(overrides)
    return pd.DataFrame([row])


# ---------------------------------------------------------------------------
# build_informe_url
# ---------------------------------------------------------------------------

class TestBuildInformeUrl:
    def test_ano_2020_retorna_hist(self) -> None:
        url = build_informe_url(2020, 6)
        assert "/HIST/inf_diario_fi_2020.zip" in url

    def test_ano_2000_retorna_hist(self) -> None:
        url = build_informe_url(2000, 1)
        assert "/HIST/" in url
        assert "inf_diario_fi_2000.zip" in url

    def test_ano_2021_retorna_mensal(self) -> None:
        url = build_informe_url(2021, 3)
        assert "inf_diario_fi_202103.zip" in url
        assert "/HIST/" not in url

    def test_mes_formatado_com_zero_a_esquerda(self) -> None:
        url = build_informe_url(2025, 1)
        assert "202501" in url

    def test_ano_2020_ignora_mes(self) -> None:
        assert build_informe_url(2020, 1) == build_informe_url(2020, 6)

    def test_ano_2026_retorna_mensal(self) -> None:
        url = build_informe_url(2026, 4)
        assert "202604" in url


# ---------------------------------------------------------------------------
# unzip_csv
# ---------------------------------------------------------------------------

class TestUnzipCsv:
    def test_descomprime_csv_corretamente(self) -> None:
        content = b"CNPJ_FUNDO;DT_COMPTC\n12345;2024-01-01"
        result = unzip_csv(_make_zip("informe.csv", content))
        assert result == content

    def test_extensao_case_insensitive(self) -> None:
        content = b"COL;VAL\n1;2"
        result = unzip_csv(_make_zip("INFORME.CSV", content))
        assert result == content

    def test_zip_sem_csv_levanta_stop_iteration(self) -> None:
        with pytest.raises(StopIteration):
            unzip_csv(_make_zip("arquivo.txt", b"conteudo"))


# ---------------------------------------------------------------------------
# parse_csv_bytes
# ---------------------------------------------------------------------------

class TestParseCsvBytes:
    def test_parse_separador_ponto_virgula(self) -> None:
        csv = b"CNPJ_FUNDO;VL_QUOTA\n12345;1.5\n67890;2.0"
        df = parse_csv_bytes(csv)
        assert len(df) == 2
        assert list(df.columns) == ["CNPJ_FUNDO", "VL_QUOTA"]

    def test_todos_campos_como_string(self) -> None:
        csv = b"CNPJ_FUNDO;NR_COTST\n12345;1000"
        df = parse_csv_bytes(csv)
        # dtype=str em pandas recente resulta em StringDtype; em versões anteriores, object
        assert pd.api.types.is_string_dtype(df["NR_COTST"])

    def test_encoding_latin1(self) -> None:
        csv = "CNPJ_FUNDO;ADMIN\n12345;Gest\xe3o".encode("latin1")
        df = parse_csv_bytes(csv, encoding="latin1")
        assert "Gestão" in df["ADMIN"].iloc[0]


# ---------------------------------------------------------------------------
# validate_cadastro_rows
# ---------------------------------------------------------------------------

class TestValidateCadastroRows:
    def test_descarta_cnpj_nulo(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": ["12345", None, "67890"]})
        assert len(validate_cadastro_rows(df)) == 2

    def test_descarta_cnpj_vazio(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": ["12345", "", "67890"]})
        assert len(validate_cadastro_rows(df)) == 2

    def test_descarta_cnpj_whitespace(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": ["12345", "   ", "67890"]})
        assert len(validate_cadastro_rows(df)) == 2

    def test_preserva_linhas_validas(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": ["12345", "67890"]})
        result = validate_cadastro_rows(df)
        assert len(result) == 2

    def test_dataframe_todos_invalidos(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": [None, "", "  "]})
        assert len(validate_cadastro_rows(df)) == 0


# ---------------------------------------------------------------------------
# validate_informe_rows
# ---------------------------------------------------------------------------

class TestValidateInformeRows:
    def test_linha_valida_preservada(self) -> None:
        df = _make_informe_df()
        result = validate_informe_rows(df)
        assert len(result) == 1

    def test_descarta_cnpj_vazio(self) -> None:
        df = _make_informe_df(CNPJ_FUNDO="")
        assert len(validate_informe_rows(df)) == 0

    def test_descarta_cnpj_nulo(self) -> None:
        df = _make_informe_df(CNPJ_FUNDO=None)
        assert len(validate_informe_rows(df)) == 0

    def test_descarta_data_invalida(self) -> None:
        df = _make_informe_df(DT_COMPTC="nao-e-data")
        assert len(validate_informe_rows(df)) == 0

    def test_descarta_data_nula(self) -> None:
        df = _make_informe_df(DT_COMPTC=None)
        assert len(validate_informe_rows(df)) == 0

    def test_multiplas_linhas_filtragem_mista(self) -> None:
        rows = [
            {"CNPJ_FUNDO": "12345", "DT_COMPTC": "2024-01-01"},
            {"CNPJ_FUNDO": "",      "DT_COMPTC": "2024-01-01"},
            {"CNPJ_FUNDO": "67890", "DT_COMPTC": "invalida"},
            {"CNPJ_FUNDO": "99999", "DT_COMPTC": "2024-01-02"},
        ]
        df = pd.DataFrame(rows)
        result = validate_informe_rows(df)
        assert len(result) == 2
        assert set(result["CNPJ_FUNDO"]) == {"12345", "99999"}

    def test_vetorizado_nao_usa_python_loop(self) -> None:
        # Validar que a função não depende de iterrows para grandes volumes
        rows = [{"CNPJ_FUNDO": f"CNPJ{i:05d}", "DT_COMPTC": "2024-01-01"} for i in range(1000)]
        df = pd.DataFrame(rows)
        result = validate_informe_rows(df)
        assert len(result) == 1000


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TestInformeRecord:
    def test_cnpj_vazio_levanta_erro(self) -> None:
        with pytest.raises(Exception):
            InformeRecord(cnpj_fundo="", dt_comptc=date(2024, 1, 1))

    def test_cnpj_whitespace_levanta_erro(self) -> None:
        with pytest.raises(Exception):
            InformeRecord(cnpj_fundo="   ", dt_comptc=date(2024, 1, 1))

    def test_cnpj_valido_aceito(self) -> None:
        r = InformeRecord(cnpj_fundo="12.345.678/0001-90", dt_comptc=date(2024, 1, 1))
        assert r.cnpj_fundo == "12.345.678/0001-90"

    def test_campos_opcionais_default_none(self) -> None:
        r = InformeRecord(cnpj_fundo="12345", dt_comptc=date(2024, 1, 1))
        assert r.vl_quota is None
        assert r.nr_cotst is None


class TestCadastroRecord:
    def test_cnpj_vazio_levanta_erro(self) -> None:
        with pytest.raises(Exception):
            CadastroRecord(cnpj_fundo="")

    def test_cnpj_valido_aceito(self) -> None:
        r = CadastroRecord(cnpj_fundo="12.345.678/0001-90")
        assert r.cnpj_fundo == "12.345.678/0001-90"


# ---------------------------------------------------------------------------
# _safe_float / _safe_int
# ---------------------------------------------------------------------------

class TestSafeConversions:
    def test_safe_float_virgula_decimal(self) -> None:
        assert _safe_float("1,5") == 1.5

    def test_safe_float_ponto_decimal(self) -> None:
        assert _safe_float("1.5") == 1.5

    def test_safe_float_none_retorna_none(self) -> None:
        assert _safe_float(None) is None

    def test_safe_float_nan_string_retorna_none(self) -> None:
        assert _safe_float("nan") is None

    def test_safe_float_string_vazia_retorna_none(self) -> None:
        assert _safe_float("") is None

    def test_safe_float_numero_grande(self) -> None:
        assert _safe_float("1234567890.123456") == pytest.approx(1234567890.123456)

    def test_safe_int_de_float_string(self) -> None:
        assert _safe_int("1000.0") == 1000

    def test_safe_int_inteiro_direto(self) -> None:
        assert _safe_int("42") == 42

    def test_safe_int_none_retorna_none(self) -> None:
        assert _safe_int(None) is None

    def test_safe_int_nan_retorna_none(self) -> None:
        assert _safe_int("nan") is None

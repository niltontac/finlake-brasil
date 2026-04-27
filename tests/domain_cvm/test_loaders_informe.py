"""Unit tests para loaders_informe.py.

Requer Apache Airflow instalado. Skipped automaticamente no ambiente local.
Executar dentro do container: python -m pytest tests/ -v
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

pytest.importorskip("airflow", reason="Apache Airflow não instalado — rodar dentro do container.")

from unittest.mock import MagicMock, patch

import pandas as pd

from domain_cvm.ingestion.loaders_informe import _insert_informe, ingest_informe_mensal


def _make_hook() -> MagicMock:
    hook = MagicMock()
    conn = MagicMock()
    hook.get_conn.return_value = conn
    conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return hook


def _make_zip_bytes(csv_content: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("informe.csv", csv_content.encode("latin1"))
    return buf.getvalue()


def _make_informe_df(n: int = 2) -> pd.DataFrame:
    return pd.DataFrame({
        "TP_FUNDO":      ["FI"] * n,
        "CNPJ_FUNDO":   [f"CNPJ{i:05d}" for i in range(n)],
        "DT_COMPTC":    ["2024-03-15"] * n,
        "VL_TOTAL":     ["1000000.00"] * n,
        "VL_QUOTA":     ["10.50"] * n,
        "VL_PATRIM_LIQ":["950000.00"] * n,
        "CAPTC_DIA":    ["5000.00"] * n,
        "RESG_DIA":     ["3000.00"] * n,
        "NR_COTST":     ["100"] * n,
    })


class TestInsertInforme:
    def test_chama_executemany(self) -> None:
        hook = _make_hook()
        df = _make_informe_df(3)
        _insert_informe(hook, df, "http://test-url.zip")
        conn = hook.get_conn.return_value
        conn.cursor.assert_called_once()
        conn.commit.assert_called_once()

    def test_rollback_em_excecao(self) -> None:
        hook = _make_hook()
        conn = hook.get_conn.return_value
        conn.cursor.return_value.__enter__.return_value.executemany.side_effect = RuntimeError("DB error")
        df = _make_informe_df(1)
        with pytest.raises(RuntimeError):
            _insert_informe(hook, df, "http://test.zip")
        conn.rollback.assert_called_once()

    def test_close_sempre_chamado(self) -> None:
        hook = _make_hook()
        _insert_informe(hook, _make_informe_df(1), "http://test.zip")
        hook.get_conn.return_value.close.assert_called_once()


class TestIngestInformeMensal:
    def test_determina_mes_anterior(self) -> None:
        today = date.today()
        last_month = (today.replace(day=1)).replace(day=1).__class__(
            today.year if today.month > 1 else today.year - 1,
            today.month - 1 if today.month > 1 else 12,
            1,
        )
        csv = (
            "TP_FUNDO;CNPJ_FUNDO;DT_COMPTC;VL_TOTAL;VL_QUOTA;VL_PATRIM_LIQ;CAPTC_DIA;RESG_DIA;NR_COTST\n"
            f"FI;12345;{last_month.strftime('%Y-%m-%d')};1000;10.5;950;50;30;100\n"
        )
        zip_bytes = _make_zip_bytes(csv)

        with (
            patch("domain_cvm.ingestion.loaders_informe.download_bytes", return_value=zip_bytes),
            patch("domain_cvm.ingestion.loaders_informe.PostgresHook") as mock_hook_cls,
        ):
            mock_hook_cls.return_value = _make_hook()
            ingest_informe_mensal()

    def test_dataframe_vazio_nao_chama_insert(self) -> None:
        csv = "TP_FUNDO;CNPJ_FUNDO;DT_COMPTC\n"  # sem linhas de dados
        zip_bytes = _make_zip_bytes(csv)

        with (
            patch("domain_cvm.ingestion.loaders_informe.download_bytes", return_value=zip_bytes),
            patch("domain_cvm.ingestion.loaders_informe.PostgresHook") as mock_hook_cls,
        ):
            hook = _make_hook()
            mock_hook_cls.return_value = hook
            ingest_informe_mensal()
            hook.get_conn.assert_not_called()

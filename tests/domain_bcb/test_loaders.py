"""Unit tests para loaders.py — _upsert_dataframe e funções de ingestão.

Requer Apache Airflow instalado. Localmente: skipped automaticamente.
No container Airflow: executar com 'python -m pytest tests/ -v'.
"""
from __future__ import annotations

import pytest

# Airflow disponível apenas dentro do container Docker.
# Testes são skipped automaticamente no ambiente local.
pytest.importorskip("airflow", reason="Apache Airflow não instalado — rodar dentro do container.")

from datetime import date
from unittest.mock import MagicMock, call, patch

import pandas as pd
from airflow.exceptions import AirflowSkipException

from domain_bcb.ingestion.loaders import (
    _upsert_dataframe,
    ingest_ipca,
    ingest_ptax,
    ingest_selic,
)
from domain_bcb.ingestion.bcb_client import SERIES_CONFIG


def _make_df(series_name: str, dates: list[str], values: list[float]) -> pd.DataFrame:
    """Helper: cria DataFrame no formato retornado pelo python-bcb."""
    return pd.DataFrame(
        {series_name: values},
        index=pd.to_datetime(dates),
    )


class TestUpsertDataframe:
    """Testes para a função _upsert_dataframe."""

    def test_insere_registros_corretamente(self) -> None:
        hook = MagicMock()
        conn = MagicMock()
        hook.get_conn.return_value = conn
        config = SERIES_CONFIG["selic_daily"]
        df = _make_df("SELIC", ["2026-04-21", "2026-04-22"], [0.0435, 0.0435])

        count = _upsert_dataframe(hook, config, df)

        assert count == 2
        conn.cursor.assert_called_once()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_dataframe_vazio_retorna_zero(self) -> None:
        hook = MagicMock()
        config = SERIES_CONFIG["selic_daily"]
        df = pd.DataFrame({"SELIC": []}, index=pd.DatetimeIndex([]))

        count = _upsert_dataframe(hook, config, df)

        assert count == 0
        hook.get_conn.assert_not_called()

    def test_rollback_em_excecao(self) -> None:
        hook = MagicMock()
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value.executemany.side_effect = Exception("DB error")
        hook.get_conn.return_value = conn
        config = SERIES_CONFIG["selic_daily"]
        df = _make_df("SELIC", ["2026-04-21"], [0.0435])

        with pytest.raises(Exception, match="DB error"):
            _upsert_dataframe(hook, config, df)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_valores_nulos_sao_ignorados(self) -> None:
        hook = MagicMock()
        conn = MagicMock()
        hook.get_conn.return_value = conn
        config = SERIES_CONFIG["selic_daily"]
        df = pd.DataFrame(
            {"SELIC": [0.0435, None, 0.0435]},
            index=pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23"]),
        )

        count = _upsert_dataframe(hook, config, df)

        assert count == 2


class TestIngestFunctions:
    """Testes para as funções de ingestão públicas."""

    def _patch_ingest(self, series_key: str, load_range, df: pd.DataFrame):
        """Helper: patches comuns para _ingest_series."""
        return [
            patch("domain_bcb.ingestion.loaders.PostgresHook"),
            patch("domain_bcb.ingestion.loaders.get_load_range", return_value=load_range),
            patch("domain_bcb.ingestion.loaders.fetch_series", return_value=df),
        ]

    def test_ingest_selic_executa_sem_erro(self) -> None:
        df = _make_df("SELIC", ["2026-04-23"], [0.0435])
        conn = MagicMock()

        with patch("domain_bcb.ingestion.loaders.PostgresHook") as mock_hook_cls, \
             patch("domain_bcb.ingestion.loaders.get_load_range", return_value=(date(2026, 4, 23), date(2026, 4, 23))), \
             patch("domain_bcb.ingestion.loaders.fetch_series", return_value=df):
            mock_hook_cls.return_value.get_conn.return_value = conn
            ingest_selic()

        conn.commit.assert_called_once()

    def test_ingest_selic_skip_quando_load_range_none(self) -> None:
        with patch("domain_bcb.ingestion.loaders.PostgresHook"), \
             patch("domain_bcb.ingestion.loaders.get_load_range", return_value=None):
            with pytest.raises(AirflowSkipException):
                ingest_selic()

    def test_ingest_ipca_skip_quando_mes_gravado(self) -> None:
        with patch("domain_bcb.ingestion.loaders.PostgresHook"), \
             patch("domain_bcb.ingestion.loaders.get_load_range", return_value=None):
            with pytest.raises(AirflowSkipException):
                ingest_ipca()

    def test_ingest_ptax_executa_sem_erro(self) -> None:
        df = _make_df("PTAX", ["2026-04-23"], [5.7890])
        conn = MagicMock()

        with patch("domain_bcb.ingestion.loaders.PostgresHook") as mock_hook_cls, \
             patch("domain_bcb.ingestion.loaders.get_load_range", return_value=(date(2026, 4, 23), date(2026, 4, 23))), \
             patch("domain_bcb.ingestion.loaders.fetch_series", return_value=df):
            mock_hook_cls.return_value.get_conn.return_value = conn
            ingest_ptax()

        conn.commit.assert_called_once()

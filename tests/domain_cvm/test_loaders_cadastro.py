"""Unit tests para loaders_cadastro.py.

Requer Apache Airflow instalado. Skipped automaticamente no ambiente local.
Executar dentro do container: python -m pytest tests/ -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("airflow", reason="Apache Airflow não instalado — rodar dentro do container.")

from unittest.mock import MagicMock, patch

import pandas as pd

from domain_cvm.ingestion.loaders_cadastro import _upsert_cadastro, ingest_cadastro


def _make_hook() -> MagicMock:
    hook = MagicMock()
    conn = MagicMock()
    hook.get_conn.return_value = conn
    conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock())
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return hook


def _make_cadastro_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "cnpj_fundo":  [f"CNPJ{i:05d}" for i in range(n)],
        "denom_social": [f"Fundo {i}" for i in range(n)],
        "sit": ["EM FUNCIONAMENTO NORMAL"] * n,
    })


class TestUpsertCadastro:
    def test_chama_executemany_com_linhas_corretas(self) -> None:
        hook = _make_hook()
        df = _make_cadastro_df(2)
        _upsert_cadastro(hook, df)
        conn = hook.get_conn.return_value
        conn.cursor.assert_called_once()
        conn.commit.assert_called_once()

    def test_rollback_em_excecao(self) -> None:
        hook = _make_hook()
        conn = hook.get_conn.return_value
        conn.cursor.return_value.__enter__.return_value.executemany.side_effect = RuntimeError("DB error")
        df = _make_cadastro_df(1)
        with pytest.raises(RuntimeError, match="DB error"):
            _upsert_cadastro(hook, df)
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    def test_close_sempre_chamado(self) -> None:
        hook = _make_hook()
        df = _make_cadastro_df(1)
        _upsert_cadastro(hook, df)
        hook.get_conn.return_value.close.assert_called_once()


class TestIngestCadastro:
    def test_pipeline_completo_sem_erro(self) -> None:
        csv_bytes = (
            "CNPJ_FUNDO;DENOM_SOCIAL;SIT\n"
            "12.345/0001-90;Fundo A;EM FUNCIONAMENTO NORMAL\n"
        ).encode("latin1")

        with (
            patch("domain_cvm.ingestion.loaders_cadastro.download_bytes", return_value=csv_bytes),
            patch("domain_cvm.ingestion.loaders_cadastro.PostgresHook") as mock_hook_cls,
        ):
            mock_hook_cls.return_value = _make_hook()
            ingest_cadastro()

    def test_cnpj_invalido_descartado_sem_crash(self) -> None:
        csv_bytes = (
            "CNPJ_FUNDO;DENOM_SOCIAL\n"
            ";Fundo sem CNPJ\n"
            "12345;Fundo OK\n"
        ).encode("latin1")

        with (
            patch("domain_cvm.ingestion.loaders_cadastro.download_bytes", return_value=csv_bytes),
            patch("domain_cvm.ingestion.loaders_cadastro.PostgresHook") as mock_hook_cls,
        ):
            mock_hook_cls.return_value = _make_hook()
            ingest_cadastro()  # não deve levantar exceção

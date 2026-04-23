"""Unit tests para bcb_client.py — get_load_range e fetch_series."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from domain_bcb.ingestion.bcb_client import (
    SERIES_CONFIG,
    SeriesConfig,
    fetch_series,
    get_load_range,
)


def _make_hook(max_date: date | None) -> MagicMock:
    """Helper: cria hook mockado que retorna max_date da query MAX(date)."""
    hook = MagicMock()
    hook.get_first.return_value = (max_date,) if max_date is not None else (None,)
    return hook


class TestGetLoadRange:
    """Cenários do smart first run."""

    def test_tabela_vazia_retorna_start_date_ate_hoje(self) -> None:
        hook = _make_hook(None)
        config = SERIES_CONFIG["selic_daily"]

        result = get_load_range(config, hook)

        assert result is not None
        start, end = result
        assert start == config.start_date
        assert end == date.today()

    def test_tabela_com_dados_antigos_retorna_delta(self) -> None:
        max_date = date.today() - timedelta(days=5)
        hook = _make_hook(max_date)
        config = SERIES_CONFIG["selic_daily"]

        result = get_load_range(config, hook)

        assert result is not None
        start, end = result
        assert start == max_date + timedelta(days=1)
        assert end == date.today()

    def test_tabela_atualizada_hoje_retorna_none(self) -> None:
        hook = _make_hook(date.today())
        config = SERIES_CONFIG["selic_daily"]

        result = get_load_range(config, hook)

        assert result is None

    def test_ipca_mes_corrente_ja_gravado_retorna_none(self) -> None:
        current_month_start = date.today().replace(day=1)
        hook = _make_hook(current_month_start)
        config = SERIES_CONFIG["ipca_monthly"]

        result = get_load_range(config, hook)

        assert result is None

    def test_ipca_mes_anterior_retorna_delta(self) -> None:
        last_month = date.today().replace(day=1) - timedelta(days=1)
        last_month_start = last_month.replace(day=1)
        hook = _make_hook(last_month_start)
        config = SERIES_CONFIG["ipca_monthly"]

        result = get_load_range(config, hook)

        assert result is not None
        start, end = result
        assert start == last_month_start + timedelta(days=1)
        assert end == date.today()

    def test_ptax_tabela_vazia_retorna_start_date(self) -> None:
        hook = _make_hook(None)
        config = SERIES_CONFIG["ptax_daily"]

        result = get_load_range(config, hook)

        assert result is not None
        start, _ = result
        assert start == config.start_date


class TestFetchSeries:
    """Testes para fetch_series com mock da API BCB."""

    def test_retorna_dataframe_com_coluna_correta(self) -> None:
        mock_df = pd.DataFrame(
            {"SELIC": [0.0435, 0.0435, 0.0435]},
            index=pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23"]),
        )
        config = SERIES_CONFIG["selic_daily"]

        with patch("domain_bcb.ingestion.bcb_client.sgs.get", return_value=mock_df):
            result = fetch_series(config, date(2026, 4, 21), date(2026, 4, 23))

        assert isinstance(result, pd.DataFrame)
        assert config.value_column in result.columns
        assert len(result) == 3

    def test_retorna_dataframe_vazio_se_api_sem_dados(self) -> None:
        mock_df = pd.DataFrame({"SELIC": []}, index=pd.DatetimeIndex([]))
        config = SERIES_CONFIG["selic_daily"]

        with patch("domain_bcb.ingestion.bcb_client.sgs.get", return_value=mock_df):
            result = fetch_series(config, date(2026, 4, 21), date(2026, 4, 21))

        assert result.empty


class TestSeriesConfig:
    """Validações do SERIES_CONFIG."""

    def test_todas_as_series_presentes(self) -> None:
        assert "selic_daily" in SERIES_CONFIG
        assert "ipca_monthly" in SERIES_CONFIG
        assert "ptax_daily" in SERIES_CONFIG

    def test_ipca_frequency_eh_monthly(self) -> None:
        assert SERIES_CONFIG["ipca_monthly"].frequency == "monthly"

    def test_selic_ptax_frequency_eh_daily(self) -> None:
        assert SERIES_CONFIG["selic_daily"].frequency == "daily"
        assert SERIES_CONFIG["ptax_daily"].frequency == "daily"

    def test_start_dates_corretas(self) -> None:
        assert SERIES_CONFIG["selic_daily"].start_date == date(2000, 1, 1)
        assert SERIES_CONFIG["ipca_monthly"].start_date == date(1994, 7, 1)
        assert SERIES_CONFIG["ptax_daily"].start_date == date(1999, 1, 1)

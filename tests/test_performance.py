import logging

import pytest

from core.performance import measure_navigation, navigation_metrics_enabled


def test_navigation_metrics_are_disabled_without_explicit_development_opt_in(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RENDA_PERENE_NAVIGATION_METRICS", raising=False)

    assert navigation_metrics_enabled() is False


def test_measure_navigation_logs_technical_identifier_in_development(monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RENDA_PERENE_NAVIGATION_METRICS", "true")
    caplog.set_level(logging.DEBUG, logger="core.performance")

    with measure_navigation("ativos.carteira", "total"):
        pass

    assert "ativos.carteira.total duration:" in caplog.text


@pytest.mark.parametrize(
    ("screen", "phase"),
    [
        ("Meus Ativos", "total"),
        ("ativos.carteira", "Histórico de preços"),
        ("petr4", "total"),
    ],
)
def test_measure_navigation_rejects_ui_and_dynamic_identifiers(screen, phase):
    with pytest.raises(ValueError, match="approved technical names"):
        with measure_navigation(screen, phase):
            pass

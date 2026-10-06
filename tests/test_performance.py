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


def test_operations_reports_separate_manual_form_timings(monkeypatch, caplog):
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    from views.components.manual_entry import MarketData

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RENDA_PERENE_NAVIGATION_METRICS", "true")
    caplog.set_level(logging.DEBUG, logger="core.performance")
    monkeypatch.setattr(MarketData, "load_assets_catalog", lambda: pd.DataFrame())
    app = AppTest.from_string('''
from views.operations_view import OperationsView
OperationsView().render()
''').run(timeout=30)
    assert not app.exception
    metrics = [record.message for record in caplog.records if record.name == "core.performance"]
    for phase in ("manual_catalog", "manual_ticker_options", "manual_controls"):
        assert sum(message.startswith(f"ativos.operacoes.{phase} duration:") for message in metrics) == 1


@pytest.mark.parametrize("bound_ticker", [None, "TEST00001"])
def test_large_catalog_does_not_delay_manual_form_options(monkeypatch, caplog, bound_ticker):
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    from views.components.manual_entry import MarketData

    # Non-unique catalog codes must not turn every label lookup into a full scan.
    codes = [f"TEST{index:05d}" for index in range(10000)]
    codes.append(codes[0])
    catalog = pd.DataFrame({"NOME": ["Ativo de teste"] * len(codes)}, index=codes)
    monkeypatch.setattr(MarketData, "load_assets_catalog", lambda: catalog)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RENDA_PERENE_NAVIGATION_METRICS", "true")
    caplog.set_level(logging.DEBUG, logger="core.performance")
    app = AppTest.from_string(
        "from views.components.manual_entry import ManualEntryWidget\n"
        f"ManualEntryWidget().render({bound_ticker!r})"
    ).run(timeout=30)
    assert not app.exception
    metrics = [record.message for record in caplog.records if record.name == "core.performance"]
    duration = next(
        message for message in metrics
        if message.startswith("ativos.operacoes.manual_ticker_options duration:")
    )
    milliseconds = int(duration.rsplit(": ", 1)[1].split()[0])
    assert milliseconds < 1000, duration
    if bound_ticker is None:
        assert "TEST00001 - Ativo de teste" in app.selectbox[1].options
        assert len(app.selectbox[1].options) == 10001
    else:
        assert len(app.selectbox) == 1


def test_manual_form_keeps_first_catalog_name_for_duplicate_code(monkeypatch):
    import pandas as pd
    from streamlit.testing.v1 import AppTest
    from views.components.manual_entry import MarketData

    catalog = pd.DataFrame(
        {"NOME": ["Primeiro nome", "Outro nome", "Segundo ativo"]},
        index=["TEST3", "TEST3", "TEST4"],
    )
    monkeypatch.setattr(MarketData, "load_assets_catalog", lambda: catalog)
    app = AppTest.from_string(
        "from views.components.manual_entry import ManualEntryWidget\n"
        "ManualEntryWidget().render()"
    ).run(timeout=30)
    assert not app.exception
    assert app.selectbox[1].options == [
        "--- Selecione ---", "TEST3 - Primeiro nome", "TEST4 - Segundo ativo"
    ]


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

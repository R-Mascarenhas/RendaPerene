import datetime
from concurrent.futures import Future

import pytest
import streamlit.env_util
from streamlit.testing.v1 import AppTest

from core.dividends import DividendEvent
from services.assets_service import AssetService
from services.dividend_search_session import DividendSearchSession
from views.cached_market_data import market_data_portfolio_context


@pytest.fixture
def dividend_app(monkeypatch):
    monkeypatch.setattr(streamlit.env_util, "is_repl", lambda: False)
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", lambda ticker=None: {
        "suggestions": [{"event": event, "quantity": 100, "existing": []}],
        "unavailable": [], "changed": [], "revision": 0,
    })
    monkeypatch.setattr(AssetService, "get_local_projection_revision", lambda: 0)
    monkeypatch.setattr(
        AssetService, "prepare_dividend_search",
        lambda ticker=None: lambda: AssetService.get_dividend_suggestions(ticker),
    )
    class ImmediateExecutor:
        def submit(self, callback):
            future = Future()
            try:
                future.set_result(callback())
            except Exception as error:
                future.set_exception(error)
            return future
    calls = []
    def confirm(*args):
        calls.append(args)
        return True
    monkeypatch.setattr(AssetService, "confirm_dividend", confirm)
    app = AppTest.from_string('''
from views.components.dividend_sync import DividendSyncWidget
DividendSyncWidget().render("CMIG4")
''', default_timeout=30)
    app.session_state["dividend_search_session"] = DividendSearchSession(
        AssetService, ImmediateExecutor(), market_data_portfolio_context,
    )
    return app, calls


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_detect_and_review_do_not_save_until_user_confirms(dividend_app):
    app, calls = dividend_app
    app.run()
    button(app, "Buscar proventos no Yahoo Finance").click().run()
    assert not app.exception
    assert calls == []
    next(item for item in app.selectbox if item.label == "Tipo do provento").select("JCP")
    app.date_input[0].set_value(datetime.date(2027, 6, 30))
    button(app, "Revisar parcelas").click().run()
    assert not app.exception
    assert calls == []
    button(app, "Confirmar e salvar pagamentos").click().run()
    assert not app.exception
    assert len(calls) == 1
    assert calls[0][1] == "JCP"
    assert calls[0][2][0].date == "2027-06-30"


def test_missing_payment_date_blocks_confirmation(dividend_app):
    app, calls = dividend_app
    app.run()
    button(app, "Buscar proventos no Yahoo Finance").click().run()
    next(item for item in app.selectbox if item.label == "Tipo do provento").select("JCP")
    button(app, "Revisar parcelas").click().run()
    assert not app.exception
    assert app.error
    assert calls == []
    assert all(item.label != "Confirmar e salvar pagamentos" for item in app.button)


def test_pending_search_shows_background_status_without_a_confirmation(dividend_app):
    app, calls = dividend_app
    class PendingExecutor:
        def submit(self, callback):
            return Future()
    app.session_state["dividend_search_session"] = DividendSearchSession(
        AssetService, PendingExecutor(), market_data_portfolio_context,
    )
    app.run()
    assert not app.exception
    assert any("segundo plano" in item.value for item in app.caption)
    assert all(item.label != "Confirmar e salvar pagamentos" for item in app.button)
    assert not calls


def test_new_dividend_is_announced_without_clicking_search(dividend_app):
    app, calls = dividend_app
    app.run()
    assert not app.exception
    assert any("Foi identificado" in item.value and "CMIG4" in item.value for item in app.info)
    assert calls == []


def test_failed_automatic_search_is_visible_and_not_repeated(dividend_app, monkeypatch):
    app, _ = dividend_app
    searches = []
    def fail(ticker=None):
        searches.append(ticker)
        raise RuntimeError("Remote source unavailable")
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", fail)
    app.run()
    app.run()
    assert not app.exception
    assert searches == ["CMIG4"]
    assert any("Não foi possível verificar" in item.value for item in app.warning)


def test_provider_unavailability_is_announced_without_opening_form(dividend_app, monkeypatch):
    app, _ = dividend_app
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", lambda ticker=None: {
        "suggestions": [], "unavailable": ["CMIG4"], "changed": [], "revision": 0,
    })
    app.run()
    assert not app.exception
    assert any("indisponível para: CMIG4" in item.value for item in app.warning)


def test_unreviewed_event_is_shown_without_duplicate_label(dividend_app, monkeypatch):
    app, calls = dividend_app
    result = AssetService.get_dividend_suggestions("CMIG4")
    result["suggestions"][0]["existing"] = [{
        "id": 1, "date": "2027-06-30", "dividend_type": "JCP", "quantity": 100,
        "unit_price": 0.10, "total_value": 10,
    }]
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", lambda ticker=None: result)
    app.run()
    assert not app.exception
    assert any("Foram encontrados proventos" in item.value for item in app.warning)
    assert not app.checkbox
    assert all("possível duplicado" not in option for item in app.selectbox
               if item.label == "Provento para revisar" for option in item.options)
    assert any("já" in item.label for item in app.selectbox)
    assert calls == []


def test_detection_form_is_hidden_without_pending_events(dividend_app, monkeypatch):
    app, calls = dividend_app
    result = AssetService.get_dividend_suggestions("CMIG4")
    result["suggestions"] = []
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", lambda ticker=None: result)
    app.run()
    assert not app.exception
    assert not any("Foram encontrados proventos" in item.value for item in app.warning)
    assert not any(item.label == "Detectar proventos e informar pagamentos" for item in app.expander)
    assert calls == []


@pytest.mark.parametrize("failure", ["exception", "unavailable"])
def test_failed_search_can_be_retried_without_opening_detection_form(dividend_app, monkeypatch, failure):
    app, calls = dividend_app
    original = AssetService.get_dividend_suggestions
    searches = []

    def fail(ticker=None):
        searches.append(ticker)
        if failure == "exception":
            raise TimeoutError("unavailable")
        return {"suggestions": [], "unavailable": ["CMIG4"], "changed": [], "revision": 0}

    monkeypatch.setattr(AssetService, "get_dividend_suggestions", fail)
    app.run()
    assert not app.exception
    assert searches == ["CMIG4"]
    assert not any(item.label == "Detectar proventos e informar pagamentos" for item in app.expander)
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", original)
    button(app, "Buscar proventos no Yahoo Finance").click().run()
    assert not app.exception
    assert any("Foram encontrados proventos para CMIG4" in item.value for item in app.warning)
    assert any(item.label == "Detectar proventos e informar pagamentos" for item in app.expander)
    assert calls == []


def test_source_change_notice_is_visible_without_pending_suggestions(dividend_app, monkeypatch):
    app, calls = dividend_app
    result = AssetService.get_dividend_suggestions("CMIG4")
    result["suggestions"] = []
    result["changed"] = ["CMIG4"]
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", lambda ticker=None: result)
    app.run()
    assert not app.exception
    assert any("O Yahoo alterou valores" in item.value and "CMIG4" in item.value
               and "pagamentos confirmados foram preservados" in item.value for item in app.info)
    assert not any(item.label == "Detectar proventos e informar pagamentos" for item in app.expander)
    assert calls == []


def test_empty_search_can_be_manually_refreshed_when_source_publishes_new_event(dividend_app, monkeypatch):
    app, calls = dividend_app
    available = AssetService.get_dividend_suggestions("CMIG4")
    published = [False]
    searches = []

    def search(ticker=None):
        searches.append(ticker)
        return available if published[0] else {**available, "suggestions": []}

    monkeypatch.setattr(AssetService, "get_dividend_suggestions", search)
    app.run()
    app.run()
    assert not app.exception
    assert searches == ["CMIG4"]
    assert not any(item.label == "Detectar proventos e informar pagamentos" for item in app.expander)
    published[0] = True
    button(app, "Buscar proventos no Yahoo Finance").click().run()
    assert not app.exception
    assert searches == ["CMIG4", "CMIG4"]
    assert any("Foram encontrados proventos para CMIG4" in item.value for item in app.warning)
    assert calls == []

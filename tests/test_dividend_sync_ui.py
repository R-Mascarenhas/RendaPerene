import datetime
from concurrent.futures import Future

import pytest
import streamlit.env_util
from streamlit.testing.v1 import AppTest

from core.dividends import DividendEvent
from services.assets_service import AssetService


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
    monkeypatch.setattr(
        "views.components.dividend_sync.get_dividend_search_executor",
        lambda: ImmediateExecutor(),
    )
    calls = []
    def confirm(*args):
        calls.append(args)
        return True
    monkeypatch.setattr(AssetService, "confirm_dividend", confirm)
    app = AppTest.from_string('''
from views.components.dividend_sync import DividendSyncWidget
DividendSyncWidget().render("CMIG4")
''', default_timeout=30)
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


def test_new_dividend_is_announced_without_clicking_search(dividend_app):
    app, calls = dividend_app
    app.run()
    assert not app.exception
    assert any("Foi identificado" in item.value and "CMIG4" in item.value for item in app.info)
    assert calls == []


def test_automatic_search_is_reused_and_manual_search_refreshes(dividend_app, monkeypatch):
    app, _ = dividend_app
    original = AssetService.get_dividend_suggestions
    searches = []
    def search(ticker=None):
        searches.append(ticker)
        return original(ticker)
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", search)
    app.run()
    app.run()
    assert searches == ["CMIG4"]
    button(app, "Buscar proventos no Yahoo Finance").click().run()
    assert not app.exception
    assert searches == ["CMIG4", "CMIG4"]


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


def test_automatic_search_refreshes_after_portfolio_change(dividend_app, monkeypatch):
    app, _ = dividend_app
    revision = [0]
    original = AssetService.get_dividend_suggestions
    searches = []
    def search(ticker=None):
        searches.append(ticker)
        return {**original(ticker), "revision": revision[0]}
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", search)
    monkeypatch.setattr(AssetService, "get_local_projection_revision", lambda: revision[0])
    app.run()
    revision[0] = 1
    app.run()
    app.run()
    assert searches == ["CMIG4", "CMIG4"]
    assert not app.exception
    assert any("CMIG4" in item.value for item in app.info)


def test_automatic_search_is_isolated_between_portfolios(dividend_app, monkeypatch):
    app, _ = dividend_app
    original = AssetService.get_dividend_suggestions
    searches = []
    def search(ticker=None):
        searches.append(ticker)
        return original(ticker)
    monkeypatch.setattr(AssetService, "get_dividend_suggestions", search)
    app.session_state["active_db"] = "test_portfolio_a.db"
    app.run()
    app.session_state["active_db"] = "test_portfolio_b.db"
    app.run()
    app.run()
    assert searches == ["CMIG4", "CMIG4"]
    assert not app.exception


def test_pending_search_does_not_block_and_result_appears_when_ready(dividend_app, monkeypatch):
    app, calls = dividend_app
    future = Future()
    queued = []
    class PendingExecutor:
        def submit(self, callback):
            queued.append(callback)
            return future
    monkeypatch.setattr(
        "views.components.dividend_sync.get_dividend_search_executor",
        lambda: PendingExecutor(),
    )
    app.run()
    app.run()
    assert not app.exception
    assert len(queued) == 1
    assert not future.done()
    assert any("segundo plano" in item.value for item in app.caption)
    assert calls == []
    future.set_result(queued[0]())
    app.run()
    assert not app.exception
    assert any("Foram encontrados proventos para CMIG4" in item.value for item in app.warning)
    assert calls == []


def test_outdated_background_result_does_not_replace_current_portfolio_review(dividend_app, monkeypatch):
    app, _ = dividend_app
    revision = [0]
    futures = []
    class PendingExecutor:
        def submit(self, callback):
            future = Future()
            future.set_running_or_notify_cancel()
            futures.append(future)
            return future
    monkeypatch.setattr(AssetService, "get_local_projection_revision", lambda: revision[0])
    monkeypatch.setattr(
        "views.components.dividend_sync.get_dividend_search_executor",
        lambda: PendingExecutor(),
    )
    app.run()
    revision[0] = 1
    app.run()
    old_result = AssetService.get_dividend_suggestions("CMIG4")
    futures[0].set_result(old_result)
    app.run()
    assert len(futures) == 2
    assert not any("Foram encontrados" in item.value for item in app.warning)
    futures[1].set_result({**old_result, "revision": 1})
    app.run()
    assert not app.exception
    assert any("Foram encontrados proventos para CMIG4" in item.value for item in app.warning)


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

import threading
import datetime

import pandas as pd
import pytest

from core.market_data_cache import MarketDataCache
from core.screen_cache import ScreenCache


@pytest.fixture
def app_test_environment(monkeypatch):
    import streamlit.env_util

    # AppTest is not a REPL. Avoid its costly one-time stack scan on the WSL mount.
    monkeypatch.setattr(streamlit.env_util, "is_repl", lambda: False)


def test_cold_cache_returns_without_waiting_for_remote_source():
    started = threading.Event()
    release = threading.Event()

    def load():
        started.set()
        assert release.wait(5)
        return {"price": 25.0}

    cache = MarketDataCache(workers=1)
    try:
        result = cache.read(("quote", "TEST3"), load, ttl=600, default={})
        assert result == {}
        assert started.wait(2)
        assert cache.status(("quote", "TEST3")).updating
        release.set()
        assert cache.wait_idle(2)
        assert cache.read(("quote", "TEST3"), load, ttl=600, default={}) == {"price": 25.0}
    finally:
        release.set()
        cache.close()


def test_market_value_is_available_immediately_after_restart(tmp_path):
    path = tmp_path / "screens.db"
    cache = MarketDataCache(store=ScreenCache(path))
    try:
        assert cache.read(("quote", "TEST3"), lambda: 25.0, ttl=600, default=None) is None
        assert cache.wait_idle(2)
    finally:
        cache.close()

    calls = []
    reopened = MarketDataCache(store=ScreenCache(path))
    try:
        assert reopened.read(
            ("quote", "TEST3"), lambda: calls.append(True), ttl=600, default=None
        ) == 25.0
        assert not calls
        assert reopened.status(("quote", "TEST3")).age_seconds is not None
    finally:
        reopened.close()


def test_expired_saved_quote_is_shown_while_refresh_runs(tmp_path):
    now = [datetime.datetime(2026, 9, 29, tzinfo=datetime.timezone.utc)]
    store = ScreenCache(tmp_path / "screens.db", clock=lambda: now[0])
    assert store.put("market", ("quote", "TEST3"), 25.0, ttl=10)
    now[0] += datetime.timedelta(seconds=11)
    started = threading.Event()
    release = threading.Event()

    def load():
        started.set()
        assert release.wait(5)
        return 30.0

    cache = MarketDataCache(store=store)
    try:
        assert cache.read(("quote", "TEST3"), load, ttl=10, default=None) == 25.0
        assert started.wait(2)
        assert cache.status(("quote", "TEST3")).stale
        release.set()
        assert cache.wait_idle(2)
        assert cache.read(("quote", "TEST3"), load, ttl=10, default=None) == 30.0
    finally:
        release.set()
        cache.close()


def test_expired_cache_retains_last_value_when_refresh_fails():
    now = [0.0]
    calls = []

    def load():
        calls.append(True)
        if len(calls) > 1:
            raise TimeoutError("private provider payload")
        return {"price": 25.0}

    cache = MarketDataCache(clock=lambda: now[0])
    try:
        cache.read(("quote",), load, ttl=10, default={})
        assert cache.wait_idle(2)
        first = cache.read(("quote",), load, ttl=10, default={})
        first["price"] = 999
        now[0] = 11
        assert cache.read(("quote",), load, ttl=10, default={}) == {"price": 25.0}
        assert cache.wait_idle(2)
        assert cache.status(("quote",)).failed
        assert cache.status(("quote",)).stale
        assert cache.read(("quote",), load, ttl=10, default={}) == {"price": 25.0}
        assert len(calls) == 2
    finally:
        cache.close()


def test_duplicate_reads_and_manual_refresh_discard_old_reply():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def old_load():
        calls.append(True)
        started.set()
        assert release.wait(5)
        return 10

    cache = MarketDataCache(workers=2)
    try:
        cache.read(("quote",), old_load, ttl=10, default=None)
        assert started.wait(2)
        for _ in range(5):
            assert cache.read(("quote",), old_load, ttl=10, default=None) is None
        cache.refresh(("quote",))
        cache.read(("quote",), lambda: 20, ttl=10, default=None)
        release.set()
        assert cache.wait_idle(2)
        assert cache.read(("quote",), old_load, ttl=10, default=None) == 20
        assert len(calls) == 1
    finally:
        release.set()
        cache.close()


def test_distinct_tickers_can_load_concurrently_without_blocking_reads():
    started = [threading.Event(), threading.Event()]
    release = threading.Event()
    cache = MarketDataCache(workers=2)
    try:
        for index in range(2):
            def load(index=index):
                started[index].set()
                assert release.wait(5)
                return index + 1

            assert cache.read(("quote", index), load, ttl=10, default=None) is None
        assert all(event.wait(2) for event in started)
        release.set()
        assert cache.wait_idle(2)
    finally:
        release.set()
        cache.close()


def test_missing_quote_does_not_turn_portfolio_equity_into_a_partial_total(monkeypatch):
    from core.strings import DISPLAY_QUOTE_TODAY, DISPLAY_WEIGHT
    from core.utils.market_data import MarketData
    from services.assets_service import AssetService

    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20)
    AssetService.add_transaction("CXSE3", "2024-01-01", "BUY", 10, 10)
    monkeypatch.setattr(MarketData, "get_batch_quotes", lambda _: {"BBAS3": 30.0})
    monkeypatch.setattr(AssetService.get_default()._market_analysis_api,
                        "get_ticker_market_analysis", lambda *args, **kwargs: {})
    positions, metrics = AssetService.get_portfolio_summary_metrics(AssetService.calculate_positions())
    assert pd.isna(metrics["total_equity"])
    assert pd.isna(metrics["overall_return"])
    assert metrics["total_dividends"] == 0
    assert not metrics["market_complete"]
    display, _ = AssetService.get_detailed_holdings_dataframe(positions, 6)
    assert display.loc[display["Código"] == "CXSE3", DISPLAY_QUOTE_TODAY].iloc[0] == "N/D"
    assert set(display[DISPLAY_WEIGHT]) == {"N/D"}


def test_invalid_reply_preserves_previous_value_and_sanitizes_failure(caplog):
    cache = MarketDataCache(retry_seconds=0)
    try:
        cache.read(("quote",), lambda: 30, ttl=600, default=None, valid=lambda value: value > 0)
        assert cache.wait_idle(2)
        cache.refresh(("quote",))
        assert cache.read(("quote",), lambda: 0, ttl=600, default=None,
                          valid=lambda value: value > 0) == 30
        assert cache.wait_idle(2)
        assert cache.status(("quote",)).failed
        cache.refresh(("quote",))

        def fail():
            raise TimeoutError("PRIVATE3 secret portfolio data")

        assert cache.read(("quote",), fail, ttl=600, default=None) == 30
        assert cache.wait_idle(2)
        assert "TimeoutError" in caplog.text
        assert "PRIVATE3" not in caplog.text
        assert "secret" not in caplog.text
    finally:
        cache.close()


def test_cache_capacity_and_full_queue_do_not_block_reader():
    release = threading.Event()
    started = threading.Event()

    def load():
        started.set()
        assert release.wait(5)
        return 1

    cache = MarketDataCache(workers=1, max_pending=1, max_entries=2)
    try:
        cache.read(("quote", 0), load, ttl=600, default=None)
        assert started.wait(2)
        cache.read(("quote", 1), load, ttl=600, default=None)
        assert cache.read(("quote", 2), load, ttl=600, default=None) is None
        assert not cache.status(("quote", 0)).updating  # Evicted entry is unavailable.
        assert not cache.status(("quote", 2)).updating  # Full queue does not block.
        release.set()
        assert cache.wait_idle(2)
        cache.read(("quote", 2), load, ttl=600, default=None)
        assert cache.wait_idle(2)
        assert cache.read(("quote", 2), load, ttl=600, default=None) == 1
    finally:
        release.set()
        cache.close()


def test_bcb_failure_does_not_replace_cached_official_indicator(monkeypatch):
    import requests
    from core.background_market_data import BackgroundMarketData
    from core.utils.market_data import MarketData

    now = [0.0]

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"valor": "15.0"}]

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    cache = MarketDataCache(clock=lambda: now[0])
    market = BackgroundMarketData(MarketData, cache)
    try:
        assert market.get_current_selic() == 10.5
        assert cache.wait_idle(2)
        assert market.get_current_selic() == 15.0
        now[0] = 2592001

        def fail(*args, **kwargs):
            raise TimeoutError("private response")

        monkeypatch.setattr(requests, "get", fail)
        assert market.get_current_selic() == 15.0
        assert cache.wait_idle(2)
        assert market.get_current_selic() == 15.0
        assert market.status(("selic",)).failed
    finally:
        cache.close()


def test_dashboard_renders_local_portfolio_while_yahoo_is_blocked(monkeypatch, app_test_environment):
    from streamlit.testing.v1 import AppTest
    from core.daos.portfolio_dao import PortfolioDAO
    from core.utils.market_data import MarketData
    from services.assets_service import AssetService
    from services.market_analysis_service import MarketAnalysisService
    from services.share_quantity_goal_service import ShareQuantityGoalService
    from views.cached_market_data import StreamlitCachedMarketData
    import importlib
    importlib.import_module("views.dashboard_view")  # Preload imports outside the timed render.

    started = threading.Event()
    release = threading.Event()

    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(30)
        return {}

    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 10, 20)
    market_analysis = MarketAnalysisService(StreamlitCachedMarketData, PortfolioDAO())
    AssetService.set_adapters(
        market_data_api=StreamlitCachedMarketData,
        market_analysis_api=market_analysis,
    )
    ShareQuantityGoalService.set_adapters(market_analysis_api=market_analysis)
    monkeypatch.setattr(MarketData, "get_batch_quotes", blocked)
    monkeypatch.setattr(MarketData, "get_ticker_market_snapshot", blocked)
    try:
        app = AppTest.from_string('''
from views.dashboard_view import DashboardView
DashboardView().render()
''').run(timeout=15)
        assert not app.exception
        assert started.is_set()
        assert any(metric.value == "N/D" for metric in app.metric)
        assert any("R$ 200,00" == metric.value for metric in app.metric)
        assert len(app.dataframe) >= 1
    finally:
        release.set()


@pytest.mark.parametrize(("reply", "manual_edit"), [(1700.0, None), (None, None), (1700.0, 1650.0)])
def test_manual_minimum_wage_update_waits_for_valid_reply_before_saving(monkeypatch, reply, manual_edit, app_test_environment):
    from streamlit.testing.v1 import AppTest
    from core.constants import MW_VALUE, SESSION_MW_VALUE
    from core.strings import MSG_UPDATE_MW_BTN
    from core.utils.market_data import MarketData
    from services.planning_service import SimulationService
    from views.cached_market_data import get_background_market_data
    import importlib
    importlib.import_module("views.planning_view")
    release = threading.Event()
    started = threading.Event()

    def load(*, strict=False):
        assert strict
        started.set()
        assert release.wait(30)
        if reply is None:
            raise TimeoutError("private response")
        return reply

    monkeypatch.setattr(MarketData, "get_current_minimum_wage", load)
    SimulationService.save_configuration("1990-01-01", 65, 7, 6, 1500, 0)
    original = SimulationService.get_configuration()[MW_VALUE]
    try:
        app = AppTest.from_string('''
from core.utils.session import SessionManager
from views.planning_view import PlanningView
SessionManager.initialize()
PlanningView().render()
''').run(timeout=20)
        assert not app.exception
        button = next(button for button in app.button if button.label == MSG_UPDATE_MW_BTN)
        button.click().run(timeout=20)
        assert not app.exception
        assert started.wait(2)
        assert app.session_state[SESSION_MW_VALUE] == original
        assert SimulationService.get_configuration()[MW_VALUE] == original
        if manual_edit is not None:
            wage_input = next(element for element in app.number_input if element.label == "Salário Mínimo (R$)")
            wage_input.set_value(manual_edit).run(timeout=20)
            assert not app.exception
            assert SimulationService.get_configuration()[MW_VALUE] == manual_edit
        release.set()
        assert get_background_market_data().cache.wait_idle(2)
        app.run(timeout=20)
        assert not app.exception
        expected = manual_edit if manual_edit is not None else reply if reply is not None else original
        assert app.session_state[SESSION_MW_VALUE] == expected
        assert SimulationService.get_configuration()[MW_VALUE] == expected
        assert "market_minimum_wage_refresh" not in app.session_state
    finally:
        release.set()


def test_switching_portfolio_cancels_pending_market_ui_actions(monkeypatch):
    import streamlit as st
    from core.utils.session import SessionManager

    state = {
        "active_db": "first.db",
        "market_minimum_wage_refresh": ("first.db", 1),
        "market_data_requests": {("minimum_wage",): 1},
        "market_data_poll_ready": True,
    }
    monkeypatch.setattr(st, "session_state", state)
    assert SessionManager.switch_portfolio("second.db")
    assert state == {"active_db": "second.db"}


def test_remote_metrics_are_separate_and_do_not_identify_tickers(monkeypatch, caplog):
    import logging
    from core.background_market_data import BackgroundMarketData

    class Source:
        def get_batch_quotes(self, tickers):
            return {tickers[0]: 30.0}

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("RENDA_PERENE_NAVIGATION_METRICS", "true")
    caplog.set_level(logging.DEBUG, logger="core.performance")
    cache = MarketDataCache()
    try:
        market = BackgroundMarketData(Source(), cache)
        assert market.get_batch_quotes(["PRIVATE3"]) == {}
        assert cache.wait_idle(2)
        assert market.get_batch_quotes(["PRIVATE3"]) == {"PRIVATE3": 30.0}
        messages = [record.getMessage() for record in caplog.records if record.name == "core.performance"]
        assert len(messages) == 1
        assert messages[0].startswith("atualizacao.mercado.remote_quote duration:")
        assert "PRIVATE3" not in messages[0]
    finally:
        cache.close()

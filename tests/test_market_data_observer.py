import threading
import gc
import weakref

import pytest

from core.background_market_data import BackgroundMarketData
from core.market_data_cache import MarketDataCache
from core.market_data_observer import MarketDataObserver


@pytest.fixture
def observed_market():
    now = [0.0]
    release = threading.Event()
    calls = []

    class Source:
        def get_batch_quotes(self, tickers):
            calls.append(tickers)
            assert release.wait(5)
            return {ticker: 25.0 for ticker in tickers}

    cache = MarketDataCache(workers=1, clock=lambda: now[0])
    background = BackgroundMarketData(Source(), cache)
    observer = MarketDataObserver(background)
    try:
        yield observer, background, cache, release, now, calls
    finally:
        release.set()
        assert cache.wait_idle(5)
        cache.close()


def test_completion_before_first_poll_is_not_lost(observed_market):
    observer, _, cache, release, _, calls = observed_market
    observer.begin_run()
    assert observer.market_data.get_batch_quotes([" test3 ", "TEST3"]) == {}
    release.set()
    assert cache.wait_idle(2)
    # Reading again must not absorb the revision that the initial screen missed.
    assert observer.market_data.get_last_price("TEST3") == 25.0
    first = observer.poll()
    assert not first.changed
    assert len(first.statuses) == 1
    assert observer.poll().changed
    assert not observer.poll().changed
    assert calls == [["TEST3"]]


def test_pending_wage_survives_runs_and_is_bound_to_portfolio_generation():
    release = threading.Event()

    class Source:
        def get_current_minimum_wage(self, *, strict=False):
            assert strict
            assert release.wait(5)
            return 1700.0

    cache = MarketDataCache(workers=1)
    observer = MarketDataObserver(BackgroundMarketData(Source(), cache))
    try:
        observer.request_minimum_wage_refresh(("first.db", "generation-1"))
        assert observer.minimum_wage_pending
        assert observer.take_minimum_wage_refresh(("first.db", "generation-1")) is None
        observer.begin_run()
        assert len(observer.poll().statuses) == 1
        release.set()
        assert cache.wait_idle(2)
        assert observer.poll().changed
        result = observer.take_minimum_wage_refresh(("first.db", "generation-1"))
        assert result.value == 1700.0
        assert not result.failed
        assert not observer.minimum_wage_pending
        assert observer.take_minimum_wage_refresh(("first.db", "generation-1")) is None

        observer.request_minimum_wage_refresh(("first.db", "generation-1"))
        assert cache.wait_idle(2)
        assert observer.take_minimum_wage_refresh(("first.db", "generation-2")) is None
        assert not observer.minimum_wage_pending
    finally:
        release.set()
        assert cache.wait_idle(5)
        cache.close()


def test_new_run_and_reset_only_discard_session_observation(observed_market):
    observer, background, cache, release, _, calls = observed_market
    observer.market_data.get_last_price("TEST3")
    release.set()
    assert cache.wait_idle(2)
    other = MarketDataObserver(background)
    other.market_data.get_last_price("TEST4")
    assert cache.wait_idle(2)
    observer.begin_run()
    assert not observer.poll().statuses
    assert len(other.poll().statuses) == 1
    observer.market_data.get_last_price("TEST3")
    assert not observer.poll().changed
    assert not observer.poll().changed
    observer.reset()
    assert not observer.poll().statuses
    assert background.get_last_price("TEST3") == 25.0
    assert calls == [["TEST3"], ["TEST4"]]


def test_poll_retries_only_observed_failures_after_backoff():
    now = [0.0]
    calls = []

    class Source:
        def get_batch_quotes(self, tickers):
            ticker = tickers[0]
            calls.append(ticker)
            if len(calls) <= 2:
                raise TimeoutError("controlled failure")
            return {ticker: 30.0}

    cache = MarketDataCache(workers=1, clock=lambda: now[0])
    background = BackgroundMarketData(Source(), cache)
    observer = MarketDataObserver(background)
    try:
        observer.market_data.get_last_price("TEST3")
        background.get_last_price("TEST4")
        assert cache.wait_idle(2)
        assert observer.poll().statuses[0].failed
        now[0] = 29
        observer.poll()
        assert cache.wait_idle(2)
        assert calls == ["TEST3", "TEST4"]
        now[0] = 30
        observer.poll()
        assert cache.wait_idle(2)
        assert observer.poll().changed
        assert observer.market_data.get_last_price("TEST3") == 30.0
        assert calls == ["TEST3", "TEST4", "TEST3"]
    finally:
        cache.close()


@pytest.mark.parametrize("reply", [None, float("nan"), 0.0, 999.0, 5001.0])
def test_failed_or_out_of_range_wage_refresh_never_returns_a_value(reply):
    class Source:
        def get_current_minimum_wage(self, *, strict=False):
            assert strict
            return reply

    cache = MarketDataCache(workers=1)
    observer = MarketDataObserver(BackgroundMarketData(Source(), cache))
    try:
        observer.request_minimum_wage_refresh(("first.db", None))
        assert cache.wait_idle(2)
        result = observer.take_minimum_wage_refresh(("first.db", None))
        assert result.failed
        assert result.value is None
        assert not observer.minimum_wage_pending
    finally:
        cache.close()


@pytest.mark.parametrize("cancel", ["reset", "cancel_minimum_wage_refresh"])
def test_cancelled_action_cannot_apply_a_late_valid_reply(cancel):
    release = threading.Event()

    class Source:
        def get_current_minimum_wage(self, *, strict=False):
            assert release.wait(5)
            return 1700.0

    cache = MarketDataCache(workers=1)
    background = BackgroundMarketData(Source(), cache)
    observer = MarketDataObserver(background)
    try:
        observer.request_minimum_wage_refresh(("first.db", None))
        getattr(observer, cancel)()
        release.set()
        assert cache.wait_idle(2)
        assert observer.take_minimum_wage_refresh(("first.db", None)) is None
        assert background.get_current_minimum_wage() == 1700.0
    finally:
        release.set()
        assert cache.wait_idle(5)
        cache.close()


def test_presentation_uses_observer_without_reconstructing_request_keys(monkeypatch, observed_market):
    import streamlit as st
    import views.cached_market_data as cached

    observer, background, cache, release, _, _ = observed_market
    state = {}
    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(cached, "get_background_market_data", lambda: background)
    assert cached.StreamlitCachedMarketData.get_batch_quotes([" test3 "]) == {}
    assert cached.get_market_data_observer() is cached.get_market_data_observer()
    release.set()
    assert cache.wait_idle(2)
    ui_observer = cached.get_market_data_observer()
    assert len(ui_observer.poll().statuses) == 1
    assert ui_observer.poll().changed
    assert not observer.poll().statuses


def test_remote_cache_does_not_retain_session_observers(observed_market):
    _, background, cache, release, _, _ = observed_market
    observer = MarketDataObserver(background)
    reference = weakref.ref(observer)
    observer.market_data.get_last_price("TEST3")
    del observer
    gc.collect()
    assert reference() is None
    release.set()
    assert cache.wait_idle(2)
    assert background.get_last_price("TEST3") == 25.0


def test_all_request_types_use_the_remote_identity_and_skip_blank_tickers():
    import pandas as pd

    release = threading.Event()
    calls = []
    ui_thread = threading.get_ident()

    class Source:
        def _reply(self, request, value):
            assert threading.get_ident() != ui_thread
            calls.append(request)
            assert release.wait(5)
            return value

        def get_batch_quotes(self, tickers):
            return self._reply("quote", {tickers[0]: 25.0})

        def get_ticker_market_snapshot(self, ticker, reference_year):
            assert ticker == "TEST3"
            assert reference_year == 2026
            return self._reply("snapshot", {"current_price": 25.0})

        def get_ticker_history(self, ticker, *, period, interval):
            assert (ticker, period, interval) == ("TEST3", "2y", "1wk")
            return self._reply("history", pd.DataFrame({"Close": [25.0]}))

        def get_ticker_intraday_history(self, ticker, *, period, interval):
            assert (ticker, period, interval) == ("TEST3", "5d", "15m")
            return self._reply("intraday", pd.DataFrame({"Close": [25.0]}))

        def get_current_ipca_l12m(self, *, strict=False):
            assert strict
            return self._reply("ipca", 4.5)

        def get_current_selic(self, *, strict=False):
            assert strict
            return self._reply("selic", 10.5)

        def get_current_minimum_wage(self, *, strict=False):
            assert strict
            return self._reply("minimum_wage", 1700.0)

    cache = MarketDataCache(workers=1)
    observer = MarketDataObserver(BackgroundMarketData(Source(), cache))
    market = observer.market_data
    try:
        for ticker in [" test3 ", "TEST3", " "]:
            market.get_last_price(ticker)
            market.get_ticker_market_snapshot(ticker, 2026)
            market.get_ticker_history(ticker, "2y", "1wk")
            market.get_ticker_intraday_history(ticker, "5d", "15m")
        market.get_current_ipca_l12m()
        market.get_current_selic()
        market.get_current_minimum_wage()
        assert len(observer.poll().statuses) == 7
        release.set()
        assert cache.wait_idle(2)
        poll = observer.poll()
        assert poll.changed
        assert all(status.available for status in poll.statuses)
        assert calls == ["quote", "snapshot", "history", "intraday", "ipca", "selic", "minimum_wage"]
    finally:
        release.set()
        assert cache.wait_idle(5)
        cache.close()


def test_restoring_same_filename_cancels_wage_action_without_clearing_remote_cache(monkeypatch):
    import streamlit as st
    from core.constants import SESSION_ACTIVE_DATABASE_GENERATION
    from core.utils.session import SessionManager
    from views.cached_market_data import get_market_data_observer, market_data_portfolio_context
    from core.utils.market_data import MarketData

    calls = []
    def load(*, strict=False):
        calls.append(True)
        return 1700.0

    monkeypatch.setattr(MarketData, "get_current_minimum_wage", load)
    state = {"active_db": "first.db", SESSION_ACTIVE_DATABASE_GENERATION: "old"}
    monkeypatch.setattr(st, "session_state", state)
    observer = get_market_data_observer()
    observer.request_minimum_wage_refresh(market_data_portfolio_context())
    assert observer.market_data.cache.wait_idle(2)
    assert SessionManager.refresh_portfolio_generation("restored")
    assert not observer.minimum_wage_pending
    assert not observer.poll().statuses
    assert market_data_portfolio_context() == ("first.db", "restored")
    replacement = get_market_data_observer()
    assert replacement is not observer
    assert replacement.market_data.get_current_minimum_wage() == 1700.0
    assert calls == [True]

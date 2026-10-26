import datetime
import threading

import pandas as pd
import pytest

from core.background_market_data import BackgroundMarketData
from core.market_data_cache import MarketDataCache
from core.utils.market_data import MarketData


def _manual_screen():
    from views.components.manual_entry import ManualEntryWidget
    ManualEntryWidget().render()


@pytest.fixture
def manual_app(monkeypatch):
    import streamlit.env_util
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(streamlit.env_util, "is_repl", lambda: False)
    monkeypatch.setattr(MarketData, "get_price_on_date", lambda *args: 23.45, raising=False)
    monkeypatch.setattr("views.components.manual_entry.MarketData.load_assets_catalog", lambda: MarketData.load_assets_catalog())
    return AppTest.from_function(_manual_screen, default_timeout=30)


def _price(app):
    return next(widget for widget in app.number_input if widget.label == "Preço Unitário (R$)")


def test_manual_price_autofills_and_stays_editable(manual_app):
    from services.assets_service import AssetService
    from views.cached_market_data import get_background_market_data

    app = manual_app.run()
    assert not app.exception
    assert _price(app).value is None
    app.selectbox[1].select("BBAS3 - Banco do Brasil").run()
    assert get_background_market_data().cache.wait_idle(2)
    app.run()
    assert not app.exception
    assert _price(app).value == 23.45
    _price(app).set_value(24.0).run()
    app.run()
    assert _price(app).value == 24.0
    app.number_input[0].set_value(2)
    app.button[0].click().run()
    assert not app.exception
    transactions = AssetService.get_portfolio_activity()
    assert len(transactions) == 1
    from services.portfolio_read_service import PortfolioReadService
    saved = PortfolioReadService.read_asset("BBAS3").transaction_history.iloc[0]
    assert saved["unit_price"] == 24.0
    assert saved["quantity"] == 2
    assert _price(app).value is None


def test_manual_edit_during_lookup_survives_late_response(manual_app, monkeypatch):
    from views.cached_market_data import get_background_market_data

    release = threading.Event()
    def delayed(*args):
        assert release.wait(10)
        return 23.45
    monkeypatch.setattr(MarketData, "get_price_on_date", delayed)
    try:
        app = manual_app.run()
        app.selectbox[1].select("BBAS3 - Banco do Brasil").run()
        assert not app.exception
        assert _price(app).value is None
        _price(app).set_value(24.0).run()
        release.set()
        assert get_background_market_data().cache.wait_idle(2)
        app.run()
        assert not app.exception
        assert _price(app).value == 24.0
    finally:
        release.set()


@pytest.mark.parametrize("change", ["ticker", "date"])
def test_old_lookup_cannot_fill_new_selection(manual_app, monkeypatch, change):
    from views.cached_market_data import get_background_market_data

    day = datetime.date(2025, 3, 10)
    release = threading.Event()
    started = threading.Event()

    def lookup(ticker, selected_day):
        if (ticker, selected_day) == ("BBAS3", day):
            started.set()
            assert release.wait(10)
            return 23.45
        return 31.50

    monkeypatch.setattr(MarketData, "get_price_on_date", lookup)
    try:
        app = manual_app.run()
        app.date_input[0].set_value(day).run()
        app.selectbox[1].select("BBAS3 - Banco do Brasil").run()
        assert started.wait(2)
        _price(app).set_value(99.0).run()
        if change == "ticker":
            app.selectbox[1].select("CXSE3 - Caixa Seguridade").run()
        else:
            app.date_input[0].set_value(day + datetime.timedelta(days=1)).run()
        assert not app.exception
        assert _price(app).value != 99.0
        release.set()
        assert get_background_market_data().cache.wait_idle(2)
        app.run()
        assert not app.exception
        assert _price(app).value == 31.50
    finally:
        release.set()


@pytest.mark.parametrize("failed", [False, True])
def test_unavailable_quote_allows_manual_save_but_requires_price(manual_app, monkeypatch, failed):
    from services.assets_service import AssetService
    from services.portfolio_read_service import PortfolioReadService
    from views.cached_market_data import get_background_market_data

    def lookup(*args):
        if failed:
            raise RuntimeError("private provider details")
        return None

    monkeypatch.setattr(MarketData, "get_price_on_date", lookup)
    app = manual_app.run()
    app.selectbox[1].select("BBAS3 - Banco do Brasil").run()
    assert get_background_market_data().cache.wait_idle(2)
    app.run()
    assert not app.exception
    assert _price(app).value is None
    assert any("manualmente" in caption.value for caption in app.caption)
    assert not any("private" in caption.value for caption in app.caption)
    app.button[0].click().run()
    assert not app.exception
    assert app.error[0].value == "Informe o preço unitário antes de registrar o lançamento."
    app.run()
    assert app.error[0].value == "Informe o preço unitário antes de registrar o lançamento."
    assert AssetService.get_portfolio_activity().empty
    _price(app).set_value(25.75).run()
    app.button[0].click().run()
    assert not app.exception
    assert PortfolioReadService.read_asset("BBAS3").transaction_history.iloc[0]["unit_price"] == 25.75


def test_future_date_does_not_request_yahoo(manual_app, monkeypatch):
    calls = []
    monkeypatch.setattr(MarketData, "get_price_on_date", lambda *args: calls.append(args))
    app = manual_app.run()
    app.date_input[0].set_value(datetime.date.today() + datetime.timedelta(days=1)).run()
    app.selectbox[1].select("BBAS3 - Banco do Brasil").run()
    assert not app.exception
    assert not calls
    assert _price(app).value is None
    assert any("futuras" in caption.value for caption in app.caption)


def test_returning_to_purchase_restores_automatic_price(manual_app):
    from streamlit.testing.v1 import AppTest
    from views.cached_market_data import get_background_market_data

    app = AppTest.from_string(
        'from views.components.manual_entry import ManualEntryWidget\n'
        'ManualEntryWidget().render("BBAS3")', default_timeout=30
    ).run()
    assert get_background_market_data().cache.wait_idle(2)
    app.run()
    assert _price(app).value == 23.45
    app.selectbox[0].select("Dividendo (Recebimento)").run()
    assert not app.exception
    assert all(widget.label != "Preço Unitário (R$)" for widget in app.number_input)
    app.selectbox[0].select("Compra (Aporte)").run()
    assert not app.exception
    assert _price(app).value == 23.45


def test_sub_cent_reference_does_not_break_manual_price_input(manual_app, monkeypatch):
    from views.cached_market_data import get_background_market_data

    monkeypatch.setattr(MarketData, "get_price_on_date", lambda *args: 0.004)
    app = manual_app.run()
    app.selectbox[1].select("BBAS3 - Banco do Brasil").run()
    assert get_background_market_data().cache.wait_idle(2)
    app.run()
    assert not app.exception
    assert _price(app).value is None
    _price(app).set_value(10.5).run()
    assert not app.exception
    assert _price(app).value == 10.5


def test_date_price_uses_only_requested_day_and_unadjusted_close(mock_db, monkeypatch):
    calls = []

    class Ticker:
        def history(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                {"Close": [23.45]},
                index=pd.DatetimeIndex(["2025-03-10"], tz="America/Sao_Paulo"),
            )

    symbols = []
    monkeypatch.setattr("core.utils.market_data.yf.Ticker", lambda symbol: symbols.append(symbol) or Ticker())
    assert mock_db["original_get_price_on_date"](" bbas3 ", datetime.date(2025, 3, 10)) == 23.45
    assert symbols == ["BBAS3.SA"]
    assert calls[0]["start"] == "2025-03-10"
    assert calls[0]["end"] == "2025-03-11"
    assert calls[0]["auto_adjust"] is False


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1.0, 0.0])
def test_empty_or_invalid_close_is_not_suggested(mock_db, monkeypatch, value):
    class Ticker:
        def history(self, **kwargs):
            return pd.DataFrame({"Close": [value]}, index=pd.to_datetime(["2025-03-10"]))
    monkeypatch.setattr("core.utils.market_data.yf.Ticker", lambda symbol: Ticker())
    assert mock_db["original_get_price_on_date"]("BBAS3", datetime.date(2025, 3, 10)) is None


def test_adjacent_session_is_not_used_on_a_non_trading_day(mock_db, monkeypatch):
    class Ticker:
        def history(self, **kwargs):
            return pd.DataFrame({"Close": [23.45]}, index=pd.to_datetime(["2025-03-07"]))
    monkeypatch.setattr("core.utils.market_data.yf.Ticker", lambda symbol: Ticker())
    assert mock_db["original_get_price_on_date"]("BBAS3", datetime.date(2025, 3, 8)) is None


def test_date_price_background_read_does_not_wait_and_reuses_cache():
    release = threading.Event()
    calls = []

    class Source:
        def get_price_on_date(self, ticker, date):
            calls.append((ticker, date))
            assert release.wait(3)
            return 23.45

    cache = MarketDataCache()
    try:
        market = BackgroundMarketData(Source(), cache)
        day = datetime.date(2025, 3, 10)
        assert market.get_price_on_date(" bbas3 ", day) is None
        assert cache.status(("date_price", "BBAS3", day.isoformat())).updating
        release.set()
        assert cache.wait_idle(2)
        assert market.get_price_on_date("BBAS3", day) == 23.45
        assert calls == [("BBAS3", day)]
    finally:
        release.set()
        cache.close()

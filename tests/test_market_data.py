import datetime

import pandas as pd
import pytest
import yfinance as yf
from core.daos.portfolio_dao import PortfolioDAO
from core.database import DatabaseManager, db
from core.strings import MODEL_CLASSIC, MODEL_IPCA_SPREAD, MODEL_SELIC
from core.utils.market_data import MarketData
from services.assets_service import AssetService
from services.market_analysis_service import MarketAnalysisService


def get_market_analysis(ticker: str, target_yield_pct: float = 6.0) -> dict:
    """Exercise the portfolio-aware analysis through its public seam."""
    return MarketAnalysisService(MarketData, PortfolioDAO()).get_ticker_market_analysis(
        ticker, target_yield_pct
    )


def test_new_asset_dividend_average_uses_only_listed_years_and_zero_payment_years(
    monkeypatch,
):
    current_year = datetime.date.today().year
    listing_year = current_year - 3
    listing_timestamp = datetime.datetime(
        listing_year, 1, 2, tzinfo=datetime.timezone.utc
    ).timestamp()

    class MockTicker:
        def __init__(self, ticker_name):
            self.info = {
                "longName": "Empresa Nova S.A.",
                "firstTradeDateEpochUtc": listing_timestamp,
            }
            self.fast_info = {"lastPrice": 10.0}
            self.dividends = pd.Series(
                [1.0, 3.0],
                index=pd.to_datetime([f"{listing_year}-12-01", f"{current_year - 1}-12-01"]),
                name="Dividends",
            ).rename_axis("Date")

        def history(self, period, interval, auto_adjust):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    analysis = get_market_analysis("NEW3")

    assert analysis["dividend_average_years"] == 3
    assert analysis["dividends_5y"][current_year - 2] == 0
    assert analysis["avg_dividend_5y"] == pytest.approx(4 / 3)
    assert analysis["dividend_history_status"] == "partial"


def test_market_analysis_isolates_portfolio_corrections_while_reusing_remote_snapshot(
    monkeypatch, tmp_path
):
    """Each portfolio gets fresh corrections without invalidating the remote snapshot."""
    from views.cached_market_data import StreamlitCachedMarketData

    current_year = datetime.date.today().year
    corrected_year = current_year - 1
    remote_calls = []

    def get_remote_snapshot(ticker, reference_year):
        remote_calls.append((ticker, reference_year))
        return {
            "name": "Empresa Teste S.A.",
            "current_price": 20.0,
            "listing_year": None,
            "dividends_5y": {year: 0.0 for year in range(current_year - 5, current_year)},
            "dividends_history": {year: 0.0 for year in range(current_year - 10, current_year)},
            "annual_closing_prices": {corrected_year: 25.0},
            "dividend_events": [{"date": f"{corrected_year}-04-01", "value": 1.0}],
        }

    monkeypatch.setattr(MarketData, "get_ticker_market_snapshot", get_remote_snapshot)
    StreamlitCachedMarketData.get_ticker_market_snapshot.clear()

    first_manager = DatabaseManager(tmp_path / "first_portfolio.db")
    second_manager = DatabaseManager(tmp_path / "second_portfolio.db")
    first_manager.init_personal_db()
    second_manager.init_personal_db()
    first_corrections = PortfolioDAO(first_manager)
    second_corrections = PortfolioDAO(second_manager)
    first_corrections.insert_dividend_correction("TEST3", corrected_year, 2.5)
    second_corrections.insert_dividend_correction("TEST3", corrected_year, 5.0)

    first_analysis = MarketAnalysisService(
        StreamlitCachedMarketData, first_corrections
    ).get_ticker_market_analysis(" test3 ")
    second_analysis = MarketAnalysisService(
        StreamlitCachedMarketData, second_corrections
    ).get_ticker_market_analysis("TEST3")

    assert first_analysis["dividends_history"][corrected_year] == 2.5
    assert first_analysis["dividend_yields_history"][corrected_year] == 10.0
    assert second_analysis["dividends_history"][corrected_year] == 5.0
    assert second_analysis["dividend_yields_history"][corrected_year] == 20.0
    assert first_analysis["dividend_events"] == second_analysis["dividend_events"]
    assert remote_calls == [("TEST3", current_year)]

    first_corrections.insert_dividend_correction("TEST3", corrected_year, 3.0)
    refreshed_analysis = MarketAnalysisService(
        StreamlitCachedMarketData, first_corrections
    ).get_ticker_market_analysis("TEST3")

    assert refreshed_analysis["dividends_history"][corrected_year] == 3.0
    assert remote_calls == [("TEST3", current_year)]


def test_remote_snapshot_cache_normalizes_ticker_before_building_its_key(monkeypatch):
    """Equivalent ticker spellings must reuse the same portfolio-independent snapshot."""
    from views.cached_market_data import StreamlitCachedMarketData

    current_year = datetime.date.today().year
    remote_calls = []

    def get_remote_snapshot(ticker, reference_year):
        remote_calls.append((ticker, reference_year))
        return {"current_price": 20.0}

    monkeypatch.setattr(MarketData, "get_ticker_market_snapshot", get_remote_snapshot)
    StreamlitCachedMarketData.get_ticker_market_snapshot.clear()

    first_snapshot = StreamlitCachedMarketData.get_ticker_market_snapshot(" test3 ", current_year)
    second_snapshot = StreamlitCachedMarketData.get_ticker_market_snapshot("TEST3", current_year)

    assert first_snapshot == second_snapshot
    assert remote_calls == [("TEST3", current_year)]


def test_remote_market_snapshot_does_not_include_portfolio_corrections(monkeypatch):
    """The cacheable Yahoo payload must not contain active-portfolio state."""
    current_year = datetime.date.today().year
    dividend_year = current_year - 1

    class MockTicker:
        def __init__(self, ticker_name):
            assert ticker_name == "TEST3.SA"
            self.info = {"longName": "Empresa Teste S.A."}
            self.fast_info = {"lastPrice": 20.0}
            self.dividends = pd.Series(
                [1.5],
                index=pd.to_datetime([f"{dividend_year}-12-01"]),
                name="Dividends",
            ).rename_axis("Date")

        def history(self, period, interval, auto_adjust):
            assert (period, interval, auto_adjust) == ("10y", "1mo", False)
            return pd.DataFrame(
                {"Close": [25.0]},
                index=pd.to_datetime([f"{dividend_year}-12-30"]),
            )

    monkeypatch.setattr(yf, "Ticker", MockTicker)
    connection = db.get_personal_connection()
    connection.execute(
        "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES (?, ?, ?)",
        ("TEST3", dividend_year, 9.0),
    )
    connection.commit()
    connection.close()

    snapshot = MarketData.get_ticker_market_snapshot(" test3 ", current_year)

    assert snapshot["dividends_history"][dividend_year] == 1.5


@pytest.mark.parametrize("invalid_total", ["not-a-number", float("nan"), float("inf"), -1.0])
def test_market_analysis_maps_invalid_portfolio_correction_to_unavailable_result(
    invalid_total,
):
    """Corrupt local correction values must not leak an exception or stale remote result."""
    current_year = datetime.date.today().year
    corrected_year = current_year - 1

    class RemoteSnapshot:
        @staticmethod
        def get_ticker_market_snapshot(ticker, reference_year):
            return {
                "current_price": 20.0,
                "dividends_5y": {corrected_year: 1.0},
                "dividends_history": {corrected_year: 1.0},
                "annual_closing_prices": {corrected_year: 20.0},
            }

    class InvalidCorrections:
        @staticmethod
        def get_dividend_corrections(ticker):
            return {corrected_year: invalid_total}

    analysis = MarketAnalysisService(RemoteSnapshot, InvalidCorrections).get_ticker_market_analysis(
        "TEST3"
    )

    assert analysis == {}


def test_market_analysis_maps_invalid_ticker_snapshot_to_unavailable_result():
    """A Yahoo response without a usable quote does not represent a valid ticker analysis."""

    class InvalidTickerSnapshot:
        @staticmethod
        def get_ticker_market_snapshot(ticker, reference_year):
            return {
                "name": f"Asset {ticker}",
                "current_price": 0.0,
                "dividends_5y": {},
                "dividends_history": {},
                "annual_closing_prices": {},
            }

    class EmptyCorrections:
        @staticmethod
        def get_dividend_corrections(ticker):
            return {}

    analysis = MarketAnalysisService(
        InvalidTickerSnapshot, EmptyCorrections
    ).get_ticker_market_analysis("INVALID3")

    assert analysis == {}


def test_get_ticker_market_analysis(monkeypatch):
    """
    Verifies that get_ticker_market_analysis correctly parses and calculates market data.
    In particular, checks that the dividend yield (dy) is NOT multiplied by 100 if yfinance
    already returns it as a percentage (e.g. 1.2 for BBAS3 instead of 0.012).
    """

    class MockTicker:
        def __init__(self, ticker_name):
            self.info = {
                "longName": "Banco do Brasil S.A.",
                "priceToBook": 0.85,
                "trailingPE": 4.5,
                "dividendYield": 1.2,  # Already percentage (1.2%)
                "returnOnEquity": 0.09224,  # Decimal fraction (9.224%)
                "open": 19.5,
                "dayHigh": 20.1,
                "dayLow": 19.4,
                "marketCap": 55_000_000_000,
                "sharesOutstanding": 2_800_000_000,
                "volume": 1_500_000,
                "totalDebt": 1_000_000_000,
            }
            self.fast_info = {"yearLow": 15.0, "yearHigh": 30.0, "lastPrice": 19.86}
            self.dividends = pd.Series(dtype=float)

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # Call get_ticker_market_analysis for a mock ticker
    analysis = get_market_analysis("BBAS3")

    # Assertions
    assert analysis["name"] == "Banco do Brasil S.A."
    assert analysis["current_price"] == 19.86
    assert analysis["pb"] == 0.85
    assert analysis["pe"] == 4.5
    assert analysis["roe"] == 9.224  # Should be multiplied by 100 since ROE is a decimal fraction
    assert analysis["net_margin"] is None
    assert analysis["dy"] == 1.2  # Should be exactly 1.2, NOT 120.0
    assert analysis["quote_snapshot"]["opening_price"] == 19.5
    assert analysis["quote_snapshot"]["market_cap"] == 55_000_000_000
    assert analysis["quote_snapshot"]["daily_financial_volume"] == pytest.approx(29_790_000)
    assert analysis["indicators"]["total_debt"] == 1_000_000_000


def test_get_ticker_market_analysis_normalization(monkeypatch):
    """
    Verifies that get_ticker_market_analysis correctly normalizes the ticker parameter
    (converting to uppercase and stripping whitespace) before performing any database queries.
    """

    class MockTicker:
        def __init__(self, ticker_name):
            assert "BBAS3.SA" in ticker_name
            self.info = {
                "longName": "Banco do Brasil S.A.",
                "priceToBook": 0.85,
                "trailingPE": 4.5,
                "dividendYield": 1.2,
                "returnOnEquity": 0.09224,
            }
            self.fast_info = {"yearLow": 15.0, "yearHigh": 30.0, "lastPrice": 19.86}
            s = pd.Series({pd.Timestamp("2024-01-01"): 1.50})
            s.index.name = "Date"
            s.name = "Dividends"
            self.dividends = s

        def history(self, period, interval):
            assert period == "max"
            assert interval == "1d"
            return pd.DataFrame(
                {"Close": [20.0, 25.0]},
                index=pd.to_datetime(["2024-01-02", "2024-12-30"]),
            )

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # Pre-seed a specific correction for BBAS3 in the database
    conn = db.get_personal_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2024, 2.50)"
    )
    conn.commit()
    conn.close()

    # Call with unnormalized ticker: lowercase and with spaces
    analysis = get_market_analysis("  bbas3   ")

    # Assertions
    assert (
        analysis["dividends_5y"][2024] == 2.50
    )  # Should be the corrected value, not the yfinance one (1.50)
    assert analysis["dividend_events"] == [{"date": "2024-01-01", "value": 1.5}]


def test_market_data_bcb_indicators_sanity():
    """
    Verifies that MarketData SGS API integration methods (for IPCA and SELIC)
    compile, handle cache clearings, and return valid positive financial indicators.
    """
    MarketData.get_current_ipca_l12m.clear()
    ipca_val = MarketData.get_current_ipca_l12m()
    assert isinstance(ipca_val, float)
    assert ipca_val > 0.0

    MarketData.get_current_selic.clear()
    selic_val = MarketData.get_current_selic()
    assert isinstance(selic_val, float)
    assert selic_val > 0.0


def test_get_tracked_market_assets_includes_owned_stocks(mock_db):
    """
    Ensures get_tracked_market_assets() automatically merges manually tracked tickers
    with tickers of owned stocks (quantity > 0 and asset_type is 'Ação'),
    and supports retrieving only manually tracked assets with include_owned=False.
    """
    # 1. Add a manually tracked asset: CXSE3
    AssetService.add_tracked_market_asset("CXSE3")

    # 2. Add an owned stock: BBAS3 (Buy 10 shares)
    AssetService.add_transaction("BBAS3", "2021-12-15", "BUY", 10, 10.00)

    # 3. Check positions to confirm quantity is > 0 and type is Ação
    positions = AssetService.calculate_positions()
    assert not positions.empty
    bbas3_row = positions[positions["ticker"] == "BBAS3"]
    assert not bbas3_row.empty
    assert bbas3_row.iloc[0]["quantity"] == 10
    assert bbas3_row.iloc[0]["asset_type"] == "Ação"

    # 4. Get combined tracked assets (should have both BBAS3 and CXSE3, sorted)
    combined = AssetService.get_tracked_market_assets(include_owned=True)
    assert "BBAS3" in combined
    assert "CXSE3" in combined
    assert combined == ["BBAS3", "CXSE3"]

    # 5. Get manually tracked assets only (should have only CXSE3)
    manual_only = AssetService.get_tracked_market_assets(include_owned=False)
    assert "CXSE3" in manual_only
    assert "BBAS3" not in manual_only
    assert manual_only == ["CXSE3"]

    # 6. Add BBAS3 to manual tracking as well (so it is both manually tracked and owned)
    AssetService.add_tracked_market_asset("BBAS3")

    # With include_owned=True, it should still be listed
    combined_both = AssetService.get_tracked_market_assets(include_owned=True)
    assert "BBAS3" in combined_both
    assert "CXSE3" in combined_both

    # With include_owned=False, BBAS3 should be excluded because it is owned!
    manual_both = AssetService.get_tracked_market_assets(include_owned=False)
    assert "CXSE3" in manual_both
    assert "BBAS3" not in manual_both  # Must be excluded since it is currently owned
    assert manual_both == ["CXSE3"]


def test_streamlit_cached_market_data_delegation(monkeypatch):
    """
    Verifies that StreamlitCachedMarketData correctly delegates calls to the underlying
    pure MarketData class, ensuring the structural adapter contract is preserved.
    """
    from views.cached_market_data import StreamlitCachedMarketData

    calls = []

    def mock_get_batch_quotes(tickers):
        calls.append("get_batch_quotes")
        return {"MOCK3": 10.0}

    monkeypatch.setattr(MarketData, "get_batch_quotes", mock_get_batch_quotes)

    result = StreamlitCachedMarketData.get_batch_quotes(["MOCK3"])
    assert result == {"MOCK3": 10.0}
    assert "get_batch_quotes" in calls


def test_asset_service_returns_analysis_for_catalog_asset_without_tracking():
    """A catalog ticker can be analyzed without being owned or in the watchlist."""

    class FakeMarketData:
        @staticmethod
        def load_assets_catalog():
            return pd.DataFrame({"NOME": ["Empresa Teste"]}, index=["TEST3"])

        @staticmethod
        def get_ticker_market_analysis(ticker, target_yield_pct):
            assert ticker == "TEST3"
            assert target_yield_pct == 6.0
            return {"current_price": 10.0, "ceiling_price": 12.0}

    fake_market_data = FakeMarketData()
    analysis = AssetService(
        market_data_api=fake_market_data,
        market_analysis_api=fake_market_data,
    ).get_asset_market_analysis("test3", 6.0)

    assert analysis["current_price"] == 10.0
    assert analysis["metadata"]["name"] == "Empresa Teste"


def test_asset_service_prepares_unique_sorted_catalog_entries():
    class FakeMarketData:
        @staticmethod
        def load_assets_catalog():
            return pd.DataFrame(
                {"NOME": ["Empresa B", "Empresa A", "Empresa A duplicada"]},
                index=["BBBB3", "AAAA3", "AAAA3"],
            )

    entries = AssetService(market_data_api=FakeMarketData()).get_asset_catalog_entries()

    assert entries == [("AAAA3", "Empresa A"), ("BBBB3", "Empresa B")]


def test_asset_service_resolves_bazin_targets_with_injected_market_rates():
    class FakeMarketData:
        @staticmethod
        def get_current_selic():
            return 12.5

        @staticmethod
        def get_current_ipca_l12m():
            return 4.5

    service = AssetService(market_data_api=FakeMarketData())

    classic = service.get_bazin_target_context(MODEL_CLASSIC, classic_target_yield=6.0)
    selic = service.get_bazin_target_context(MODEL_SELIC)
    ipca = service.get_bazin_target_context(MODEL_IPCA_SPREAD, target_spread=3.0)

    assert classic == {"target_yield": 6.0, "reference_rate": None}
    assert selic == {"target_yield": 12.5, "reference_rate": 12.5}
    assert ipca == {"target_yield": 7.5, "reference_rate": 4.5}


@pytest.mark.parametrize("live_price", [None, 0.0, float("nan")])
def test_market_analysis_falls_back_to_latest_valid_close(monkeypatch, live_price):
    """Missing or invalid live quotes use the latest valid historical close."""

    class MockTicker:
        def __init__(self, ticker_name):
            assert ticker_name == "BBAS3.SA"
            self.info = {"longName": "Banco do Brasil S.A."}
            self.fast_info = {"lastPrice": live_price}
            self.dividends = pd.Series(dtype=float)

        def history(self, period, interval):
            assert period == "5d"
            assert interval == "1d"
            return pd.DataFrame(
                {"Close": [10.0, 11.0, float("nan")]},
                index=pd.to_datetime(["2026-08-20", "2026-08-21", "2026-08-22"]),
            )

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    analysis = get_market_analysis("BBAS3")

    assert analysis["current_price"] == 11.0
    assert analysis["quote_snapshot"]["closing_price"] == 11.0


def test_market_analysis_uses_annual_closes_for_historical_dividend_yields(monkeypatch):
    """Each completed year's DY uses that year's final close, not today's quote."""

    class MockTicker:
        def __init__(self, ticker_name):
            assert ticker_name == "BBAS3.SA"
            self.info = {"longName": "Banco do Brasil S.A."}
            self.fast_info = {"lastPrice": 20.0}
            self.dividends = pd.Series(
                [1.284, 2.832, 2.486],
                index=pd.to_datetime(["2025-12-01", "2024-12-01", "2023-12-01"]),
                name="Dividends",
            ).rename_axis("Date")

        def history(self, period, interval, auto_adjust):
            assert (period, interval, auto_adjust) == ("10y", "1mo", False)
            return pd.DataFrame(
                {"Close": [23.8662, 24.1443, 27.7576]},
                index=pd.to_datetime(["2025-12-30", "2024-12-30", "2023-12-28"]),
            )

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    analysis = get_market_analysis("BBAS3")

    assert analysis["dividends_history"][2024] == 2.61
    assert analysis["dividends_history"][2023] == 2.29
    assert analysis["dividend_yields_history"][2025] == pytest.approx(5.38, abs=0.01)
    assert analysis["dividend_yields_history"][2024] == pytest.approx(10.81, abs=0.01)
    assert analysis["dividend_yields_history"][2023] == pytest.approx(8.25, abs=0.01)


def test_market_analysis_uses_annual_close_for_manual_dividend_correction(monkeypatch):
    """A correction must have a historical close even when Yahoo has no dividends."""

    class MockTicker:
        def __init__(self, ticker_name):
            assert ticker_name == "BBAS3.SA"
            self.info = {"longName": "Banco do Brasil S.A."}
            self.fast_info = {"lastPrice": 20.0}
            self.dividends = pd.Series(
                dtype=float,
                index=pd.DatetimeIndex([], name="Date"),
                name="Dividends",
            )

        def history(self, period, interval, auto_adjust):
            assert (period, interval, auto_adjust) == ("10y", "1mo", False)
            return pd.DataFrame(
                {"Close": [25.0]},
                index=pd.to_datetime(["2024-12-30"]),
            )

    monkeypatch.setattr(yf, "Ticker", MockTicker)
    connection = db.get_personal_connection()
    connection.execute(
        "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES (?, ?, ?)",
        ("BBAS3", 2024, 2.5),
    )
    connection.commit()
    connection.close()

    analysis = get_market_analysis("BBAS3")

    assert analysis["dividends_history"][2024] == 2.5
    assert analysis["dividend_yields_history"][2024] == 10.0


def test_load_assets_catalog_instantiation(monkeypatch, tmp_path):
    """
    Verifies that load_assets_catalog correctly compiles and executes, avoiding
    missing 'self' positional argument TypeError by properly instantiating the DAO.
    """
    import importlib
    import sys
    import core.utils.market_data

    # Reload to get the original unpatched class
    importlib.reload(core.utils.market_data)
    OriginalMarketData = core.utils.market_data.MarketData

    catalog_path = tmp_path / "assets.csv"
    catalog_path.write_text(
        "CÓDIGO,NOME,IMAGEM,CNPJ,SETOR ECONÔMICO,SUBSETOR ,SEGMENTO / ADM / PAÍS,TIPO,SEGMENTO\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(
        OriginalMarketData,
        "resolve_catalog_path",
        staticmethod(lambda: catalog_path),
    )

    try:
        catalog = OriginalMarketData.load_assets_catalog()
        assert isinstance(catalog, pd.DataFrame)
    finally:
        importlib.reload(core.utils.market_data)

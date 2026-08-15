import pytest
import pandas as pd
import yfinance as yf
from core.utils.market_data import MarketData
from core.database import db
from services.assets_service import AssetService

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
                "returnOnEquity": 0.09224  # Decimal fraction (9.224%)
            }
            self.fast_info = {
                "yearLow": 15.0,
                "yearHigh": 30.0,
                "lastPrice": 19.86
            }
            self.dividends = pd.Series(dtype=float)

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # Call get_ticker_market_analysis for a mock ticker
    analysis = MarketData.get_ticker_market_analysis("BBAS3")

    # Assertions
    assert analysis["name"] == "Banco do Brasil S.A."
    assert analysis["current_price"] == 19.86
    assert analysis["pb"] == 0.85
    assert analysis["pe"] == 4.5
    assert analysis["roe"] == 9.224  # Should be multiplied by 100 since ROE is a decimal fraction
    assert analysis["dy"] == 1.2      # Should be exactly 1.2, NOT 120.0

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
                "returnOnEquity": 0.09224
            }
            self.fast_info = {
                "yearLow": 15.0,
                "yearHigh": 30.0,
                "lastPrice": 19.86
            }
            s = pd.Series({
                pd.Timestamp("2024-01-01"): 1.50
            })
            s.index.name = "Date"
            s.name = "Dividends"
            self.dividends = s

    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # Pre-seed a specific correction for BBAS3 in the database
    conn = db.get_personal_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2024, 2.50)")
    conn.commit()
    conn.close()

    # Clear cache to avoid hits from previous tests
    MarketData.get_ticker_market_analysis.clear()

    # Call with unnormalized ticker: lowercase and with spaces
    analysis = MarketData.get_ticker_market_analysis("  bbas3   ")

    # Assertions
    assert analysis["dividends_5y"][2024] == 2.50  # Should be the corrected value, not the yfinance one (1.50)

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
    assert "BBAS3" not in manual_both # Must be excluded since it is currently owned
    assert manual_both == ["CXSE3"]

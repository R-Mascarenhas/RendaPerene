import pandas as pd
import streamlit as st

from core.utils.market_data import MarketData


class StreamlitCachedMarketData:
    """
    Streamlit caching adapter for MarketDataPort.
    Acts as a decorator layer positioned strictly at the presentation boundary.
    Delegates implementation details to pure headless MarketData.
    """

    @staticmethod
    @st.cache_data(ttl=600)
    def get_batch_quotes(tickers: list) -> dict:
        """Fetches batch quotes from Yahoo Finance with a 10-minute cache."""
        return MarketData.get_batch_quotes(tickers)

    @staticmethod
    def get_last_price(ticker: str) -> float:
        """Returns the last closing price of a single ticker from Yahoo Finance (Not cached)."""
        return MarketData.get_last_price(ticker)

    @staticmethod
    @st.cache_data(ttl=600)
    def get_ticker_intraday_history(ticker: str, period="1d", interval="5m") -> pd.DataFrame:
        """Fetches the intraday close prices series for a specific ticker (Cached)."""
        return MarketData.get_ticker_intraday_history(ticker, period=period, interval=interval)

    @staticmethod
    @st.cache_data(ttl=3600)
    def get_ticker_history(ticker: str, period="1y", interval="1d") -> pd.DataFrame:
        """Fetches the raw historical stock price series from Yahoo Finance (Cached)."""
        return MarketData.get_ticker_history(ticker, period=period, interval=interval)

    @staticmethod
    @st.cache_data(ttl=600)
    def _get_raw_ticker_market_analysis(ticker: str) -> dict:
        """Fetches raw core B3 valuation metrics and 5-year historical dividends (Cached)."""
        return MarketData._get_raw_ticker_market_analysis(ticker)

    @staticmethod
    def get_ticker_market_analysis(ticker: str, target_yield_pct=6.0) -> dict:
        """
        Fetches core B3 valuation metrics and 5-year historical dividends, and performs Bazin ceiling calculations.
        Underlying raw fetching is cached on StreamlitCachedMarketData to avoid redundant web reloads.
        """
        ticker = ticker.strip().upper()
        raw_data = StreamlitCachedMarketData._get_raw_ticker_market_analysis(ticker)
        if not raw_data:
            return {}

        # Copy dict to avoid mutating cached object directly
        data = raw_data.copy()

        avg_dividend_5y = data["avg_dividend_5y"]
        current_price = data["current_price"]

        # Calculate dynamic Bazin ceiling price using the customized caller's yield divisor
        target_yield = target_yield_pct / 100
        ceiling_price = (avg_dividend_5y / target_yield) if target_yield > 0 else 0.0

        # Calculate dynamic real 5-year average dividend yield
        avg_dy_5y = (avg_dividend_5y / current_price * 100) if current_price > 0 else 0.0

        data["ceiling_price"] = ceiling_price
        data["avg_dy_5y"] = avg_dy_5y

        return data

    @staticmethod
    @st.cache_data
    def load_assets_catalog() -> pd.DataFrame:
        """Loads the B3 assets static catalog from assets.csv into memory RAM (Vastly faster!)."""
        return MarketData.load_assets_catalog()

    @staticmethod
    @st.cache_data(ttl=2592000)
    def get_current_ipca_l12m() -> float:
        """Dynamically fetches the official 12-month accumulated IPCA index (Cached)."""
        return MarketData.get_current_ipca_l12m()

    @staticmethod
    @st.cache_data(ttl=2592000)
    def get_current_selic() -> float:
        """Dynamically fetches the official annualized SELIC Target rate (Cached)."""
        return MarketData.get_current_selic()

    @staticmethod
    @st.cache_data(ttl=2592000)
    def get_current_minimum_wage() -> float:
        """Dynamically fetches the current Brazilian minimum wage (Cached)."""
        return MarketData.get_current_minimum_wage()


# Attach direct clear delegate function attribute for compatibility with existing tests/handlers
StreamlitCachedMarketData.get_ticker_market_analysis.clear = (
    StreamlitCachedMarketData._get_raw_ticker_market_analysis.clear
)

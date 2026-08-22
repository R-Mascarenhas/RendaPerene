import pandas as pd
import streamlit as st

from core.utils.market_data import MarketData
from services.valuation_service import ValuationService


class StreamlitCachedMarketData:
    """
    Streamlit caching adapter for MarketDataPort.
    Acts as a decorator layer positioned strictly at the presentation boundary.
    Delegates implementation details to pure headless MarketData.
    """

    RAW_ANALYSIS_CACHE_VERSION = 7

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
    def _get_raw_ticker_market_analysis(ticker: str, cache_version: int) -> dict:
        """Fetch market metrics and dividend history with a versioned 10-minute cache."""
        return MarketData._get_raw_ticker_market_analysis(ticker)

    @staticmethod
    def get_ticker_market_analysis(ticker: str, target_yield_pct=6.0) -> dict:
        """
        Fetches core B3 valuation metrics and 5-year historical dividends, and performs Bazin ceiling calculations.
        Underlying raw fetching is cached on StreamlitCachedMarketData to avoid redundant web reloads.
        """
        ticker = ticker.strip().upper()
        raw_data = StreamlitCachedMarketData._get_raw_ticker_market_analysis(
            ticker, StreamlitCachedMarketData.RAW_ANALYSIS_CACHE_VERSION
        )
        if not raw_data:
            return {}

        return ValuationService.apply_bazin_valuation(raw_data, target_yield_pct)

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

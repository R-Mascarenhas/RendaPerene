import datetime
import hashlib

import pandas as pd
import streamlit as st

from core.application_paths import ApplicationPaths
from core.database import db
from core.utils.market_data import MarketData
from services.assets_service import AssetService


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
    def get_ticker_market_snapshot(ticker: str, reference_year: int) -> dict:
        """Normalize remote inputs before consulting the portfolio-independent cache."""
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            return {}
        return StreamlitCachedMarketData._get_cached_ticker_market_snapshot(
            normalized_ticker, reference_year
        )

    @staticmethod
    @st.cache_data(ttl=600)
    def _get_cached_ticker_market_snapshot(ticker: str, reference_year: int) -> dict:
        """Cache one Yahoo snapshot by its normalized remote inputs."""
        return MarketData.get_ticker_market_snapshot(ticker, reference_year)

    @staticmethod
    @st.cache_data
    def _load_assets_catalog(catalog_path: str) -> pd.DataFrame:
        """Cache one B3 catalog using its resolved path as part of the cache key."""
        from core.daos.assets_catalog_dao import AssetsCatalogDAO

        return AssetsCatalogDAO(catalog_path).load_catalog()

    @staticmethod
    def load_assets_catalog() -> pd.DataFrame:
        """Load the B3 catalog using its current resolved path as the cache key."""
        return StreamlitCachedMarketData._load_assets_catalog(
            str(MarketData.resolve_catalog_path())
        )

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


StreamlitCachedMarketData.get_ticker_market_snapshot.clear = (
    StreamlitCachedMarketData._get_cached_ticker_market_snapshot.clear
)


class StreamlitCachedPortfolioData:
    """Cache discardable portfolio projections behind the Streamlit boundary."""

    @staticmethod
    def _context() -> tuple[str, str | None, int]:
        database_path = db.get_personal_database_path()
        portfolio_key = hashlib.sha256(str(database_path).encode()).hexdigest()
        return (
            portfolio_key,
            ApplicationPaths.database_generation(database_path),
            AssetService.get_local_projection_revision(),
        )

    @staticmethod
    @st.cache_data
    def _calculate_positions(
        portfolio_key: str,
        database_generation: str | None,
        revision: int,
        today_date: str | None,
        start_date: str | None,
    ) -> pd.DataFrame:
        del portfolio_key, database_generation, revision
        today = datetime.date.fromisoformat(today_date) if today_date else None
        return AssetService.calculate_positions(today_date=today, start_date=start_date)

    @classmethod
    def calculate_positions(cls, today_date=None, start_date=None) -> pd.DataFrame:
        portfolio_key, database_generation, revision = cls._context()
        return cls._calculate_positions(
            portfolio_key,
            database_generation,
            revision,
            str(today_date) if today_date else None,
            start_date,
        )

    @staticmethod
    @st.cache_data
    def _calculate_historical_evolution(
        portfolio_key: str,
        database_generation: str | None,
        revision: int,
        start_date: str | None,
        include_pending_costs: bool,
    ) -> pd.DataFrame:
        del portfolio_key, database_generation, revision
        return AssetService.calculate_historical_evolution(start_date, include_pending_costs)

    @classmethod
    def calculate_historical_evolution(cls, start_date=None, include_pending_costs=False):
        portfolio_key, database_generation, revision = cls._context()
        return cls._calculate_historical_evolution(
            portfolio_key, database_generation, revision, start_date, include_pending_costs
        )

    @staticmethod
    @st.cache_data
    def _get_monthly_contributions_by_year(
        portfolio_key: str, database_generation: str | None, revision: int, start_date: str | None
    ) -> pd.DataFrame:
        del portfolio_key, database_generation, revision
        return AssetService.get_monthly_contributions_by_year(start_date)

    @classmethod
    def get_monthly_contributions_by_year(cls, start_date=None) -> pd.DataFrame:
        portfolio_key, database_generation, revision = cls._context()
        return cls._get_monthly_contributions_by_year(
            portfolio_key, database_generation, revision, start_date
        )

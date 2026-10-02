import datetime
import hashlib
from pathlib import Path

import pandas as pd
import streamlit as st

from core.application_paths import ApplicationPaths
from core.background_market_data import BackgroundMarketData
from core.database import db
from core.market_data_cache import MarketDataCache
from core.screen_cache import ScreenCache
from core.utils.market_data import MarketData
from services.assets_service import AssetService

_cache_configuration: dict[str, Path | None] = {"path": None}
_PROJECTION_VERSION = 1


def configure_screen_cache(path: Path) -> None:
    """Production composition root opts into the optional disk cache."""
    _cache_configuration["path"] = Path(path)


def get_screen_cache() -> ScreenCache | None:
    path = _cache_configuration["path"]
    return ScreenCache(path) if path is not None else None


@st.cache_resource
def _background_market_data(cache_path: str | None) -> BackgroundMarketData:
    """One synchronized, bounded remote cache for this application process."""
    store = ScreenCache(Path(cache_path)) if cache_path is not None else None
    return BackgroundMarketData(MarketData, MarketDataCache(store=store))


def get_background_market_data() -> BackgroundMarketData:
    path = _cache_configuration["path"]
    return _background_market_data(str(path) if path else None)


class StreamlitCachedMarketData:
    """
    Streamlit caching adapter for MarketDataPort.
    Acts as a decorator layer positioned strictly at the presentation boundary.
    Delegates implementation details to pure headless MarketData.
    """

    @staticmethod
    def _remember(key: tuple) -> None:
        """Track revisions in the UI thread so completed work can refresh the page."""
        requests = st.session_state.setdefault("market_data_requests", {})
        requests.setdefault(key, get_background_market_data().status(key).revision)

    @staticmethod
    def get_batch_quotes(tickers: list) -> dict:
        for ticker in tickers:
            StreamlitCachedMarketData._remember(("quote", ticker.strip().upper()))
        return get_background_market_data().get_batch_quotes(tickers)

    @staticmethod
    def get_last_price(ticker: str) -> float:
        StreamlitCachedMarketData._remember(("quote", ticker.strip().upper()))
        return get_background_market_data().get_last_price(ticker)

    @staticmethod
    def get_ticker_intraday_history(ticker: str, period="1d", interval="5m") -> pd.DataFrame:
        StreamlitCachedMarketData._remember(("intraday", ticker.strip().upper(), period, interval))
        return get_background_market_data().get_ticker_intraday_history(ticker, period, interval)

    @staticmethod
    def get_ticker_history(ticker: str, period="1y", interval="1d") -> pd.DataFrame:
        StreamlitCachedMarketData._remember(("history", ticker.strip().upper(), period, interval))
        return get_background_market_data().get_ticker_history(ticker, period, interval)

    @staticmethod
    def get_ticker_market_snapshot(ticker: str, reference_year: int) -> dict:
        """Normalize remote inputs before consulting the portfolio-independent cache."""
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            return {}
        StreamlitCachedMarketData._remember(("snapshot", normalized_ticker, reference_year))
        return get_background_market_data().get_ticker_market_snapshot(
            normalized_ticker, reference_year
        )

    @staticmethod
    def prefetch_ticker_market_snapshots(tickers: list[str], reference_year: int) -> None:
        for ticker in dict.fromkeys(tickers):
            StreamlitCachedMarketData.get_ticker_market_snapshot(ticker, reference_year)

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
    def get_current_ipca_l12m() -> float:
        StreamlitCachedMarketData._remember(("ipca",))
        return get_background_market_data().get_current_ipca_l12m()

    @staticmethod
    def get_current_selic() -> float:
        StreamlitCachedMarketData._remember(("selic",))
        return get_background_market_data().get_current_selic()

    @staticmethod
    def get_current_minimum_wage() -> float:
        StreamlitCachedMarketData._remember(("minimum_wage",))
        return get_background_market_data().get_current_minimum_wage()

    @staticmethod
    def status(key: tuple):
        return get_background_market_data().status(key)

    @staticmethod
    def refresh(prefix: tuple):
        get_background_market_data().cache.refresh(prefix)

    @staticmethod
    def retry_due(keys: set[tuple] | None = None) -> int:
        return get_background_market_data().cache.retry_due(keys)


for _method, _prefix in (
    ("get_batch_quotes", "quote"),
    ("get_last_price", "quote"),
    ("get_ticker_market_snapshot", "snapshot"),
    ("get_ticker_history", "history"),
    ("get_ticker_intraday_history", "intraday"),
    ("get_current_ipca_l12m", "ipca"),
    ("get_current_selic", "selic"),
    ("get_current_minimum_wage", "minimum_wage"),
):
    getattr(StreamlitCachedMarketData, _method).clear = lambda prefix=_prefix: (
        StreamlitCachedMarketData.refresh((prefix,))
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
        portfolio_context: tuple[str, str | None, int],
        today_date: str | None,
        start_date: str | None,
        catalog_identity: tuple,
    ) -> pd.DataFrame:
        key = (_PROJECTION_VERSION, *portfolio_context, today_date, start_date, catalog_identity)
        store = get_screen_cache()
        if store is not None:
            saved = store.get("positions", key)
            if saved is not None and not saved.stale and isinstance(saved.value, pd.DataFrame):
                return saved.value
        today = datetime.date.fromisoformat(today_date)
        filters = {}
        filters["today_date"] = today
        if start_date is not None:
            filters["start_date"] = start_date
        result = AssetService.calculate_positions(**filters)
        if store is not None:
            store.put("positions", key, result, ttl=30 * 86400)
        return result

    @classmethod
    def calculate_positions(cls, today_date=None, start_date=None) -> pd.DataFrame:
        portfolio_context = cls._context()
        effective_today = today_date or datetime.date.today()
        catalog_path = Path(MarketData.resolve_catalog_path())
        try:
            catalog_stat = catalog_path.stat()
            catalog_identity = (str(catalog_path), catalog_stat.st_mtime_ns, catalog_stat.st_size)
        except OSError:
            catalog_identity = (str(catalog_path), None, None)
        return cls._calculate_positions(
            portfolio_context,
            effective_today.isoformat(),
            start_date,
            catalog_identity,
        )

    @staticmethod
    @st.cache_data
    def _calculate_historical_evolution(
        portfolio_context: tuple[str, str | None, int],
        start_date: str | None,
        include_pending_costs: bool,
        as_of_month: str,
    ) -> pd.DataFrame:
        key = (
            _PROJECTION_VERSION,
            *portfolio_context,
            start_date,
            include_pending_costs,
            as_of_month,
        )
        store = get_screen_cache()
        if store is not None:
            saved = store.get("historical_evolution", key)
            if saved is not None and not saved.stale and isinstance(saved.value, pd.DataFrame):
                return saved.value
        result = AssetService.calculate_historical_evolution(start_date, include_pending_costs)
        if store is not None:
            store.put("historical_evolution", key, result, ttl=30 * 86400)
        return result

    @classmethod
    def calculate_historical_evolution(cls, start_date=None, include_pending_costs=False):
        portfolio_context = cls._context()
        as_of_month = datetime.date.today().strftime("%Y-%m")
        return cls._calculate_historical_evolution(
            portfolio_context,
            start_date,
            include_pending_costs,
            as_of_month,
        )

    @staticmethod
    @st.cache_data
    def _get_monthly_contributions_by_year(
        portfolio_key: str, database_generation: str | None, revision: int, start_date: str | None
    ) -> pd.DataFrame:
        key = (_PROJECTION_VERSION, portfolio_key, database_generation, revision, start_date)
        store = get_screen_cache()
        if store is not None:
            saved = store.get("monthly_contributions", key)
            if saved is not None and not saved.stale and isinstance(saved.value, pd.DataFrame):
                return saved.value
        result = AssetService.get_monthly_contributions_by_year(start_date)
        if store is not None:
            store.put("monthly_contributions", key, result, ttl=30 * 86400)
        return result

    @classmethod
    def get_monthly_contributions_by_year(cls, start_date=None) -> pd.DataFrame:
        portfolio_key, database_generation, revision = cls._context()
        return cls._get_monthly_contributions_by_year(
            portfolio_key, database_generation, revision, start_date
        )

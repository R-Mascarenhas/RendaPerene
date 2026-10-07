import hashlib
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from core.application_paths import ApplicationPaths
from core.background_market_data import BackgroundMarketData
from core.constants import SESSION_ACTIVE_DATABASE_GENERATION
from core.daos.portfolio_dao import PortfolioDAO
from core.market_data_cache import MarketDataCache
from core.market_data_observer import MarketDataObserver
from core.portfolio_read import PortfolioLedger
from core.screen_cache import ScreenCache
from core.utils.market_data import MarketData

_cache_configuration: dict[str, Path | None] = {"path": None}
_PROJECTION_VERSION = 2
_OBSERVER_SESSION_KEY = "market_data_observer"


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


def get_market_data_observer() -> MarketDataObserver:
    """Keep presentation observation per session over the shared remote cache."""
    background = get_background_market_data()
    observer = st.session_state.get(_OBSERVER_SESSION_KEY)
    if observer is None or observer.market_data.cache is not background.cache:
        observer = MarketDataObserver(background)
        st.session_state[_OBSERVER_SESSION_KEY] = observer
    return observer


def reset_market_data_observer() -> None:
    observer = st.session_state.pop(_OBSERVER_SESSION_KEY, None)
    if observer is not None:
        observer.reset()


def market_data_portfolio_context() -> tuple[str, str | None]:
    """Identity for UI actions, independent of changes to the portfolio ledger."""
    return (
        st.session_state.get("active_db", "portfolio.db"),
        st.session_state.get(SESSION_ACTIVE_DATABASE_GENERATION),
    )


class StreamlitCachedMarketData:
    """
    Streamlit caching adapter for MarketDataPort.
    Acts as a decorator layer positioned strictly at the presentation boundary.
    Delegates implementation details to pure headless MarketData.
    """

    @staticmethod
    def get_batch_quotes(tickers: list) -> dict:
        return get_market_data_observer().market_data.get_batch_quotes(tickers)

    @staticmethod
    def get_last_price(ticker: str) -> float:
        return get_market_data_observer().market_data.get_last_price(ticker)

    @staticmethod
    def get_ticker_intraday_history(ticker: str, period="1d", interval="5m") -> pd.DataFrame:
        return get_market_data_observer().market_data.get_ticker_intraday_history(
            ticker, period, interval
        )

    @staticmethod
    def get_ticker_history(ticker: str, period="1y", interval="1d") -> pd.DataFrame:
        return get_market_data_observer().market_data.get_ticker_history(ticker, period, interval)

    @staticmethod
    def get_ticker_market_snapshot(ticker: str, reference_year: int) -> dict:
        return get_market_data_observer().market_data.get_ticker_market_snapshot(
            ticker, reference_year
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
        return get_market_data_observer().market_data.get_current_ipca_l12m()

    @staticmethod
    def get_current_selic() -> float:
        return get_market_data_observer().market_data.get_current_selic()

    @staticmethod
    def get_current_minimum_wage() -> float:
        return get_market_data_observer().market_data.get_current_minimum_wage()

    @staticmethod
    def refresh(prefix: tuple):
        get_background_market_data().cache.refresh(prefix)


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


class StreamlitCachedPortfolioRepository:
    """Cache only local ledger snapshots; enrich market inputs on every read."""

    def __init__(self, repository=None):
        self._repository = repository or PortfolioDAO()

    def context(self) -> tuple[str, str | None, int]:
        database_path = self._repository.db.get_personal_database_path()
        return (
            hashlib.sha256(str(database_path).encode()).hexdigest(),
            ApplicationPaths.database_generation(database_path),
            self._repository.get_local_projection_revision(),
        )

    @staticmethod
    @st.cache_data
    def _load_ledger(context, _repository):
        key = (_PROJECTION_VERSION, *context)
        store = get_screen_cache()
        if store is not None:
            saved = store.get("portfolio_ledger", key)
            if saved is not None and not saved.stale:
                try:
                    data = saved.value
                    return PortfolioLedger(
                        pd.read_json(io.StringIO(data["transactions"]), orient="table"),
                        pd.read_json(io.StringIO(data["dividends"]), orient="table"),
                        int(data["revision"]),
                    )
                except (ValueError, KeyError, TypeError):
                    pass
        ledger = _repository.load_ledger()
        if store is not None and ledger.revision == context[2]:
            store.put(
                "portfolio_ledger",
                key,
                {
                    "transactions": ledger.transactions.to_json(
                        orient="table", double_precision=15
                    ),
                    "dividends": ledger.dividends.to_json(orient="table", double_precision=15),
                    "revision": ledger.revision,
                },
                ttl=30 * 86400,
            )
        return ledger

    def load_ledger(self) -> PortfolioLedger:
        return self._load_ledger(self.context(), self._repository)


def portfolio_context() -> tuple[str, str | None, int]:
    """Public identity for widgets scoped to the active local portfolio."""
    return StreamlitCachedPortfolioRepository().context()

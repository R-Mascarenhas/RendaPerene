"""MarketDataPort adapter that never performs network I/O in the reader's thread."""

import math
from collections.abc import Callable

import pandas as pd

from core.market_data_cache import MarketDataCache, MarketDataStatus
from core.performance import measure_navigation
from core.ports import RemoteMarketDataPort

MINIMUM_WAGE_KEY = ("minimum_wage",)


def _positive(value) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


class BackgroundMarketData:
    """Normalize remote keys and keep portfolio-dependent work out of the cache."""

    def __init__(self, source: RemoteMarketDataPort, cache: MarketDataCache):
        self._source = source
        self.cache = cache
        self._observer: Callable[[tuple], None] | None = None

    def observed(self, observer: Callable[[tuple], None]) -> "BackgroundMarketData":
        """Share remote resources, notifying only in the caller's thread before reads."""
        reader = BackgroundMarketData(self._source, self.cache)
        reader._observer = observer
        return reader

    def _read(self, key, loader, ttl, default, valid):
        if self._observer is not None:
            self._observer(key)

        def measured():
            with measure_navigation("atualizacao.mercado", f"remote_{key[0]}"):
                return loader()

        return self.cache.read(key, measured, ttl=ttl, default=default, valid=valid)

    def status(self, key: tuple) -> MarketDataStatus:
        return self.cache.status(key)

    def get_batch_quotes(self, tickers: list) -> dict:
        """Share per-ticker entries across overlapping portfolios and single quotes."""
        quotes = {}
        for ticker in dict.fromkeys(tickers):
            price = self.get_last_price(ticker)
            if _positive(price):
                quotes[ticker] = price
        return quotes

    def get_last_price(self, ticker: str) -> float:
        normalized = ticker.strip().upper()
        if not normalized:
            return float("nan")
        return self._read(
            ("quote", normalized),
            lambda source=self._source: source.get_batch_quotes([normalized]).get(normalized),
            600,
            float("nan"),
            _positive,
        )

    def get_ticker_market_snapshot(self, ticker: str, reference_year: int) -> dict:
        normalized = ticker.strip().upper()
        if not normalized:
            return {}
        return self._read(
            ("snapshot", normalized, reference_year),
            lambda source=self._source: source.get_ticker_market_snapshot(
                normalized, reference_year
            ),
            600,
            {},
            lambda value: isinstance(value, dict) and _positive(value.get("current_price")),
        )

    def get_ticker_history(self, ticker: str, period="1y", interval="1d") -> pd.DataFrame:
        normalized = ticker.strip().upper()
        return (
            self._read(
                ("history", normalized, period, interval),
                lambda source=self._source: source.get_ticker_history(
                    normalized, period=period, interval=interval
                ),
                3600,
                pd.DataFrame(),
                lambda value: isinstance(value, pd.DataFrame) and not value.empty,
            )
            if normalized
            else pd.DataFrame()
        )

    def get_ticker_intraday_history(self, ticker: str, period="1d", interval="5m") -> pd.DataFrame:
        normalized = ticker.strip().upper()
        return (
            self._read(
                ("intraday", normalized, period, interval),
                lambda source=self._source: source.get_ticker_intraday_history(
                    normalized, period=period, interval=interval
                ),
                600,
                pd.DataFrame(),
                lambda value: isinstance(value, pd.DataFrame) and not value.empty,
            )
            if normalized
            else pd.DataFrame()
        )

    def _indicator(self, name, loader, fallback):
        return self._read(
            MINIMUM_WAGE_KEY if name == "minimum_wage" else (name,),
            loader,
            2592000,
            fallback,
            lambda value: math.isfinite(float(value)) and (name == "ipca" or float(value) > 0),
        )

    def get_current_ipca_l12m(self) -> float:
        return self._indicator(
            "ipca", lambda source=self._source: source.get_current_ipca_l12m(strict=True), 4.50
        )

    def get_current_selic(self) -> float:
        return self._indicator(
            "selic", lambda source=self._source: source.get_current_selic(strict=True), 10.50
        )

    def get_current_minimum_wage(self) -> float:
        return self._indicator(
            "minimum_wage",
            lambda source=self._source: source.get_current_minimum_wage(strict=True),
            1621.0,
        )

    def load_assets_catalog(self) -> pd.DataFrame:
        return self._source.load_assets_catalog()

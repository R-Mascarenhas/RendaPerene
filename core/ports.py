from typing import Protocol, Any
import pandas as pd

class PortfolioPort(Protocol):
    """Outbound Port interface defining portfolio ledger operations (DIP compliant)."""

    @staticmethod
    def get_personal_connection() -> Any:
        ...

    @staticmethod
    def find_transaction(date: str, ticker: str, transaction_type: str, quantity: int, unit_price: float, fees: float) -> bool:
        ...

    @staticmethod
    def insert_transaction(date: str, ticker: str, transaction_type: str, quantity: int, unit_price: float, fees: float) -> bool:
        ...

    @staticmethod
    def find_dividend(date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        ...

    @staticmethod
    def insert_dividend(date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        ...

    @staticmethod
    def get_quantity_on_date(ticker: str, date_str: str, conn: Any = None) -> int:
        ...

    @staticmethod
    def get_transactions_by_ticker(ticker: str) -> pd.DataFrame:
        ...

    @staticmethod
    def get_transactions_by_ticker_desc(ticker: str) -> pd.DataFrame:
        ...

    @staticmethod
    def get_dividends_by_ticker(ticker: str) -> pd.DataFrame:
        ...

    @staticmethod
    def get_years_with_dividends() -> list:
        ...

    @staticmethod
    def get_asset_years_with_dividends(ticker: str) -> list:
        ...

    @staticmethod
    def get_annual_dividend_types_sum(year: str) -> list:
        ...

    @staticmethod
    def get_asset_annual_dividend_types_sum(ticker: str, year: str) -> list:
        ...

    @staticmethod
    def get_tracked_assets() -> list:
        ...

    @staticmethod
    def insert_tracked_asset(ticker: str) -> bool:
        ...

    @staticmethod
    def delete_tracked_asset(ticker: str) -> bool:
        ...

    @staticmethod
    def insert_dividend_correction(ticker: str, year: int, total_value: float) -> bool:
        ...

    @staticmethod
    def get_dividend_corrections(ticker: str) -> dict:
        ...

    @staticmethod
    def get_all_transactions() -> pd.DataFrame:
        ...

    @staticmethod
    def get_total_dividends_by_ticker(ticker: str) -> float:
        ...

    @staticmethod
    def get_dividends_by_ticker_since_date(ticker: str, limit_date: str) -> float:
        ...

    @staticmethod
    def get_all_dividends() -> pd.DataFrame:
        ...

    @staticmethod
    def get_ytd_contributions_sum(limit_date: str) -> float:
        ...

    @staticmethod
    def get_all_buy_transactions() -> pd.DataFrame:
        ...


class AssetsCatalogPort(Protocol):
    """Outbound Port interface defining assets static catalog access (DIP compliant)."""

    @staticmethod
    def load_catalog() -> pd.DataFrame:
        ...

    @staticmethod
    def add_fallback_asset(ticker: str) -> None:
        ...


class MarketDataPort(Protocol):
    """Outbound Port interface defining market integration and quotation lookup (DIP compliant)."""

    @staticmethod
    def get_batch_quotes(tickers: list) -> dict:
        ...

    @staticmethod
    def get_last_price(ticker: str) -> float:
        ...

    @staticmethod
    def get_ticker_intraday_history(ticker: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
        ...

    @staticmethod
    def get_ticker_history(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        ...

    @staticmethod
    def get_ticker_market_analysis(ticker: str, target_yield_pct: float = 6.0) -> dict:
        ...

    @staticmethod
    def load_assets_catalog() -> pd.DataFrame:
        ...

    @staticmethod
    def get_current_ipca_l12m() -> float:
        ...

    @staticmethod
    def get_current_selic() -> float:
        ...

    @staticmethod
    def get_current_minimum_wage() -> float:
        ...

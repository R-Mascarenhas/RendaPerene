from typing import Protocol, Any
import pandas as pd

class hybridmethod:
    """Descriptor that acts as an instance method when called on an instance,
    and delegates to a default instance (class-level singleton) when called on the class.
    Perfect for keeping 100% backward compatibility in static views while enabling pure instantiable contexts.
    """
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner):
        if instance is None:
            return self.func.__get__(owner.get_default(), owner)
        return self.func.__get__(instance, owner)


class PortfolioPort(Protocol):
    """Outbound Port interface defining portfolio ledger operations (DIP compliant)."""

    def get_personal_connection(self) -> Any:
        ...

    def find_transaction(self, date: str, ticker: str, transaction_type: str, quantity: int, unit_price: float, fees: float) -> bool:
        ...

    def insert_transaction(self, date: str, ticker: str, transaction_type: str, quantity: int, unit_price: float, fees: float) -> bool:
        ...

    def find_dividend(self, date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        ...

    def insert_dividend(self, date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        ...

    def get_quantity_on_date(self, ticker: str, date_str: str, conn: Any = None) -> int:
        ...

    def get_transactions_by_ticker(self, ticker: str) -> pd.DataFrame:
        ...

    def get_transactions_by_ticker_desc(self, ticker: str) -> pd.DataFrame:
        ...

    def get_dividends_by_ticker(self, ticker: str) -> pd.DataFrame:
        ...

    def get_years_with_dividends(self) -> list:
        ...

    def get_asset_years_with_dividends(self, ticker: str) -> list:
        ...

    def get_annual_dividend_types_sum(self, year: str) -> list:
        ...

    def get_asset_annual_dividend_types_sum(self, ticker: str, year: str) -> list:
        ...

    def get_tracked_assets(self) -> list:
        ...

    def insert_tracked_asset(self, ticker: str) -> bool:
        ...

    def delete_tracked_asset(self, ticker: str) -> bool:
        ...

    def insert_dividend_correction(self, ticker: str, year: int, total_value: float) -> bool:
        ...

    def get_dividend_corrections(self, ticker: str) -> dict:
        ...

    def get_all_transactions(self) -> pd.DataFrame:
        ...

    def get_total_dividends_by_ticker(self, ticker: str) -> float:
        ...

    def get_dividends_by_ticker_since_date(self, ticker: str, limit_date: str) -> float:
        ...

    def get_all_dividends(self) -> pd.DataFrame:
        ...

    def get_ytd_contributions_sum(self, limit_date: str) -> float:
        ...

    def get_all_buy_transactions(self) -> pd.DataFrame:
        ...


class AssetsCatalogPort(Protocol):
    """Outbound Port interface defining assets static catalog access (DIP compliant)."""

    def load_catalog(self) -> pd.DataFrame:
        ...

    def add_fallback_asset(self, ticker: str) -> None:
        ...


class MarketDataPort(Protocol):
    """Outbound Port interface defining market integration and quotation lookup (DIP compliant)."""

    def get_batch_quotes(self, tickers: list) -> dict:
        ...

    def get_last_price(self, ticker: str) -> float:
        ...

    def get_ticker_intraday_history(self, ticker: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
        ...

    def get_ticker_history(self, ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        ...

    def get_ticker_market_analysis(self, ticker: str, target_yield_pct: float = 6.0) -> dict:
        ...

    def load_assets_catalog(self) -> pd.DataFrame:
        ...

    def get_current_ipca_l12m(self) -> float:
        ...

    def get_current_selic(self) -> float:
        ...

    def get_current_minimum_wage(self) -> float:
        ...


class PlanningConfigPort(Protocol):
    """Outbound Port interface defining planning configuration and persistence operations (DIP compliant)."""

    def get_configuration(self) -> dict | None:
        ...

    def save_configuration(self, birth_date: str, retirement_age: int, desired_income_mw: float,
                           annual_interest_rate: float, mw_value: float, initial_equity_input: float,
                           desired_income_type: str = "MULTIPLIER", desired_income_fixed: float = 10000.0,
                           ceiling_model_selection: str = "Bazin Clássico", bazin_target_yield: float = 6.0,
                           bazin_target_spread: float = 3.0, planning_start_date: str = None) -> None:
        ...

    def get_min_transaction_date(self) -> str:
        ...

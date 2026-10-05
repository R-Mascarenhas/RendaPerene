"""Named portfolio read results; numeric tables use core.constants column names."""

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class PortfolioLedger:
    transactions: pd.DataFrame
    dividends: pd.DataFrame
    revision: int


@dataclass(frozen=True)
class PortfolioOverview:
    positions: pd.DataFrame
    summary: dict
    holdings: pd.DataFrame
    ceilings: dict
    sectors: pd.DataFrame
    pending_tickers: tuple[str, ...]


@dataclass(frozen=True)
class AssetRead:
    ticker: str
    metadata: dict
    position: dict
    market: dict
    transactions: pd.DataFrame
    transaction_history: pd.DataFrame
    dividends: pd.DataFrame
    dividend_details: pd.DataFrame
    annual_dividends: dict[str, dict]


@dataclass(frozen=True)
class PortfolioHistory:
    evolution: pd.DataFrame
    monthly_contributions: pd.DataFrame


@dataclass(frozen=True)
class PortfolioPlanning:
    positions: pd.DataFrame
    total_invested: float
    prior_invested: float | None
    ytd_contributions: float | None
    quantities: dict[str, int] = field(default_factory=dict)
    transactions: dict[str, pd.DataFrame] = field(default_factory=dict)
    pending_tickers: tuple[str, ...] = ()

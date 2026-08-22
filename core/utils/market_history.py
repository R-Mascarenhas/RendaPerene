"""Pure transformations for historical market-price data."""

import math

import pandas as pd

MARKET_HISTORY_PERIODS = {
    "1 Dia": ("1d", "5m"),
    "5 Dias": ("5d", "30m"),
    "1 Mês": ("1mo", "1d"),
    "6 Meses": ("6mo", "1d"),
    "No Ano (YTD)": ("ytd", "1d"),
    "1 Ano": ("1y", "1d"),
    "5 Anos": ("5y", "1wk"),
    "Máximo": ("max", "1wk"),
}


def downsample_history_for_chart(history: pd.DataFrame, step: int) -> pd.DataFrame:
    """Downsample chart history while preserving its most recent row."""
    sampled_history = history.iloc[::step].copy()
    if not history.empty and (len(history) - 1) % step != 0:
        sampled_history = pd.concat([sampled_history, history.iloc[[-1]]])
    return sampled_history


def get_valid_closing_history(history: pd.DataFrame) -> pd.DataFrame:
    """Return a copy containing only rows with a numeric closing price.

    Yahoo Finance can include a final row without a close on weekends, holidays,
    or before a market session is complete. Consumers can safely use the final
    row of this result as the most recent recorded close.
    """
    if history.empty or "Close" not in history.columns:
        return pd.DataFrame()

    valid_history = history.copy()
    valid_history["Close"] = pd.to_numeric(valid_history["Close"], errors="coerce")
    valid_history = valid_history.dropna(subset=["Close"])
    return valid_history[valid_history["Close"].map(math.isfinite)]


def get_latest_valid_close(history: pd.DataFrame) -> float | None:
    """Return the latest positive finite closing price, if one is available."""
    valid_history = get_valid_closing_history(history)
    valid_history = valid_history[valid_history["Close"] > 0]
    if valid_history.empty:
        return None
    return float(valid_history["Close"].iloc[-1])


def get_annual_closing_prices(history: pd.DataFrame, years: list[int]) -> dict[int, float]:
    """Return the latest positive finite close available in each requested year."""
    valid_history = get_valid_closing_history(history)
    valid_history = valid_history[valid_history["Close"] > 0]
    if valid_history.empty:
        return {}

    valid_history = valid_history.sort_index()
    history_years = pd.to_datetime(valid_history.index, errors="coerce").year
    annual_prices = {}
    for year in years:
        year_history = valid_history[history_years == year]
        if not year_history.empty:
            annual_prices[year] = float(year_history["Close"].iloc[-1])
    return annual_prices


def get_closing_price_summary(history: pd.DataFrame) -> dict | None:
    """Return the first/last close and percentage change for valid history."""
    valid_history = get_valid_closing_history(history)
    valid_history = valid_history[valid_history["Close"] > 0]
    if valid_history.empty:
        return None

    initial_price = float(valid_history["Close"].iloc[0])
    current_price = float(valid_history["Close"].iloc[-1])
    return {
        "history": valid_history,
        "initial_price": initial_price,
        "current_price": current_price,
        "value_change": current_price - initial_price,
        "change_pct": ((current_price / initial_price) - 1) * 100,
    }

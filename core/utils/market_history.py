"""Pure transformations for historical market-price data."""

import pandas as pd


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
    return valid_history.dropna(subset=["Close"])

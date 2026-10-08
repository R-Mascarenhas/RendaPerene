"""Replaceable Yahoo provider; no portfolio state, payment guesses or zero fallbacks."""

import datetime

import pandas as pd
import yfinance as yf

from core.dividends import DividendEvent, positive_number
from core.utils.ticker import normalize_b3_ticker


class YahooDividendProvider:
    def get_events(self, ticker: str, start_date: str) -> list[DividendEvent]:
        ticker = normalize_b3_ticker(ticker)
        datetime.date.fromisoformat(start_date)
        history = yf.Ticker(f"{ticker}.SA").history(
            start=start_date,
            actions=True,
            auto_adjust=False,
            raise_errors=True,
            timeout=10,
        )
        if history.empty:
            return []
        if "Dividends" not in history:
            raise ValueError("Dividend history is unavailable")
        events = []
        for timestamp, value in history["Dividends"].items():
            if pd.isna(value) or value == 0:
                continue
            unit_value = positive_number(value)
            date = pd.Timestamp(timestamp).date().isoformat()
            events.append(DividendEvent(ticker, date, unit_value))
        return events

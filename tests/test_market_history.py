import pandas as pd
import pytest

from core.utils.market_history import (
    downsample_history_for_chart,
    get_annual_closing_prices,
    get_closing_price_summary,
    get_valid_closing_history,
)


def test_get_valid_closing_history_discards_missing_closes():
    history = pd.DataFrame({"Close": [10.0, "11.0", None, "invalid", float("inf")]})

    valid_history = get_valid_closing_history(history)

    assert valid_history["Close"].tolist() == [10.0, 11.0]
    assert valid_history["Close"].iloc[-1] == 11.0


def test_get_closing_price_summary_returns_derived_price_values():
    history = pd.DataFrame({"Close": [10.0, 11.0, None]})

    summary = get_closing_price_summary(history)

    assert summary["current_price"] == 11.0
    assert summary["value_change"] == 1.0
    assert summary["change_pct"] == pytest.approx(10.0)


def test_downsample_history_for_chart_preserves_the_latest_row():
    history = pd.DataFrame(
        {"Close": [10.0, 11.0, 12.0, 13.0, 14.0]},
        index=pd.date_range("2025-01-01", periods=5),
    )

    sampled_history = downsample_history_for_chart(history, step=3)

    assert sampled_history["Close"].tolist() == [10.0, 13.0, 14.0]


def test_get_annual_closing_prices_uses_each_years_latest_valid_close():
    history = pd.DataFrame(
        {"Close": [18.0, 23.8662, 24.0, 26.1980, 30.1333, float("nan")]},
        index=pd.to_datetime(
            [
                "2025-01-31",
                "2025-12-30",
                "2024-01-31",
                "2024-12-30",
                "2023-12-28",
                "2023-12-29",
            ]
        ),
    )

    annual_prices = get_annual_closing_prices(history, years=[2025, 2024, 2023])

    assert annual_prices == {2025: 23.8662, 2024: 26.1980, 2023: 30.1333}

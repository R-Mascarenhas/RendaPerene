import pandas as pd
import pytest

from core.utils.dividend_provider import YahooDividendProvider


def test_provider_returns_ex_dates_and_values_without_payment_or_type_guesses(monkeypatch):
    calls = []

    class FakeTicker:
        def __init__(self, ticker):
            calls.append(ticker)

        def history(self, **kwargs):
            assert kwargs["raise_errors"] is True
            return pd.DataFrame({"Dividends": [0, 0.069913]}, index=pd.to_datetime([
                "2026-09-22T10:00:00-03:00", "2026-09-23T10:00:00-03:00",
            ]))

    monkeypatch.setattr("core.utils.dividend_provider.yf.Ticker", FakeTicker)
    events = YahooDividendProvider().get_events(" cmig4 ", "2026-09-01")
    assert calls == ["CMIG4.SA"]
    assert len(events) == 1
    assert events[0].ex_date == "2026-09-23"
    assert events[0].unit_value == 0.069913


def test_provider_does_not_convert_source_failure_to_zero(monkeypatch):
    class FailingTicker:
        def __init__(self, ticker):
            pass

        def history(self, **kwargs):
            raise TimeoutError("source unavailable")

    monkeypatch.setattr("core.utils.dividend_provider.yf.Ticker", FailingTicker)
    with pytest.raises(TimeoutError):
        YahooDividendProvider().get_events("CMIG4", "2026-09-01")

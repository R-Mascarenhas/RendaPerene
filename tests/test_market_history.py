import pandas as pd

from core.utils.market_history import get_valid_closing_history


def test_get_valid_closing_history_discards_missing_closes():
    history = pd.DataFrame({"Close": [10.0, "11.0", None, "invalid"]})

    valid_history = get_valid_closing_history(history)

    assert valid_history["Close"].tolist() == [10.0, 11.0]
    assert valid_history["Close"].iloc[-1] == 11.0

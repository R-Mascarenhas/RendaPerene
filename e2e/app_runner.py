"""Run the production composition root with isolated files and external sources."""

import os
import runpy
import socket
from pathlib import Path

import pandas as pd

from core.application_paths import ApplicationPaths
from core.update_checker import UpdateChecker
from core.utils.dividend_provider import YahooDividendProvider
from core.utils.market_data import MarketData

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = Path(os.environ["RENDAPERENE_E2E_ROOT"]).resolve()

# Never discover user storage or legacy databases, including those in the checkout.
ApplicationPaths.discover = classmethod(
    lambda cls, system=None: cls(SANDBOX / "resources", SANDBOX / "data", SANDBOX / "legacy")
)


def history(*args, **kwargs):
    return pd.DataFrame({"Close": [20.0, 21.0]}, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))


# Keep caches, services, financial calculations and repositories real.
MarketData.get_batch_quotes = staticmethod(lambda tickers: dict.fromkeys(tickers, 21.0))
MarketData.get_last_price = staticmethod(lambda ticker: 21.0)
MarketData.get_price_on_date = staticmethod(lambda ticker, day: 20.0)
MarketData.get_ticker_history = staticmethod(history)
MarketData.get_ticker_intraday_history = staticmethod(history)
MarketData.get_ticker_market_snapshot = staticmethod(
    lambda ticker, reference_year: {"current_price": 21.0}
)
MarketData.get_current_ipca_l12m = staticmethod(lambda **kwargs: 4.5)
MarketData.get_current_selic = staticmethod(lambda **kwargs: 10.5)
MarketData.get_current_minimum_wage = staticmethod(lambda **kwargs: 1621.0)
YahooDividendProvider.get_events = lambda self, ticker, start_date: []
UpdateChecker._request_latest_release = staticmethod(lambda timeout: {"tag_name": "v0.0.0"})


def local_connections_only(address, *args, **kwargs):
    """Fail unexpected backend network calls instead of consulting live providers."""
    host = address[0]
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise OSError("External network is disabled in E2E tests")
    return original_connect(address, *args, **kwargs)


# Save the original once: Streamlit executes this script again on every rerun.
if not hasattr(socket, "_e2e_original_create_connection"):
    socket._e2e_original_create_connection = socket.create_connection
original_connect = socket._e2e_original_create_connection
socket.create_connection = local_connections_only

runpy.run_path(str(ROOT / "app.py"), run_name="__main__")

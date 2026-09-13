import datetime
import math

import pandas as pd
import yfinance as yf

from core.utils.market_history import get_annual_closing_prices, get_latest_valid_close


class MarketData:
    """Class responsible for integrations with market and financial APIs."""

    _catalog_path = "assets.csv"

    @classmethod
    def configure_catalog(cls, catalog_path) -> None:
        """Configure the writable catalog selected at the application composition root."""
        cls._catalog_path = catalog_path

    @classmethod
    def resolve_catalog_path(cls):
        """Resolve the catalog path for the context performing the current operation."""
        return cls._catalog_path() if callable(cls._catalog_path) else cls._catalog_path

    @staticmethod
    def _listing_year(info: dict) -> int | None:
        """Returns Yahoo's first trading year when that metadata is available."""
        for key in ("firstTradeDateEpochUtc", "firstTradeDate"):
            value = info.get(key)
            if value is None:
                continue
            try:
                timestamp = float(value)
                if timestamp > 10_000_000_000:
                    timestamp /= 1000
                return datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).year
            except (OSError, TypeError, ValueError):
                continue
        return None

    @staticmethod
    def get_batch_quotes(tickers: list) -> dict:
        """Fetches batch quotes from Yahoo Finance with a 10-minute cache."""
        quotes = {}
        for t in tickers:
            try:
                ticker_sa = f"{t.strip().upper()}.SA"
                info = yf.Ticker(ticker_sa).fast_info
                quotes[t] = info["lastPrice"]
            except Exception:
                quotes[t] = 0.0
        return quotes

    @staticmethod
    def get_last_price(ticker: str) -> float:
        """Returns the last closing price of a single ticker from Yahoo Finance."""
        try:
            ticker_sa = f"{ticker.strip().upper()}.SA"
            info = yf.Ticker(ticker_sa).fast_info
            return float(info["lastPrice"])
        except Exception:
            return 0.0

    @staticmethod
    def get_ticker_intraday_history(ticker: str, period="1d", interval="5m") -> pd.DataFrame:
        """
        Fetches the intraday close prices series for a specific ticker.
        Applies a gapless categorical time-axis transformation.
        """
        try:
            ticker_sa = f"{ticker.strip().upper()}.SA"
            history = yf.Ticker(ticker_sa).history(period=period, interval=interval)
            if history.empty:
                return pd.DataFrame()

            # Reset index and keep datetime and Close columns
            df = history.reset_index()
            time_col = "Datetime" if "Datetime" in df.columns else "Date"

            df = df[[time_col, "Close"]].rename(columns={time_col: "time", "Close": "price"})

            # Format display timestamps tightly and force categorical string index
            if interval in {"5m", "15m"}:
                df["display_time"] = df["time"].dt.strftime("%d/%m %H:%M")
            else:
                df["display_time"] = df["time"].dt.strftime("%d/%m/%Y")

            return df
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def get_ticker_history(ticker: str, period="1y", interval="1d") -> pd.DataFrame:
        """Fetches the raw historical stock price series from Yahoo Finance with a 1-hour cache."""
        try:
            ticker_sa = f"{ticker.strip().upper()}.SA"
            return yf.Ticker(ticker_sa).history(period=period, interval=interval)
        except Exception:
            return pd.DataFrame()

    @staticmethod
    def get_ticker_market_snapshot(ticker: str, reference_year: int) -> dict:
        """
        Fetch portfolio-independent B3 metrics, dividends, and annual closing prices.

        The reference year shapes the five- and ten-year windows and is therefore part
        of the remote snapshot cache key.
        """
        ticker = ticker.strip().upper()
        try:
            ticker_sa = f"{ticker}.SA"
            yt = yf.Ticker(ticker_sa)
            info = yt.info

            # 1. Fetch dynamic valuation metrics safely
            pb = info.get("priceToBook")
            pe = info.get("trailingPE")
            dy = info.get("dividendYield", 0.0) or 0.0
            roe = (
                float(info["returnOnEquity"]) * 100
                if info.get("returnOnEquity") is not None
                else None
            )
            net_margin = (
                float(info["profitMargins"]) * 100
                if info.get("profitMargins") is not None
                else None
            )

            # Use extremely reliable fast_info for prices, highs, and lows on B3
            fast = yt.fast_info
            low_52w = fast.get("yearLow", info.get("fiftyTwoWeekLow", 0.0))
            high_52w = fast.get("yearHigh", info.get("fiftyTwoWeekHigh", 0.0))
            current_price = next(
                (
                    numeric_price
                    for price in (
                        fast.get("lastPrice"),
                        info.get("currentPrice"),
                        info.get("regularMarketPrice"),
                    )
                    if (numeric_price := MarketData._positive_finite_number(price)) is not None
                ),
                None,
            )
            if current_price is None:
                fallback_history = yt.history(period="5d", interval="1d")
                current_price = get_latest_valid_close(fallback_history) or 0.0
            daily_volume = info.get("volume", info.get("regularMarketVolume"))
            try:
                daily_financial_volume = float(daily_volume) * float(current_price)
            except (TypeError, ValueError):
                daily_financial_volume = None
            quote_snapshot = {
                "closing_price": current_price,
                "opening_price": info.get("open", info.get("regularMarketOpen")),
                "day_high": info.get("dayHigh", info.get("regularMarketDayHigh")),
                "day_low": info.get("dayLow", info.get("regularMarketDayLow")),
                "high_52w": high_52w,
                "low_52w": low_52w,
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "daily_volume": daily_volume,
                "daily_financial_volume": daily_financial_volume,
                "ibov_participation": None,
            }
            indicators = {
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "enterprise_to_ebitda": info.get("enterpriseToEbitda"),
                "enterprise_to_revenue": info.get("enterpriseToRevenue"),
                "total_cash": info.get("totalCash"),
                "total_debt": info.get("totalDebt"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "quick_ratio": info.get("quickRatio"),
                "operating_cashflow": info.get("operatingCashflow"),
                "free_cashflow": info.get("freeCashflow"),
                "return_on_assets": info.get("returnOnAssets"),
                "return_on_equity": info.get("returnOnEquity"),
                "gross_margins": info.get("grossMargins"),
                "operating_margins": info.get("operatingMargins"),
                "profit_margins": info.get("profitMargins"),
                "revenue_per_share": info.get("revenuePerShare"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
                "dividend_rate": info.get("dividendRate"),
                "dividend_yield": info.get("dividendYield"),
                "payout_ratio": info.get("payoutRatio"),
                "five_year_avg_dividend_yield": info.get("fiveYearAvgDividendYield"),
                "volume": daily_volume,
                "average_volume": info.get("averageVolume"),
                "average_volume_10d": info.get("averageDailyVolume10Day"),
                "beta": info.get("beta"),
                "fifty_two_week_change": info.get("52WeekChange"),
                "benchmark_fifty_two_week_change": info.get("SandP52WeekChange"),
            }

            # 2. Fetch five-year Bazin data and ten-year dividend history
            div_series = yt.dividends
            div_by_year = {}
            dividends_history = {}
            annual_closing_prices = {}
            dividend_events = []
            current_year = reference_year
            listing_year = MarketData._listing_year(info)
            history_listing_year = None
            last_5_years = [current_year - i for i in range(1, 6)]
            last_10_years = [current_year - i for i in range(1, 11)]

            if not div_series.empty:
                df_div = div_series.to_frame().reset_index()
                df_div["year"] = df_div["Date"].dt.year
                df_annual = df_div.groupby("year")["Dividends"].sum()

                event_start_year = current_year - 10
                for _, event in df_div[df_div["year"] >= event_start_year].iterrows():
                    dividend_events.append(
                        {
                            "date": event["Date"].strftime("%Y-%m-%d"),
                            "value": float(event["Dividends"]),
                        }
                    )

                for yr in last_5_years:
                    div_by_year[yr] = float(df_annual.get(yr, 0.0))
                for yr in last_10_years:
                    dividends_history[yr] = float(df_annual.get(yr, 0.0))

            else:
                for yr in last_5_years:
                    div_by_year[yr] = 0.0
                for yr in last_10_years:
                    dividends_history[yr] = 0.0

            try:
                annual_price_history = yt.history(period="10y", interval="1mo", auto_adjust=False)
                annual_closing_prices = get_annual_closing_prices(
                    annual_price_history, last_10_years
                )
                if not annual_price_history.empty:
                    history_listing_year = int(annual_price_history.index.min().year)
            except Exception:
                annual_closing_prices = {}
            return {
                "name": info.get("longName", f"Asset {ticker}"),
                "current_price": current_price,
                "pb": pb,
                "pe": pe,
                "dy": dy,
                "roe": roe,
                "net_margin": net_margin,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "quote_snapshot": quote_snapshot,
                "indicators": indicators,
                "dividends_5y": div_by_year,
                "dividends_history": dividends_history,
                "annual_closing_prices": annual_closing_prices,
                "dividend_events": dividend_events,
                "listing_year": listing_year,
                "history_listing_year": history_listing_year,
            }
        except Exception:
            return {}

    @staticmethod
    def _positive_finite_number(value) -> float | None:
        """Return a positive finite float or None for unusable market values."""
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value):
            return None
        return numeric_value if numeric_value > 0 else None

    @staticmethod
    def load_assets_catalog():
        """Loads the B3 assets static catalog from assets.csv into memory RAM (Vastly faster!)."""
        from core.daos.assets_catalog_dao import AssetsCatalogDAO

        return AssetsCatalogDAO(MarketData.resolve_catalog_path()).load_catalog()

    @staticmethod
    def get_current_ipca_l12m() -> float:
        """Dynamically fetches the official 12-month accumulated IPCA index from the Banco Central (BCB) SGS API Series 13522."""
        import requests

        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if data and len(data) > 0 and "valor" in data[0]:
                return float(data[0]["valor"])
        except Exception:
            pass
        return 4.50  # Highly realistic Brazilian fallback IPCA proxy if the BCB API is temporarily down

    @staticmethod
    def get_current_selic() -> float:
        """Dynamically fetches the official annualized SELIC Target rate from the Banco Central (BCB) SGS API Series 1178."""
        import requests

        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1178/dados/ultimos/1?formato=json"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if data and len(data) > 0 and "valor" in data[0]:
                return float(data[0]["valor"])
        except Exception:
            pass
        return 10.50  # Highly realistic Brazilian fallback SELIC proxy if the BCB API is temporarily down

    @staticmethod
    def get_current_minimum_wage() -> float:
        """Dynamically fetches the current Brazilian minimum wage from the Banco Central (BCB) API Series 1619."""
        import requests

        url = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1619/dados/ultimos/1?formato=json"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if data and len(data) > 0 and "valor" in data[0]:
                return float(data[0]["valor"])
        except Exception:
            pass
        return 1621.0


# Attach direct clear dummy functions for backwards compatibility in headless environments
MarketData.get_current_ipca_l12m.clear = lambda: None
MarketData.get_current_selic.clear = lambda: None
MarketData.get_current_minimum_wage.clear = lambda: None
MarketData.get_batch_quotes.clear = lambda: None
MarketData.get_ticker_intraday_history.clear = lambda: None
MarketData.get_ticker_history.clear = lambda: None

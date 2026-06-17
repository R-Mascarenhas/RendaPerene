import streamlit as st
import yfinance as yf
import datetime
import os
import pandas as pd

YAHOO_DIVIDEND_CORRECTIONS = {
    "BBAS3": {
        2023: 2.29,  # Corrects Yahoo's omission of November 2023 JCP
        2024: 2.61   # Corrects Yahoo's omission of November 2024 JCP
    }
}

class MarketData:
    """Class responsible for integrations with market and financial APIs."""

    @staticmethod
    @st.cache_data(ttl=600)
    def get_batch_quotes(tickers: list) -> dict:
        """Fetches batch quotes from Yahoo Finance with a 10-minute cache."""
        quotes = {}
        for t in tickers:
            try:
                ticker_sa = f"{t.strip().upper()}.SA"
                info = yf.Ticker(ticker_sa).fast_info
                quotes[t] = info['lastPrice']
            except Exception:
                quotes[t] = 0.0
        return quotes

    @staticmethod
    @st.cache_data(ttl=3600)
    def get_ticker_details(ticker: str) -> dict:
        """Fetches advanced real-time metrics and historical data for a ticker from Yahoo Finance."""
        ticker_sa = f"{ticker.strip().upper()}.SA"
        try:
            t = yf.Ticker(ticker_sa)
            info = t.info
            history = t.history(period="1y")

            return {
                "current_price": info.get("currentPrice", info.get("lastPrice", info.get("regularMarketPrice", 0.0))),
                "dy": info.get("dividendYield", 0.0) * 100 if info.get("dividendYield") is not None else 0.0,
                "pe": info.get("trailingPE", 0.0) if info.get("trailingPE") is not None else 0.0,
                "pb": info.get("priceToBook", 0.0) if info.get("priceToBook") is not None else 0.0,
                "high_52w": info.get("fiftyTwoWeekHigh", 0.0) if info.get("fiftyTwoWeekHigh") is not None else 0.0,
                "low_52w": info.get("fiftyTwoWeekLow", 0.0) if info.get("fiftyTwoWeekLow") is not None else 0.0,
                "history": history
            }
        except Exception:
            return {}

    @staticmethod
    @st.cache_data(ttl=2592000) # Cache for 30 days
    def get_current_minimum_wage() -> float:
        """Dynamically fetches the current Brazilian minimum wage from the Banco Central (BCB) API."""
        import requests
        url = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs.1619/dados/ultimos/1?formato=json'
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if data and len(data) > 0 and 'valor' in data[0]:
                return float(data[0]['valor'])
        except Exception:
            pass
        return 1621.0

    @staticmethod
    @st.cache_data(ttl=3600)
    def get_ticker_market_analysis(ticker: str, target_yield_pct: float = 6.0) -> dict:
        """Fetches comprehensive market metrics, last 5y dividends, and computes Bazin's Ceiling Price."""
        ticker_sa = f"{ticker.strip().upper()}.SA"
        try:
            t = yf.Ticker(ticker_sa)
            info = t.info

            current_price = info.get("currentPrice", info.get("lastPrice", info.get("regularMarketPrice", 0.0)))
            vpa = info.get("bookValue", 0.0)
            pb = info.get("priceToBook", 0.0)
            pe = info.get("trailingPE", 0.0)
            dy = info.get("dividendYield", 0.0) * 100 if info.get("dividendYield") is not None else 0.0
            roe = info.get("returnOnEquity", 0.0) * 100 if info.get("returnOnEquity") is not None else 0.0
            high_52w = info.get("fiftyTwoWeekHigh", 0.0)
            low_52w = info.get("fiftyTwoWeekLow", 0.0)
            name = info.get("longName", info.get("shortName", ticker))

            div_series = t.dividends
            current_year = datetime.date.today().year
            last_5_years = [current_year - i for i in range(1, 6)]

            div_by_year = {}
            ticker_clean = ticker.strip().upper()

            if not div_series.empty:
                div_df = div_series.groupby(div_series.index.year).sum()
                for yr in last_5_years:
                    val = float(div_df.get(yr, 0.0))
                    if ticker_clean in YAHOO_DIVIDEND_CORRECTIONS and yr in YAHOO_DIVIDEND_CORRECTIONS[ticker_clean]:
                        val = YAHOO_DIVIDEND_CORRECTIONS[ticker_clean][yr]
                    div_by_year[yr] = val
            else:
                for yr in last_5_years:
                    val = 0.0
                    if ticker_clean in YAHOO_DIVIDEND_CORRECTIONS and yr in YAHOO_DIVIDEND_CORRECTIONS[ticker_clean]:
                        val = YAHOO_DIVIDEND_CORRECTIONS[ticker_clean][yr]
                    div_by_year[yr] = val

            avg_dividend_5y = sum(div_by_year.values()) / 5.0
            target_yield = target_yield_pct / 100
            ceiling_price = (avg_dividend_5y / target_yield) if target_yield > 0 else 0.0
            avg_dy_5y = (avg_dividend_5y / current_price * 100) if current_price > 0 else 0.0

            return {
                "ticker": ticker,
                "name": name,
                "current_price": current_price,
                "vpa": vpa,
                "pb": pb,
                "pe": pe,
                "dy": dy,
                "roe": roe,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "dividends_5y": div_by_year,
                "avg_dividend_5y": avg_dividend_5y,
                "ceiling_price": ceiling_price,
                "avg_dy_5y": avg_dy_5y
            }
        except Exception:
            return {}

    @staticmethod
    @st.cache_data
    def load_assets_catalog():
        """Loads the B3 assets static catalog from assets.csv into memory RAM (Vastly faster!)."""
        if os.path.exists("assets.csv"):
            return pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig").set_index("CÓDIGO")
        return pd.DataFrame()

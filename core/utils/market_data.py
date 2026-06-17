import streamlit as st
import yfinance as yf
import datetime
import os
import pandas as pd

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
            
            current_price = info.get("currentPrice", info.get("lastPrice", info.get("regularMarketPrice", 0.0)))
            ticker_clean = ticker.strip().upper()
            
            # Trailing 12-Month Dividend Yield calculated dynamically to avoid Yahoo's glitched info['dividendYield']
            div_series = t.dividends
            one_year_ago = datetime.date.today() - datetime.timedelta(days=365)
            l12m_dividends = 0.0
            
            if not div_series.empty:
                div_series.index = pd.to_datetime(div_series.index).date
                l12m_dividends = float(div_series.loc[one_year_ago:].sum())
                
            # Query custom dynamic database-driven corrections (TTM sum adjust)
            from core.database import db
            conn = db.get_personal_connection()
            cursor = conn.cursor()
            current_year = datetime.date.today().year
            cursor.execute(
                "SELECT year, total_value FROM dividend_corrections WHERE ticker = ? AND year IN (?, ?)",
                (ticker_clean, current_year, current_year - 1)
            )
            db_corrections = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()
            
            # Dynamically adjust the TTM sum if Yahoo has gaps/omissions compared to corrections table
            for yr, corrected_total in db_corrections.items():
                if not div_series.empty:
                    yahoo_total = float(div_series[div_series.index.map(lambda d: d.year == yr)].sum())
                else:
                    yahoo_total = 0.0
                if corrected_total > yahoo_total:
                    l12m_dividends += (corrected_total - yahoo_total)
                
            dy = (l12m_dividends / current_price * 100) if current_price > 0 else 0.0
            
            return {
                "current_price": current_price,
                "dy": dy,
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
            roe = info.get("returnOnEquity", 0.0) * 100 if info.get("returnOnEquity") is not None else 0.0
            high_52w = info.get("fiftyTwoWeekHigh", 0.0)
            low_52w = info.get("fiftyTwoWeekLow", 0.0)
            name = info.get("longName", info.get("shortName", ticker))

            div_series = t.dividends
            current_year = datetime.date.today().year
            last_5_years = [current_year - i for i in range(1, 6)]

            div_by_year = {}
            ticker_clean = ticker.strip().upper()

            # Connect to database and fetch all corrections for this ticker dynamically
            from core.database import db
            conn = db.get_personal_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT year, total_value FROM dividend_corrections WHERE ticker = ?", (ticker_clean,))
            db_corrections_all = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            if not div_series.empty:
                div_df = div_series.groupby(div_series.index.year).sum()
                for yr in last_5_years:
                    val = float(div_df.get(yr, 0.0))
                    if yr in db_corrections_all:
                        val = db_corrections_all[yr]
                    div_by_year[yr] = val
            else:
                for yr in last_5_years:
                    val = 0.0
                    if yr in db_corrections_all:
                        val = db_corrections_all[yr]
                    div_by_year[yr] = val

            # Calculate Trailing 12-Month Dividend Yield dynamically to avoid Yahoo's glitched dividendYield field
            one_year_ago = datetime.date.today() - datetime.timedelta(days=365)
            l12m_dividends_sum = 0.0
            if not div_series.empty:
                div_series.index = pd.to_datetime(div_series.index).date
                l12m_dividends_sum = float(div_series.loc[one_year_ago:].sum())
                
            # Dynamically adjust TTM sum from SQLite
            for yr, corrected_total in db_corrections_all.items():
                if yr in (current_year, current_year - 1):
                    if not div_series.empty:
                        yahoo_total = float(div_series[div_series.index.map(lambda d: d.year == yr)].sum())
                    else:
                        yahoo_total = 0.0
                    if corrected_total > yahoo_total:
                        l12m_dividends_sum += (corrected_total - yahoo_total)

            dy = (l12m_dividends_sum / current_price * 100) if current_price > 0 else 0.0

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

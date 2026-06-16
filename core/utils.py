import streamlit as st
import yfinance as yf
import datetime
from core.constants import MONTHS_PT

class SessionManager:
    """Manages the initialization of the application's global state."""

    @staticmethod
    def initialize():
        """Initializes shared parameters in the Session State on the first page load."""

        # We need to import the service here to avoid circular imports during startup
        from planning.planning_service import SimulationService

        # Load from Database on first run
        if 'db_loaded' not in st.session_state:
            config = SimulationService.get_configuration()
            if config:
                # Convert birth_date text string back to datetime.date
                try:
                    if isinstance(config['birth_date'], str):
                        st.session_state.birth_date = datetime.datetime.strptime(config['birth_date'], "%Y-%m-%d").date()
                    else:
                        st.session_state.birth_date = config['birth_date']
                except Exception:
                    st.session_state.birth_date = datetime.date(1992, 7, 9)

                st.session_state.retirement_age = config['retirement_age']
                st.session_state.desired_income_mw = float(config['desired_income_mw'])
                st.session_state.annual_interest_rate = float(config['annual_interest_rate'])
                st.session_state.mw_value = float(config['mw_value'])
                st.session_state.initial_equity_input = float(config['initial_equity_input'])
            st.session_state.db_loaded = True

        # Fallback Defaults (if DB is empty or fails)
        if 'birth_date' not in st.session_state:
            st.session_state.birth_date = datetime.date(1992, 7, 9)
        if 'retirement_age' not in st.session_state:
            st.session_state.retirement_age = 65
        if 'desired_income_mw' not in st.session_state:
            st.session_state.desired_income_mw = 7.0
        if 'annual_interest_rate' not in st.session_state:
            st.session_state.annual_interest_rate = 6.0
        if 'mw_value' not in st.session_state:
            st.session_state.mw_value = MarketData.get_current_minimum_wage()
        if 'initial_equity_input' not in st.session_state:
            st.session_state.initial_equity_input = 0.0

        # UI Caches
        if 'required_monthly_contribution_cache' not in st.session_state:
            st.session_state.required_monthly_contribution_cache = 0.0
        if 'calculated_equity_cache' not in st.session_state:
            st.session_state.calculated_equity_cache = 0.0

class Formatter:
    """Utility class for visual data formatting."""

    @staticmethod
    def format_currency(value: float) -> str:
        """Formats a float to the Brazilian currency string (R$ 1.234,56)."""
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def format_month_year(month_str: str) -> str:
        """Formats a YYYY-MM date to the Month/Year format (e.g., Jan/2021)."""
        try:
            year, month = month_str.split('-')
            return f"{MONTHS_PT[month]}/{year}"
        except Exception:
            return month_str

class MarketData:
    """Class responsible for integrations with market APIs."""

    @staticmethod
    @st.cache_data(ttl=600)
    def get_batch_quotes(tickers: list) -> dict:
        """Fetches batch quotes from Yahoo Finance with a 10-minute cache."""
        quotes = {}
        for t in tickers:
            try:
                # Brazilian tickers on Yahoo Finance have the .SA extension
                ticker_sa = f"{t.strip().upper()}.SA"
                info = yf.Ticker(ticker_sa).fast_info
                quotes[t] = info['lastPrice']
            except Exception:
                quotes[t] = 0.0
        return quotes

    @staticmethod
    @st.cache_data(ttl=3600) # Cache for 1 hour
    def get_ticker_details(ticker: str) -> dict:
        """Fetches advanced real-time metrics and historical data for a ticker from Yahoo Finance."""
        ticker_sa = f"{ticker.strip().upper()}.SA"
        try:
            t = yf.Ticker(ticker_sa)
            info = t.info

            # Fetch 1 year of historical close prices for the behavior chart
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
        # BCB SGS Serie 1619 - Salário Mínimo
        url = 'https://api.bcb.gov.br/dados/serie/bcdata.sgs.1619/dados/ultimos/1?formato=json'
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if data and len(data) > 0 and 'valor' in data[0]:
                return float(data[0]['valor'])
        except Exception:
            pass
        return 1621.0 # Hardcoded fallback if API fails

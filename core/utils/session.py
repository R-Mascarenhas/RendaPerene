import streamlit as st
import datetime
from core.utils.market_data import MarketData
from core.constants import (
    BIRTH_DATE, RETIREMENT_AGE, DESIRED_INCOME_MW, ANNUAL_INTEREST_RATE, MW_VALUE, INITIAL_EQUITY_INPUT,
    DESIRED_INCOME_TYPE, DESIRED_INCOME_FIXED, CEILING_MODEL_SELECTION, BAZIN_TARGET_YIELD, BAZIN_TARGET_SPREAD,
    SESSION_BIRTH_DATE, SESSION_RETIREMENT_AGE, SESSION_DESIRED_INCOME_MW, SESSION_ANNUAL_INTEREST_RATE,
    SESSION_MW_VALUE, SESSION_INITIAL_EQUITY, SESSION_DESIRED_INCOME_TYPE, SESSION_DESIRED_INCOME_FIXED,
    SESSION_CEILING_MODEL_SELECTION, SESSION_BAZIN_TARGET_YIELD, SESSION_BAZIN_TARGET_SPREAD,
    SESSION_REQUIRED_CONTRIBUTION_CACHE, SESSION_CALCULATED_EQUITY_CACHE
)
from core.strings import MODEL_CLASSIC

class SessionManager:
    """Manages the initialization of the application's global session state."""

    @staticmethod
    def initialize():
        """Initializes shared parameters in the Session State on the first page load."""
        from services.planning_service import SimulationService

        # Load from Database on first run
        if 'db_loaded' not in st.session_state:
            config = SimulationService.get_configuration()
            if config:
                try:
                    if isinstance(config[BIRTH_DATE], str):
                        st.session_state[SESSION_BIRTH_DATE] = datetime.datetime.strptime(config[BIRTH_DATE], "%Y-%m-%d").date()
                    else:
                        st.session_state[SESSION_BIRTH_DATE] = config[BIRTH_DATE]
                except Exception:
                    st.session_state[SESSION_BIRTH_DATE] = datetime.date(1992, 7, 9)

                st.session_state[SESSION_RETIREMENT_AGE] = config[RETIREMENT_AGE]
                st.session_state[SESSION_DESIRED_INCOME_MW] = float(config[DESIRED_INCOME_MW])
                st.session_state[SESSION_ANNUAL_INTEREST_RATE] = float(config[ANNUAL_INTEREST_RATE])
                st.session_state[SESSION_MW_VALUE] = float(config[MW_VALUE])
                st.session_state[SESSION_INITIAL_EQUITY] = float(config[INITIAL_EQUITY_INPUT])
                st.session_state[SESSION_DESIRED_INCOME_TYPE] = config.get(DESIRED_INCOME_TYPE, 'MULTIPLIER')
                st.session_state[SESSION_DESIRED_INCOME_FIXED] = float(config.get(DESIRED_INCOME_FIXED, 10000.0))

                # Load persistent Price-Ceiling model and variables
                st.session_state[SESSION_CEILING_MODEL_SELECTION] = config.get(CEILING_MODEL_SELECTION, MODEL_CLASSIC)
                st.session_state[SESSION_BAZIN_TARGET_YIELD] = float(config.get(BAZIN_TARGET_YIELD, 6.0))
                st.session_state[SESSION_BAZIN_TARGET_SPREAD] = float(config.get(BAZIN_TARGET_SPREAD, 3.0))
            st.session_state.db_loaded = True

        # Fallback Defaults (Using protected constants to prevent Streamlit widget unmount deletions!)
        if SESSION_BIRTH_DATE not in st.session_state:
            st.session_state[SESSION_BIRTH_DATE] = datetime.date(1992, 7, 9)
        if SESSION_RETIREMENT_AGE not in st.session_state:
            st.session_state[SESSION_RETIREMENT_AGE] = 65
        if SESSION_DESIRED_INCOME_MW not in st.session_state:
            st.session_state[SESSION_DESIRED_INCOME_MW] = 7.0
        if SESSION_ANNUAL_INTEREST_RATE not in st.session_state:
            st.session_state[SESSION_ANNUAL_INTEREST_RATE] = 6.0
        if SESSION_MW_VALUE not in st.session_state:
            st.session_state[SESSION_MW_VALUE] = MarketData.get_current_minimum_wage()
        if SESSION_INITIAL_EQUITY not in st.session_state:
            st.session_state[SESSION_INITIAL_EQUITY] = 0.0
        if SESSION_DESIRED_INCOME_TYPE not in st.session_state:
            st.session_state[SESSION_DESIRED_INCOME_TYPE] = '{INCOME_TYPE_MULTIPLIER}'
        if SESSION_DESIRED_INCOME_FIXED not in st.session_state:
            st.session_state[SESSION_DESIRED_INCOME_FIXED] = 10000.0

        # Fallback Model states
        if SESSION_CEILING_MODEL_SELECTION not in st.session_state:
            st.session_state[SESSION_CEILING_MODEL_SELECTION] = MODEL_CLASSIC
        if SESSION_BAZIN_TARGET_YIELD not in st.session_state:
            st.session_state[SESSION_BAZIN_TARGET_YIELD] = 6.0
        if SESSION_BAZIN_TARGET_SPREAD not in st.session_state:
            st.session_state[SESSION_BAZIN_TARGET_SPREAD] = 3.0

        # UI Caches
        if SESSION_REQUIRED_CONTRIBUTION_CACHE not in st.session_state:
            st.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] = 0.0
        if SESSION_CALCULATED_EQUITY_CACHE not in st.session_state:
            st.session_state[SESSION_CALCULATED_EQUITY_CACHE] = 0.0

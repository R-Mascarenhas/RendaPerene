import streamlit as st
import datetime
from core.utils.market_data import MarketData

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
                    if isinstance(config['birth_date'], str):
                        st.session_state.birth_date = datetime.datetime.strptime(config['birth_date'], "%Y-%m-%d").date()
                    else:
                        st.session_state.birth_date = config['birth_date']
                except Exception:
                    st.session_state.birth_date = datetime.date(1992, 7, 9)

                st.session_state.retirement_age = config['retirement_age']
                st.session_state.desired_income_mw_val = float(config['desired_income_mw'])
                st.session_state.annual_interest_rate = float(config['annual_interest_rate'])
                st.session_state.mw_value = float(config['mw_value'])
                st.session_state.initial_equity_input = float(config['initial_equity_input'])
                st.session_state.desired_income_type = config.get('desired_income_type', 'MULTIPLIER')
                st.session_state.desired_income_fixed_val = float(config.get('desired_income_fixed', 10000.0))
            st.session_state.db_loaded = True

        # Fallback Defaults (Using protected _val suffix to prevent Streamlit widget unmount deletions!)
        if 'birth_date' not in st.session_state:
            st.session_state.birth_date = datetime.date(1992, 7, 9)
        if 'retirement_age' not in st.session_state:
            st.session_state.retirement_age = 65
        if 'desired_income_mw_val' not in st.session_state:
            st.session_state.desired_income_mw_val = 7.0
        if 'annual_interest_rate' not in st.session_state:
            st.session_state.annual_interest_rate = 6.0
        if 'mw_value' not in st.session_state:
            st.session_state.mw_value = MarketData.get_current_minimum_wage()
        if 'initial_equity_input' not in st.session_state:
            st.session_state.initial_equity_input = 0.0
        if 'desired_income_type' not in st.session_state:
            st.session_state.desired_income_type = 'MULTIPLIER'
        if 'desired_income_fixed_val' not in st.session_state:
            st.session_state.desired_income_fixed_val = 10000.0

        # UI Caches
        if 'required_monthly_contribution_cache' not in st.session_state:
            st.session_state.required_monthly_contribution_cache = 0.0
        if 'calculated_equity_cache' not in st.session_state:
            st.session_state.calculated_equity_cache = 0.0

import datetime

import streamlit as st

from core.constants import (
    ANNUAL_INTEREST_RATE,
    BAZIN_TARGET_SPREAD,
    BAZIN_TARGET_YIELD,
    BIRTH_DATE,
    CEILING_MODEL_SELECTION,
    DESIRED_INCOME_FIXED,
    DESIRED_INCOME_MW,
    DESIRED_INCOME_TYPE,
    INITIAL_EQUITY_INPUT,
    MW_VALUE,
    PLANNING_START_DATE,
    RETIREMENT_AGE,
    SESSION_ANNUAL_INTEREST_RATE,
    SESSION_BAZIN_TARGET_SPREAD,
    SESSION_BAZIN_TARGET_YIELD,
    SESSION_BIRTH_DATE,
    SESSION_CALCULATED_EQUITY_CACHE,
    SESSION_CEILING_MODEL_SELECTION,
    SESSION_DESIRED_INCOME_FIXED,
    SESSION_DESIRED_INCOME_MW,
    SESSION_DESIRED_INCOME_TYPE,
    SESSION_INITIAL_EQUITY,
    SESSION_MW_VALUE,
    SESSION_PLANNING_START_DATE,
    SESSION_PLANNING_START_DATE_ENABLED,
    SESSION_REQUIRED_CONTRIBUTION_CACHE,
    SESSION_RETIREMENT_AGE,
)
from core.strings import MODEL_CLASSIC
from views.cached_market_data import StreamlitCachedMarketData as MarketData


class SessionManager:
    """Manages the initialization of the application's global session state."""

    @staticmethod
    def initialize():
        """Initializes shared parameters in the Session State on the first page load."""
        from services.planning_service import SimulationService

        # Load from Database on first run
        if "db_loaded" not in st.session_state:
            import sys

            if getattr(sys, "frozen", False):
                import threading

                threading.Thread(target=monitor_active_sessions, daemon=True).start()

            config = SimulationService.get_configuration()
            if config:
                try:
                    if isinstance(config[BIRTH_DATE], str):
                        st.session_state[SESSION_BIRTH_DATE] = datetime.datetime.strptime(
                            config[BIRTH_DATE], "%Y-%m-%d"
                        ).date()
                    else:
                        st.session_state[SESSION_BIRTH_DATE] = config[BIRTH_DATE]
                except Exception:
                    st.session_state[SESSION_BIRTH_DATE] = datetime.date(1992, 7, 9)

                st.session_state[SESSION_RETIREMENT_AGE] = config[RETIREMENT_AGE]
                st.session_state[SESSION_DESIRED_INCOME_MW] = float(config[DESIRED_INCOME_MW])
                st.session_state[SESSION_ANNUAL_INTEREST_RATE] = float(config[ANNUAL_INTEREST_RATE])
                st.session_state[SESSION_MW_VALUE] = float(config[MW_VALUE])
                st.session_state[SESSION_INITIAL_EQUITY] = float(config[INITIAL_EQUITY_INPUT])
                st.session_state[SESSION_DESIRED_INCOME_TYPE] = config.get(
                    DESIRED_INCOME_TYPE, "MULTIPLIER"
                )
                st.session_state[SESSION_DESIRED_INCOME_FIXED] = float(
                    config.get(DESIRED_INCOME_FIXED, 10000.0)
                )

                # Load persistent Price-Ceiling model and variables
                st.session_state[SESSION_CEILING_MODEL_SELECTION] = config.get(
                    CEILING_MODEL_SELECTION, MODEL_CLASSIC
                )
                st.session_state[SESSION_BAZIN_TARGET_YIELD] = float(
                    config.get(BAZIN_TARGET_YIELD, 6.0)
                )
                st.session_state[SESSION_BAZIN_TARGET_SPREAD] = float(
                    config.get(BAZIN_TARGET_SPREAD, 3.0)
                )

                # Load persistent Planning Start Date configuration
                try:
                    start_date_val = config.get(PLANNING_START_DATE)
                    if start_date_val:
                        if isinstance(start_date_val, str):
                            st.session_state[SESSION_PLANNING_START_DATE] = (
                                datetime.datetime.strptime(start_date_val, "%Y-%m-%d").date()
                            )
                        else:
                            st.session_state[SESSION_PLANNING_START_DATE] = start_date_val
                        st.session_state[SESSION_PLANNING_START_DATE_ENABLED] = True
                    else:
                        st.session_state[SESSION_PLANNING_START_DATE] = datetime.date.today()
                        st.session_state[SESSION_PLANNING_START_DATE_ENABLED] = False
                except Exception:
                    st.session_state[SESSION_PLANNING_START_DATE] = datetime.date.today()
                    st.session_state[SESSION_PLANNING_START_DATE_ENABLED] = False
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
            st.session_state[SESSION_DESIRED_INCOME_TYPE] = "{INCOME_TYPE_MULTIPLIER}"
        if SESSION_DESIRED_INCOME_FIXED not in st.session_state:
            st.session_state[SESSION_DESIRED_INCOME_FIXED] = 10000.0

        # Fallback Model states
        if SESSION_CEILING_MODEL_SELECTION not in st.session_state:
            st.session_state[SESSION_CEILING_MODEL_SELECTION] = MODEL_CLASSIC
        if SESSION_BAZIN_TARGET_YIELD not in st.session_state:
            st.session_state[SESSION_BAZIN_TARGET_YIELD] = 6.0
        if SESSION_BAZIN_TARGET_SPREAD not in st.session_state:
            st.session_state[SESSION_BAZIN_TARGET_SPREAD] = 3.0

        # Fallback Planning Start Date states
        if SESSION_PLANNING_START_DATE not in st.session_state:
            st.session_state[SESSION_PLANNING_START_DATE] = datetime.date.today()
        if SESSION_PLANNING_START_DATE_ENABLED not in st.session_state:
            st.session_state[SESSION_PLANNING_START_DATE_ENABLED] = False

        # UI Caches
        if SESSION_REQUIRED_CONTRIBUTION_CACHE not in st.session_state:
            st.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] = 0.0
        if SESSION_CALCULATED_EQUITY_CACHE not in st.session_state:
            st.session_state[SESSION_CALCULATED_EQUITY_CACHE] = 0.0


def monitor_active_sessions():
    """Monitors active browser tab connections and cleanly stops the server runtime when all close."""
    import os
    import sys
    import time

    from streamlit.runtime import get_instance

    try:
        with open("session_debug.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"[{time.ctime()}] Monitor thread started.\n")
    except Exception:
        pass

    # Grace period for the initial browser tab to load and connect
    time.sleep(15)

    has_had_session = False
    zero_session_count = 0
    while True:
        time.sleep(5)
        runtime = get_instance()
        if runtime is None:
            try:
                with open("session_debug.log", "a", encoding="utf-8") as log_file:
                    log_file.write(f"[{time.ctime()}] Runtime is None.\n")
            except Exception:
                pass
            continue

        session_count = 0
        session_details = []
        try:
            # list_active_sessions() returns ActiveSessionInfo (Streamlit 1.18.0+)
            sessions = runtime._session_mgr.list_active_sessions()
            session_count = len(sessions)
            try:
                session_details = [s.session.id for s in sessions]
            except Exception:
                session_details = [str(s) for s in sessions]
        except Exception as e:
            try:
                # list_sessions() is the older session info list (pre-1.18.0)
                sessions = runtime._session_mgr.list_sessions()
                session_count = len(sessions)
                try:
                    session_details = [s.id for s in sessions]
                except Exception:
                    session_details = [str(s) for s in sessions]
            except Exception as e2:
                try:
                    with open("session_debug.log", "a", encoding="utf-8") as log_file:
                        log_file.write(f"[{time.ctime()}] Exception listing sessions: {e} | {e2}\n")
                except Exception:
                    pass
                continue

        try:
            with open("session_debug.log", "a", encoding="utf-8") as log_file:
                log_file.write(
                    f"[{time.ctime()}] Active sessions count: {session_count} | Sessions: {session_details} | Has had session: {has_had_session} | Zero count: {zero_session_count}\n"
                )
        except Exception:
            pass

        if session_count > 0:
            has_had_session = True
            zero_session_count = 0
        elif has_had_session:
            zero_session_count += 1

        # Terminate cleanly after 2 consecutive checks with 0 active sessions (10s)
        if has_had_session and zero_session_count >= 2:
            try:
                with open("session_debug.log", "a", encoding="utf-8") as log_file:
                    log_file.write(f"[{time.ctime()}] Shutdown trigger fired! Exiting process.\n")
            except Exception:
                pass
            if "pytest" in sys.modules:
                runtime.stop()
                break
            else:
                import os

                os._exit(0)


def get_app_version() -> str:
    """Reads current application version from version.txt, supporting both dev and PyInstaller."""
    import os
    import sys

    try:
        # PyInstaller extracts resources to sys._MEIPASS at runtime
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")

    version_path = os.path.join(base_path, "version.txt")
    if os.path.exists(version_path):
        try:
            with open(version_path, encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            try:
                with open("session_debug.log", "a", encoding="utf-8") as log_file:
                    import time

                    log_file.write(f"[{time.ctime()}] WARNING: Error reading version.txt: {e}\n")
            except Exception:
                pass
    else:
        try:
            with open("session_debug.log", "a", encoding="utf-8") as log_file:
                import time

                log_file.write(
                    f"[{time.ctime()}] WARNING: version.txt not found at path: {version_path}\n"
                )
        except Exception:
            pass
    return "0.0.0"

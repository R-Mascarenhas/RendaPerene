import pytest
import datetime
import streamlit as st
import time
import sys
import os
from core.database import db
from core.application_paths import ApplicationPaths
from core.utils.formatter import Formatter
from core.utils.session import get_app_version, monitor_active_sessions, SessionManager


def test_formatter_colored_cell_style_dry_sanity():
    """
    Verifies that Formatter.get_colored_cell_style and Formatter.get_trend_cell_style
    return the correct high-contrast CSS color tags depending on Bazin price-to-ceiling margins
    and positive/negative trends (DRY contract sanity).
    """
    # 1. Price is cheap/muy barato (<= 80% of ceiling) -> Green
    style_green = Formatter.get_colored_cell_style(price=30.0, ceiling=50.0)
    assert "rgba(40, 167, 69, 0.25)" in style_green
    assert "font-weight: bold" in style_green

    # 2. Price is fair/abaixo (<= 100% of ceiling) -> Yellow
    style_yellow = Formatter.get_colored_cell_style(price=45.0, ceiling=50.0)
    assert "rgba(255, 193, 7, 0.25)" in style_yellow

    # 3. Price is expensive (> ceiling) -> Red
    style_red = Formatter.get_colored_cell_style(price=55.0, ceiling=50.0)
    assert "rgba(220, 53, 69, 0.25)" in style_red

    # 4. Ceiling is invalid (<= 0.0) -> Transparent
    style_trans = Formatter.get_colored_cell_style(price=30.0, ceiling=0.0)
    assert "transparent" in style_trans

    # 5. Trend is positive -> Green
    trend_green = Formatter.get_trend_cell_style(15.5)
    assert "rgba(40, 167, 69, 0.25)" in trend_green

    # 6. Trend is negative -> Red
    trend_red = Formatter.get_trend_cell_style(-3.2)
    assert "rgba(220, 53, 69, 0.25)" in trend_red

    # 7. Trend is neutral -> Transparent
    trend_neutral = Formatter.get_trend_cell_style(0.0)
    assert "transparent" in trend_neutral


def test_format_currency_compacts_millions_and_billions():
    """Large positive and negative currency amounts must remain compact in the UI."""
    assert Formatter.format_currency(999_999.99) == "R$ 999.999,99"
    assert Formatter.format_currency(1_250_000) == "R$ 1,25 mi"
    assert Formatter.format_currency(2_500_000_000) == "R$ 2,50 bi"
    assert Formatter.format_currency(-2_500_000_000) == "-R$ 2,50 bi"


def test_format_integer_compacts_millions_and_billions():
    """Large integer-like values must remain compact in market metrics."""
    assert Formatter.format_integer(999_999) == "999.999"
    assert Formatter.format_integer(1_250_000) == "1,25 mi"
    assert Formatter.format_integer(2_500_000_000) == "2,50 bi"
    assert Formatter.format_integer(-2_500_000_000) == "-2,50 bi"


def test_get_app_version_sanity(monkeypatch, tmp_path):
    """
    Verifies that get_app_version() correctly reads version.txt from either
    the standard folder or the PyInstaller sys._MEIPASS temporary directory.
    """
    # Test 1: Standard environment (dev)
    # Ensure it reads 'version.txt' from current directory
    with open("version.txt", "r", encoding="utf-8") as f:
        expected_version = f.read().strip()
    assert get_app_version() == expected_version

    # Test 2: PyInstaller environment (sys._MEIPASS mocked)
    mock_meipass = str(tmp_path)
    version_file = tmp_path / "version.txt"
    version_file.write_text("2.3.4.5", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", mock_meipass, raising=False)
    assert get_app_version() == "2.3.4.5"


def test_monitor_active_sessions_stop_trigger(monkeypatch):
    """
    Verifies that monitor_active_sessions() cleanly stops the Streamlit runtime
    when the active session count drops from positive to zero.
    """
    # Mock time.sleep to return immediately so the test runs instantly
    monkeypatch.setattr(time, "sleep", lambda x: None)

    # Mock Streamlit Runtime and session manager
    class MockSession:
        def __init__(self, session_id):
            self.id = session_id

    class MockSessionManager:
        def __init__(self):
            # Start with 1 session, then drop to 0 on the second call
            self.call_count = 0

        def list_sessions(self):
            self.call_count += 1
            if self.call_count == 1:
                return [MockSession("session_1")]
            return []  # 0 sessions

    class MockRuntime:
        def __init__(self):
            self._session_mgr = MockSessionManager()
            self.stopped = False

        def stop(self):
            self.stopped = True

    mock_runtime = MockRuntime()

    # Mock get_instance to return our mocked Runtime
    monkeypatch.setattr("streamlit.runtime.get_instance", lambda: mock_runtime)

    # Run the monitor loop (it will terminate because runtime.stop() is called, breaking the loop)
    monitor_active_sessions()

    assert mock_runtime.stopped is True


def test_session_manager_initialization_on_empty_database(mock_db, monkeypatch):
    """
    Ensures that SessionManager.initialize() can run on a completely fresh,
    empty database without crashing due to NameErrors (such as uninitialized start_date_val).
    """
    # 1. Clear database configuration to simulate a fresh install/deploy
    conn = db.get_personal_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM planning_configuration")
    conn.commit()
    conn.close()

    # 2. Mock st.session_state using a dict that supports attribute access
    class MockSessionState(dict):
        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError:
                raise AttributeError(name)

        def __setattr__(self, name, value):
            self[name] = value

    mock_session = MockSessionState()
    monkeypatch.setattr(st, "session_state", mock_session)

    # 3. Call SessionManager.initialize() and ensure it doesn't crash
    try:
        SessionManager.initialize()
    except NameError as e:
        pytest.fail(f"SessionManager.initialize() crashed with NameError: {e}")
    except Exception as e:
        pytest.fail(f"SessionManager.initialize() crashed with unexpected exception: {e}")

    # 4. Assert that defaults are correctly set in the mocked session state
    from core.constants import (
        SESSION_BIRTH_DATE,
        SESSION_RETIREMENT_AGE,
        SESSION_ANNUAL_INTEREST_RATE,
        SESSION_MW_VALUE,
        SESSION_INITIAL_EQUITY,
        SESSION_PLANNING_START_DATE,
        SESSION_PLANNING_START_DATE_ENABLED,
    )

    assert mock_session[SESSION_BIRTH_DATE] == datetime.date(1992, 7, 9)
    assert mock_session[SESSION_RETIREMENT_AGE] == 65
    assert mock_session[SESSION_PLANNING_START_DATE] == datetime.date.today()
    assert mock_session[SESSION_PLANNING_START_DATE_ENABLED] is False
    assert mock_session.db_loaded is True


def test_session_manager_resets_portfolio_state(monkeypatch):
    """Portfolio replacement must invalidate values loaded from the previous database."""
    from core.constants import (
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
        WIDGET_BAZIN_SPREAD_INPUT,
        WIDGET_BAZIN_YIELD_INPUT,
        WIDGET_BIRTH_DATE,
        WIDGET_CEILING_MODEL_SELECTOR,
        WIDGET_INCOME_FIXED,
        WIDGET_INCOME_MW,
        WIDGET_INCOME_TYPE,
        WIDGET_INITIAL_EQUITY,
        WIDGET_INTEREST_RATE,
        WIDGET_PLANNING_START_DATE,
        WIDGET_PLANNING_START_DATE_ENABLED,
        WIDGET_RETIREMENT_AGE,
    )

    portfolio_keys = {
        "db_loaded",
        "enable_dividend_reinvestment_goal_portfolio.db",
        "enable_share_quantity_goal_portfolio.db",
        SESSION_BIRTH_DATE,
        SESSION_RETIREMENT_AGE,
        SESSION_DESIRED_INCOME_MW,
        SESSION_ANNUAL_INTEREST_RATE,
        SESSION_MW_VALUE,
        SESSION_INITIAL_EQUITY,
        SESSION_DESIRED_INCOME_TYPE,
        SESSION_DESIRED_INCOME_FIXED,
        SESSION_CEILING_MODEL_SELECTION,
        SESSION_BAZIN_TARGET_YIELD,
        SESSION_BAZIN_TARGET_SPREAD,
        SESSION_PLANNING_START_DATE,
        SESSION_PLANNING_START_DATE_ENABLED,
        SESSION_REQUIRED_CONTRIBUTION_CACHE,
        SESSION_CALCULATED_EQUITY_CACHE,
        WIDGET_BIRTH_DATE,
        WIDGET_RETIREMENT_AGE,
        WIDGET_INTEREST_RATE,
        WIDGET_INCOME_TYPE,
        WIDGET_INCOME_MW,
        WIDGET_INCOME_FIXED,
        WIDGET_CEILING_MODEL_SELECTOR,
        WIDGET_BAZIN_YIELD_INPUT,
        WIDGET_BAZIN_SPREAD_INPUT,
        WIDGET_PLANNING_START_DATE,
        WIDGET_PLANNING_START_DATE_ENABLED,
        WIDGET_INITIAL_EQUITY,
    }
    mock_session = {key: "stale" for key in portfolio_keys}
    mock_session.update({"active_db": "portfolio.db", "session_id": "keep-me"})
    monkeypatch.setattr(st, "session_state", mock_session)

    SessionManager.reset_portfolio_state()

    assert portfolio_keys.isdisjoint(mock_session)
    assert mock_session["active_db"] == "portfolio.db"
    assert mock_session["session_id"] == "keep-me"


def test_session_manager_switches_to_valid_fallback_and_resets_loaded_state(monkeypatch):
    from core.constants import SESSION_BIRTH_DATE

    mock_session = {
        "active_db": "portfolio_missing.db",
        "db_loaded": True,
        SESSION_BIRTH_DATE: "stale",
        "session_id": "keep-me",
    }
    monkeypatch.setattr(st, "session_state", mock_session)
    fallback = ApplicationPaths.choose_portfolio(mock_session["active_db"], ["portfolio_family.db"])

    changed = SessionManager.switch_portfolio(fallback)

    assert changed is True
    assert mock_session["active_db"] == "portfolio_family.db"
    assert "db_loaded" not in mock_session
    assert SESSION_BIRTH_DATE not in mock_session
    assert mock_session["session_id"] == "keep-me"

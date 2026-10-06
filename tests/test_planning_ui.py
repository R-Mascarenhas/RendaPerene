"""Exercise retirement planning through real Streamlit widgets and callbacks."""

import datetime

import pytest
import streamlit.env_util
from streamlit.testing.v1 import AppTest

from core.constants import (
    INITIAL_EQUITY_AUTO,
    INITIAL_EQUITY_MANUAL_OVERRIDE,
    SESSION_INITIAL_EQUITY,
    SESSION_REQUIRED_CONTRIBUTION_CACHE,
    WIDGET_INITIAL_EQUITY_DYNAMIC_PREFIX,
    WIDGET_PLANNING_START_DATE,
    WIDGET_PLANNING_START_DATE_ENABLED,
    WIDGET_RETIREMENT_AGE,
)
from core.utils.formatter import Formatter
from services.assets_service import AssetService
from services.planning_service import SimulationService


PLANNING_SCRIPT = """
from core.utils.session import SessionManager
from views.planning_view import PlanningView

SessionManager.initialize()
PlanningView().render()
"""


@pytest.fixture
def planning_app(monkeypatch):
    # Avoid AppTest's costly REPL detection on the WSL mount.
    monkeypatch.setattr(streamlit.env_util, "is_repl", lambda: False)
    SimulationService.save_configuration(
        birth_date="1990-01-01",
        retirement_age=65,
        desired_income_mw=5.0,
        annual_interest_rate=6.0,
        mw_value=1500.0,
        initial_equity_input=0.0,
    )
    return AppTest.from_string(PLANNING_SCRIPT, default_timeout=30)


def test_retirement_age_edit_updates_saved_plan_and_displayed_contribution(planning_app):
    app = planning_app.run()
    assert not app.exception
    previous_contribution = app.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE]

    app.number_input(key=WIDGET_RETIREMENT_AGE).set_value(60).run()

    assert not app.exception
    assert SimulationService.get_configuration()["retirement_age"] == 60
    assert app.number_input(key=WIDGET_RETIREMENT_AGE).value == 60
    simulation = SimulationService.get_current_simulation()
    contribution = simulation.updated_monthly_contribution
    assert contribution > previous_contribution
    assert app.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] == pytest.approx(contribution)
    displayed = next(metric for metric in app.metric if metric.label == "Aporte Mensal Atualizado")
    assert displayed.value == Formatter.format_currency(contribution)

    # A fresh UI session must reload the value persisted by the widget callback.
    reloaded = AppTest.from_string(PLANNING_SCRIPT, default_timeout=30).run()
    assert not reloaded.exception
    assert reloaded.number_input(key=WIDGET_RETIREMENT_AGE).value == 60


def test_sandbox_edit_changes_its_metrics_without_changing_saved_plan_or_cache(planning_app):
    app = planning_app.run()
    assert not app.exception
    saved_config = SimulationService.get_configuration()
    saved_contribution = app.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE]
    # The sandbox is rendered first, before the saved plan's metrics.
    initial_sandbox_contribution = next(
        metric.value for metric in app.metric if metric.label == "Aporte Mensal Necessário"
    )

    app.number_input(key="sandbox_patrimonio_inicial").set_value(100000.0).run()

    assert not app.exception
    assert SimulationService.get_configuration() == saved_config
    assert app.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] == saved_contribution
    assert app.number_input(key="sandbox_patrimonio_inicial").value == 100000.0
    updated_sandbox_contribution = next(
        metric.value for metric in app.metric if metric.label == "Aporte Mensal Necessário"
    )
    assert updated_sandbox_contribution != initial_sandbox_contribution
    assert len(app.get("plotly_chart")) == 4

    app.run()
    assert not app.exception
    assert app.number_input(key="sandbox_patrimonio_inicial").value == 100000.0
    assert app.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] == saved_contribution


@pytest.mark.parametrize("manual_equity", [0.0, 8000.0])
def test_start_date_refreshes_auto_equity_but_preserves_manual_input(planning_app, manual_equity):
    AssetService.add_transaction("BBAS3", "2023-01-01", "BUY", 100, 30.0)
    AssetService.add_transaction("BBAS3", "2024-06-01", "BUY", 100, 20.0)
    app = planning_app.run()
    assert not app.exception

    app.checkbox(key=WIDGET_PLANNING_START_DATE_ENABLED).check().run()
    assert not app.exception
    assert app.session_state[INITIAL_EQUITY_AUTO] is True
    assert app.session_state[SESSION_INITIAL_EQUITY] == 5000.0

    app.date_input(key=WIDGET_PLANNING_START_DATE).set_value(datetime.date(2024, 1, 1)).run()
    assert not app.exception
    assert app.session_state[SESSION_INITIAL_EQUITY] == 3000.0
    config = SimulationService.get_configuration()
    assert config["planning_start_date"] == "2024-01-01"
    assert config["initial_equity_input"] == 3000.0
    assert config[INITIAL_EQUITY_AUTO] is True

    app.date_input(key=WIDGET_PLANNING_START_DATE).set_value(datetime.date(2025, 1, 1)).run()
    assert not app.exception
    assert app.session_state[SESSION_INITIAL_EQUITY] == 5000.0
    equity_key = f"{WIDGET_INITIAL_EQUITY_DYNAMIC_PREFIX}5000.0"
    assert app.number_input(key=equity_key).value == 5000.0

    app.number_input(key=equity_key).set_value(manual_equity).run()
    assert not app.exception
    assert app.session_state[INITIAL_EQUITY_AUTO] is False
    assert app.session_state[INITIAL_EQUITY_MANUAL_OVERRIDE] is True

    app.date_input(key=WIDGET_PLANNING_START_DATE).set_value(datetime.date(2024, 1, 1)).run()
    assert not app.exception
    config = SimulationService.get_configuration()
    assert config["planning_start_date"] == "2024-01-01"
    assert config["initial_equity_input"] == manual_equity
    assert config[INITIAL_EQUITY_AUTO] is False
    assert config[INITIAL_EQUITY_MANUAL_OVERRIDE] is True
    assert (
        app.number_input(key=f"{WIDGET_INITIAL_EQUITY_DYNAMIC_PREFIX}{manual_equity}").value
        == manual_equity
    )

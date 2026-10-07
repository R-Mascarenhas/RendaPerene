from services.portfolio_read_service import PortfolioReadService
import contextlib
import datetime
import sqlite3

import pandas as pd
import pytest
import streamlit as st

from core.constants import (
    WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX,
    WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX,
    WIDGET_ASSET_ANNUAL_GOAL_PREFIX,
)
from core.daos.planning_dao import PlanningDAO
from core.database import db
from services.assets_service import AssetService
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.cached_market_data import StreamlitCachedPortfolioRepository
from views.components.manual_entry import ManualEntryWidget


@pytest.mark.parametrize("entry_type,kind", [
    ("Compra (Aporte)", "BUY"),
    ("Venda (Resgate)", "SELL"),
    ("Desdobro / Bonificação", "BUY"),
    ("Grupamento", "GROUP"),
    ("Dividendo (Recebimento)", "DIVIDEND"),
    ("JCP (Recebimento)", "JCP"),
    ("Rendimento (FII/Outros)", "YIELD"),
])
def test_bound_form_saves_only_selected_ticker_and_refreshes_projections(mock_db, monkeypatch, entry_type, kind):
    from views.components.manual_entry import MarketData

    today = datetime.date.today()
    AssetService.add_transaction("BBAS3", f"{today.year - 1}-12-31", "Compra", 100, 10)
    monkeypatch.setattr(db, "get_personal_database_path", lambda: mock_db["database_path"])
    monkeypatch.setattr(MarketData, "load_assets_catalog", lambda: pd.DataFrame({"NOME": ["Caixa"]}, index=["CXSE3"]))
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
    monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
    monkeypatch.setattr(st, "success", lambda *a, **kw: None)
    monkeypatch.setattr(st, "form", lambda *a, **kw: contextlib.nullcontext())
    def selectbox(label, options, **kwargs):
        assert label == "Tipo de Lançamento", "The bound form must not offer a ticker selector"
        return entry_type
    monkeypatch.setattr(st, "selectbox", selectbox)
    monkeypatch.setattr(st, "date_input", lambda *a, **kw: today)
    monkeypatch.setattr(st, "number_input", lambda *a, **kw: 2)
    monkeypatch.setattr(st, "form_submit_button", lambda *a, **kw: True)
    reruns = []
    monkeypatch.setattr(st, "rerun", lambda: reruns.append(True))
    state = {
        f"{WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX}testsnapshotpending": True,
        f"{WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX}test": {"edited_rows": {}},
        f"{WIDGET_ASSET_ANNUAL_GOAL_PREFIX}test_error": "stale error",
        f"{WIDGET_ASSET_ANNUAL_GOAL_PREFIX}test_quantity": 150,
    }
    monkeypatch.setattr(st, "session_state", state)
    StreamlitCachedPortfolioRepository._load_ledger.clear()
    PortfolioReadService.set_adapters(repository=StreamlitCachedPortfolioRepository())
    assert PortfolioReadService.read_planning().positions.iloc[0]["quantity"] == 100
    revision = AssetService.get_local_projection_revision()
    ManualEntryWidget().render("BBAS3")
    assert AssetService.get_local_projection_revision() > revision
    assert reruns == [True]
    assert not state
    if kind in {"DIVIDEND", "JCP", "YIELD"}:
        receipt = PortfolioReadService.read_asset("BBAS3").dividends.iloc[0]
        assert receipt["Total"] == 2
        assert PortfolioReadService.read_asset("CXSE3").dividends.empty
        expected_quantity = 100
    else:
        transaction = PortfolioReadService.read_asset("BBAS3").transaction_history.iloc[-1]
        assert transaction["transaction_type"] == kind
        assert PortfolioReadService.read_asset("CXSE3").transaction_history.empty
        expected_quantity = 2 if kind == "GROUP" else 98 if kind == "SELL" else 102
    assert PortfolioReadService.read_planning().positions.iloc[0]["quantity"] == expected_quantity


def test_annual_goal_uses_january_base_and_keeps_other_targets(mock_db, monkeypatch):
    today = datetime.date.today()
    AssetService.add_transaction("BBAS3", f"{today.year - 1}-12-31", "Compra", 100, 10)
    AssetService.add_transaction("BBAS3", today.isoformat(), "Compra", 20, 10)
    AssetService.add_transaction("CXSE3", f"{today.year - 1}-12-31", "Compra", 50, 10)
    service = ShareQuantityGoalService.get_default()
    class Market:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {}
    monkeypatch.setattr(service, "_market_analysis_api", Market())
    service.save_portfolio_goal_plan({"BBAS3": 150, "CXSE3": 80})
    plan = service.get_portfolio_goal_plan(ticker="BBAS3")
    assert plan["rows"].iloc[0]["year_start_quantity"] == 100
    service.save_asset_goal(plan, "BBAS3", service.MODE_PERCENTAGE, 10)
    stored = {row["ticker"]: row for row in PlanningDAO().list_accumulation_goals()}
    assert stored["BBAS3"]["target_quantity"] == 110
    assert stored["CXSE3"]["target_quantity"] == 80
    assert service.get_portfolio_goal_plan()["rows"].set_index("ticker").loc["BBAS3", "target_quantity"] == 110
    service.save_portfolio_goal_plan({"BBAS3": 140, "CXSE3": 80})
    assert service.get_portfolio_goal_plan(ticker="BBAS3")["rows"].iloc[0]["target_quantity"] == 140


def test_individual_goal_without_general_plan_and_zero_baseline(mock_db, monkeypatch):
    AssetService.add_transaction("BBAS3", datetime.date.today().isoformat(), "Compra", 10, 10)
    service = ShareQuantityGoalService.get_default()
    class Market:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {}
    monkeypatch.setattr(service, "_market_analysis_api", Market())
    plan = service.get_portfolio_goal_plan(ticker="BBAS3")
    with pytest.raises(ValueError, match="01/01"):
        service.save_asset_goal(plan, "BBAS3", service.MODE_PERCENTAGE, 10)
    service.set_goal_enabled(False)
    service.save_asset_goal(plan, "BBAS3", service.MODE_QUANTITY, 20)
    assert service.has_saved_goals()
    assert not service.get_goal_enabled()
    with pytest.raises(ValueError):
        service.save_asset_goal(plan, "CXSE3", service.MODE_QUANTITY, 20)
    with pytest.raises(ValueError):
        service.save_asset_goal(plan, "BBAS3", service.MODE_QUANTITY, -1)


def test_manual_entry_persistence_error_does_not_rerun(mock_db, monkeypatch):
    from views.components.manual_entry import MarketData
    monkeypatch.setattr(MarketData, "load_assets_catalog", lambda: pd.DataFrame())
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
    monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
    monkeypatch.setattr(st, "selectbox", lambda *a, **kw: "Compra (Aporte)")
    monkeypatch.setattr(st, "form", lambda *a, **kw: contextlib.nullcontext())
    monkeypatch.setattr(st, "date_input", lambda *a, **kw: datetime.date.today())
    monkeypatch.setattr(st, "number_input", lambda *a, **kw: 2)
    monkeypatch.setattr(st, "form_submit_button", lambda *a, **kw: True)
    errors = []
    monkeypatch.setattr(st, "error", errors.append)
    def fail(*args):
        raise sqlite3.OperationalError("failed")
    monkeypatch.setattr(AssetService, "add_transaction", fail)
    monkeypatch.setattr(st, "rerun", lambda: pytest.fail("A failed save must not rerun"))
    ManualEntryWidget().render("BBAS3")
    assert errors == ["Não foi possível salvar a movimentação. Tente novamente."]


def _render_operations_goal_refresh(action):
    import pandas as pd
    import streamlit as st
    from core.constants import (
        WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX,
        WIDGET_ASSET_ANNUAL_GOAL_PREFIX,
    )
    from views.operations_view import OperationsView

    if not st.session_state.get("test_initialized"):
        st.session_state["test_initialized"] = True
        st.session_state[f"{WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX}testsnapshotpending"] = True
        st.session_state[f"{WIDGET_ASSET_ANNUAL_GOAL_PREFIX}test_error"] = "previous error"
        st.session_state.processed_files = set()
        st.session_state.b3_uploader_key = 0
    if action == "import":
        if st.button("Confirmar importação"):
            OperationsView._process_b3_frame(pd.DataFrame(), "test-import", {})
    else:
        OperationsView()._render_pending_costs()


@pytest.mark.parametrize("action", ["import", "regularize"])
def test_operations_refresh_discards_both_goal_editors(monkeypatch, action):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(AssetService, "process_b3_import", lambda *a, **kw: (1, 0))
    monkeypatch.setattr(AssetService, "get_pending_costs", lambda: pd.DataFrame([{
        "id": 1, "ticker": "BBAS3", "date": "2026-01-02", "quantity": 10,
        "movement": "Aquisição", "institution": "Test",
    }]))
    monkeypatch.setattr(AssetService, "regularize_cost", lambda *a, **kw: True)
    app = AppTest.from_function(
        _render_operations_goal_refresh, args=(action,), default_timeout=30
    ).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert f"{WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX}testsnapshotpending" not in app.session_state
    assert f"{WIDGET_ASSET_ANNUAL_GOAL_PREFIX}test_error" not in app.session_state
    assert app.session_state["test_initialized"] is True


def _render_goal_screens():
    import streamlit as st
    from views.components.asset_annual_goal import AssetAnnualGoalWidget
    from views.goals_view import GoalsView

    screen = st.selectbox("Tela", ["Detalhamento", "Metas"])
    if screen == "Detalhamento":
        AssetAnnualGoalWidget().render("BBAS3")
    else:
        GoalsView().render()


def _submit_goal_table_edit(app, target):
    import json
    from streamlit.proto.WidgetStates_pb2 import WidgetStates

    states = WidgetStates()
    state = states.widgets.add()
    state.id = app.dataframe[0].proto.id
    state.string_value = json.dumps({
        "edited_rows": {"0": {"target_quantity": target}},
        "added_rows": [],
        "deleted_rows": [],
    })
    app._run(states)
    assert not app.exception


def test_native_goal_form_synchronizes_with_goals_tab_without_enabled_plan(mock_db, monkeypatch):
    from streamlit.testing.v1 import AppTest

    year = datetime.date.today().year
    AssetService.add_transaction("BBAS3", f"{year - 1}-12-31", "Compra", 100, 10)
    service = ShareQuantityGoalService.get_default()
    class Market:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {"current_price": 10, "avg_dividend_5y": 2}
    monkeypatch.setattr(service, "_market_analysis_api", Market())
    service.set_goal_enabled(False)
    app = AppTest.from_function(_render_goal_screens, default_timeout=30).run()
    assert not app.exception
    assert not PlanningDAO().list_accumulation_goals()
    assert not app.button
    assert len(app.number_input) == 2
    assert not app.number_input[1].disabled
    app.number_input[1].set_value(20).run()
    assert not app.exception
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 120
    app.selectbox[0].set_value("Metas").run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["target_quantity"] == 120
    _submit_goal_table_edit(app, 150)
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 150
    app.selectbox[0].set_value("Detalhamento").run()
    assert not app.exception
    assert app.number_input[0].value == 150
    assert app.number_input[1].value == 50
    app.number_input[0].set_value(160).run()
    assert not app.exception
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 160
    assert app.number_input[1].value == 60
    app.number_input[1].set_value(0).run()
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 100
    assert app.number_input[0].value == 100
    app.number_input[1].set_value(-100).run()
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 0
    assert app.number_input[0].value == 0


def test_native_goal_percentage_is_explained_when_january_baseline_is_zero(mock_db, monkeypatch):
    from streamlit.testing.v1 import AppTest

    AssetService.add_transaction("BBAS3", datetime.date.today().isoformat(), "Compra", 10, 10)
    service = ShareQuantityGoalService.get_default()
    class Market:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {}
    monkeypatch.setattr(service, "_market_analysis_api", Market())
    service.set_goal_enabled(False)
    app = AppTest.from_function(_render_goal_screens, default_timeout=30).run()
    assert not app.exception
    assert app.number_input[1].disabled
    assert any("01/01" in info.value for info in app.info)
    assert not any("percentuais negativos" in caption.value for caption in app.caption)
    app.number_input[0].set_value(25).run()
    assert not app.exception
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 25


@pytest.mark.parametrize("save_error", [
    ValueError("Meta inválida."),
    RuntimeError("private storage details"),
    sqlite3.OperationalError("private database details"),
])
def test_native_goal_autosave_failure_preserves_target_and_allows_retry(
    mock_db, monkeypatch, save_error
):
    from streamlit.testing.v1 import AppTest

    year = datetime.date.today().year
    AssetService.add_transaction("BBAS3", f"{year - 1}-12-31", "Compra", 100, 10)
    service = ShareQuantityGoalService.get_default()
    class Market:
        @staticmethod
        def get_ticker_market_analysis(ticker):
            return {}
    monkeypatch.setattr(service, "_market_analysis_api", Market())
    service.set_goal_enabled(False)
    service.save_portfolio_goal_plan({"BBAS3": 150})
    app = AppTest.from_function(_render_goal_screens, default_timeout=30).run()
    snapshot_key = f"{WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX}testsnapshot"
    app.session_state[snapshot_key] = {"saved_target": 150}
    def fail(goals):
        raise save_error
    with monkeypatch.context() as patch:
        patch.setattr(service._goal_repo, "upsert_accumulation_goals", fail)
        app.number_input[0].set_value(160).run()
    assert not app.exception
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 150
    assert app.number_input[0].value == 150
    assert app.number_input[1].value == 50
    assert app.error[0].value == (
        str(save_error) if isinstance(save_error, ValueError)
        else "Não foi possível salvar a meta. Tente novamente."
    )
    assert app.session_state[snapshot_key] == {"saved_target": 150}
    app.number_input[0].set_value(160).run()
    assert not app.exception
    assert not app.error
    assert PlanningDAO().list_accumulation_goals()[0]["target_quantity"] == 160
    assert app.number_input[0].value == 160
    assert app.number_input[1].value == 60
    assert snapshot_key not in app.session_state


def _render_bound_manual_form():
    from views.components.manual_entry import ManualEntryWidget
    ManualEntryWidget().render("BBAS3")


def test_native_bound_form_refreshes_after_purchase(mock_db, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from views.components.manual_entry import MarketData
    monkeypatch.setattr(MarketData, "load_assets_catalog", lambda: pd.DataFrame())
    app = AppTest.from_function(_render_bound_manual_form).run()
    assert not app.exception
    assert len(app.selectbox) == 1
    app.number_input[0].set_value(5)
    app.number_input[1].set_value(20)
    app.number_input[2].set_value(1)
    app.button[0].click().run()
    assert not app.exception
    position = PortfolioReadService.read_planning().positions.iloc[0]
    assert position["ticker"] == "BBAS3"
    assert position["quantity"] == 5
    assert position["average_price"] == pytest.approx(20.2)
    assert PortfolioReadService.read_planning(year=datetime.date.today().year).ytd_contributions == 101
    assert len(AssetService.get_portfolio_activity()) == 1

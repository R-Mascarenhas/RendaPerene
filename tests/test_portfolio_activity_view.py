import pandas as pd
import streamlit as st

from services.assets_service import AssetService


def test_activity_table_formats_values_and_empty_state(monkeypatch):
    from views.components.portfolio_activity import PortfolioActivityWidget

    tables, messages = [], []
    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: tables.append(data.data))
    monkeypatch.setattr(st, "info", messages.append)
    widget = PortfolioActivityWidget()
    widget.render()
    assert messages == ["Nenhuma movimentação registrada nesta carteira."]
    assert not tables

    AssetService.add_transaction("BBAS3", "2026-01-01", "BUY", 10, 20, 2)
    AssetService.add_dividend("BBAS3", "2026-01-02", "JCP", 12)
    widget.render(limit=None)
    assert tables[0].columns.tolist() == ["Data", "Evento", "Ticker", "Quantidade", "Valor"]
    assert tables[0]["Data"].tolist() == ["02/01/2026", "01/01/2026"]
    assert tables[0]["Valor"].tolist() == ["R$ 12,00", "R$ 202,00"]
    assert tables[0]["Quantidade"].tolist() == ["10 (estimada)", "10"]


def test_activity_read_error_does_not_claim_empty_history(monkeypatch):
    from views.components.portfolio_activity import PortfolioActivityWidget

    messages, empty = [], []
    def fail(*args, **kwargs):
        raise RuntimeError("private database details")

    monkeypatch.setattr(AssetService, "get_portfolio_activity", fail)
    monkeypatch.setattr(st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(st, "error", messages.append)
    monkeypatch.setattr(st, "info", empty.append)
    PortfolioActivityWidget().render()
    assert messages == ["Não foi possível carregar as movimentações. Tente novamente."]
    assert not empty


def test_dashboard_shows_activity_without_current_positions(monkeypatch):
    from views.dashboard_view import DashboardView
    from views.components.portfolio_activity import PortfolioActivityWidget
    from views.components.annual_planning import AnnualPlanningWidget
    from views.components.accumulation_goals import AccumulationGoalProgressWidget
    from services.portfolio_read_service import PortfolioReadService
    from core.portfolio_read import PortfolioOverview

    rendered = []
    monkeypatch.setattr(PortfolioReadService, "read_portfolio", lambda **kw: PortfolioOverview(pd.DataFrame(), {}, pd.DataFrame(), {}, pd.DataFrame(), ()))
    monkeypatch.setattr(AnnualPlanningWidget, "render", lambda *args: None)
    monkeypatch.setattr(AccumulationGoalProgressWidget, "render", lambda *args: None)
    monkeypatch.setattr(PortfolioActivityWidget, "render", lambda *args, **kwargs: rendered.append(True))
    DashboardView().render()
    assert rendered == [True]


def test_recent_history_button_opens_operations_and_all_events():
    from streamlit.testing.v1 import AppTest

    for day in range(1, 13):
        AssetService.add_dividend("BBAS3", f"2026-01-{day:02}", "DIVIDEND", 12)

    app = AppTest.from_string('''
import streamlit as st
from unittest.mock import patch
from core.constants import WIDGET_MAIN_NAVIGATION
from core.strings import TAB_DASHBOARD, TAB_ASSETS, TAB_PLANNING
from views.assets_view import AssetsView
from views.operations_view import OperationsView
from views.components.portfolio_activity import PortfolioActivityWidget

selected = st.segmented_control(
    "Navegação Principal", [TAB_DASHBOARD, TAB_ASSETS, TAB_PLANNING],
    default=TAB_DASHBOARD, key=WIDGET_MAIN_NAVIGATION,
)
if selected == TAB_DASHBOARD:
    PortfolioActivityWidget().render()
elif selected == TAB_ASSETS:
    with patch.object(OperationsView, "_render_unified_manual_form"), \\
         patch.object(OperationsView, "_render_b3_import_zone"), \\
         patch.object(OperationsView, "_render_pending_costs"):
        AssetsView().render()
''').run(timeout=15)

    assert not app.exception
    assert len(app.dataframe[0].value) == 10
    app.button(key="open_operations_history").click().run(timeout=15)
    assert not app.exception
    assert app.subheader[0].value == "Histórico de movimentações"
    assert len(app.dataframe[0].value) == 12
    assert app.dataframe[0].value.iloc[0]["Data"] == "12/01/2026"


def test_activity_table_shows_pending_cost_instead_of_zero(monkeypatch):
    from views.components.portfolio_activity import PortfolioActivityWidget

    AssetService.process_b3_import(pd.DataFrame([{
        "Data": "01/01/2026", "Movimentação": "Aquisição", "Produto": "BBAS3",
        "Quantidade": 10, "Preço unitário": 0, "Valor da Operação": 0,
        "Entrada/Saída": "Crédito",
    }]))
    tables = []
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: tables.append(data.data))
    PortfolioActivityWidget().render(limit=None)
    assert tables[0].iloc[0]["Valor"] == "Custo pendente"


def test_receipt_table_distinguishes_reported_estimated_and_unknown_quantities(monkeypatch):
    from views.components.portfolio_activity import PortfolioActivityWidget

    AssetService.add_dividend("BBAS3", "2026-01-01", "DIVIDEND", 10, quantity=0.5, unit_price=20)
    AssetService.add_dividend("BBAS3", "2026-01-02", "JCP", 10, unit_price=0.125)
    AssetService.add_dividend("CXSE3", "2026-01-03", "YIELD", 10)
    tables = []
    monkeypatch.setattr(st, "dataframe", lambda data, **kwargs: tables.append(data.data))
    PortfolioActivityWidget().render(limit=None)
    assert tables[0]["Quantidade"].tolist() == ["—", "80 (estimada)", "0,5"]

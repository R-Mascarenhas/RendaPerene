import datetime

import pytest

from services.assets_service import AssetService


def test_history_pages_preserve_order_and_filter_before_limiting():
    for day in range(1, 29):
        AssetService.add_dividend("BBAS3", f"2026-01-{day:02}", "JCP", day, quantity=10)
    AssetService.add_dividend("CXSE3", "2026-01-28", "DIVIDEND", 100, quantity=5)
    first = AssetService.get_activity_page()
    second = AssetService.get_activity_page(page=2)
    assert first["total"] == 29
    assert first["pages"] == 2
    assert len(first["activity"]) == 25
    assert len(second["activity"]) == 4
    assert second["activity"]["date"].tolist() == [
        "2026-01-04", "2026-01-03", "2026-01-02", "2026-01-01"
    ]
    filtered = AssetService.get_activity_page(
        start_date=datetime.date(2026, 1, 2), end_date=datetime.date(2026, 1, 4),
        event="JCP", ticker=" bbas3 ", page=2,
    )
    assert filtered["total"] == 3
    assert filtered["page"] == 1
    assert filtered["activity"]["value"].tolist() == [4, 3, 2]
    assert AssetService.get_activity_page(ticker="ABCD3")["total"] == 0
    assert AssetService.get_activity_filter_options()["tickers"] == ["BBAS3", "CXSE3"]


@pytest.mark.parametrize("kwargs", [
    {"page": 0}, {"page": True}, {"event": "bogus"},
    {"start_date": "bad"}, {"start_date": "2026-02-01", "end_date": "2026-01-01"},
])
def test_history_rejects_invalid_filters(kwargs):
    with pytest.raises(ValueError):
        AssetService.get_activity_page(**kwargs)


def test_history_filters_corporate_events_and_sold_tickers():
    import pandas as pd

    AssetService.process_b3_import(pd.DataFrame([
        {"Data": "01/01/2026", "Movimentação": movement, "Produto": "BBAS3",
         "Quantidade": quantity, "Preço unitário": 0, "Valor da Operação": 0,
         "Entrada/Saída": "Crédito"}
        for movement, quantity in [("Desdobro", 10), ("Bonificação em Ativos", 2)]
    ]))
    AssetService.add_transaction("BBAS3", "2026-01-02", "BUY", 1, 0)
    AssetService.add_transaction("CXSE3", "2026-01-01", "BUY", 1, 10)
    AssetService.add_transaction("CXSE3", "2026-01-02", "SELL", 1, 11)
    for event in ("Desdobro", "Bonificação", "Desdobro / Bonificação"):
        result = AssetService.get_activity_page(event=event)
        assert result["total"] == 1
        assert result["activity"]["event"].tolist() == [event]
    assert "CXSE3" in AssetService.get_activity_filter_options()["tickers"]
    assert AssetService.get_activity_page(event="Compra")["activity"]["ticker"].tolist() == ["CXSE3"]


def test_history_pages_have_no_duplicates_for_same_day_ties_and_reflect_new_records():
    for value in range(1, 28):
        AssetService.add_dividend("ABCD3", "2026-01-01", "JCP", value, quantity=10)
    AssetService.add_transaction("ABCD3", "2026-01-01", "BUY", 1, 10)
    first = AssetService.get_activity_page()
    second = AssetService.get_activity_page(page=2)
    assert first["activity"]["event"].iloc[0] == "Compra"
    assert first["activity"]["value"].iloc[1:].tolist() == list(range(27, 3, -1))
    assert second["activity"]["value"].tolist() == [3, 2, 1]
    AssetService.add_dividend("ABCD3", "2026-02-01", "JCP", 100, quantity=10)
    assert AssetService.get_activity_page()["activity"].iloc[0]["value"] == 100


def test_history_pages_and_options_use_only_the_active_portfolio(tmp_path):
    from core.database import DatabaseManager
    from core.daos.portfolio_dao import PortfolioDAO

    repos = []
    for name, ticker in [("one.db", "BBAS3"), ("two.db", "CXSE3")]:
        manager = DatabaseManager(tmp_path / name)
        manager.init_personal_db()
        repo = PortfolioDAO(manager)
        service = AssetService(portfolio_repo=repo)
        service.add_dividend(ticker, "2026-01-01", "JCP", 10, quantity=10)
        repos.append((repo, ticker))
    for repo, ticker in [*repos, repos[0]]:
        AssetService.set_adapters(portfolio_repo=repo)
        assert AssetService.get_activity_page()["activity"]["ticker"].tolist() == [ticker]
        assert AssetService.get_activity_filter_options()["tickers"] == [ticker]


def test_history_ui_navigates_resets_filters_and_handles_invalid_period():
    from streamlit.testing.v1 import AppTest

    for day in range(1, 29):
        AssetService.add_dividend("BBAS3", f"2026-01-{day:02}", "JCP", day, quantity=10)
    AssetService.add_dividend("CXSE3", "2026-01-28", "DIVIDEND", 100, quantity=5)
    app = AppTest.from_string('''
import streamlit as st
from views.components.portfolio_activity import PortfolioActivityWidget
st.selectbox("Carteira", ["first.db", "second.db"], key="active_db")
PortfolioActivityWidget().render_history()
''').run(timeout=30)
    assert not app.exception
    assert len(app.dataframe[0].value) == 25
    assert app.button(key="activity_history_previous").disabled
    app.button(key="activity_history_next").click().run(timeout=30)
    assert not app.exception
    assert len(app.dataframe[0].value) == 4
    assert app.button(key="activity_history_next").disabled
    app.selectbox(key="activity_history_ticker").select("CXSE3").run(timeout=30)
    assert not app.exception
    assert app.session_state["activity_history_page"] == 1
    assert app.dataframe[0].value["Ticker"].tolist() == ["CXSE3"]
    app.selectbox(key="activity_history_event").select("JCP").run(timeout=30)
    assert not app.exception
    assert app.info[0].value == "Nenhuma movimentação encontrada para os filtros selecionados."
    app.selectbox(key="active_db").select("second.db").run(timeout=30)
    assert not app.exception
    assert app.selectbox(key="activity_history_ticker").value is None
    assert app.selectbox(key="activity_history_event").value is None
    app.date_input(key="activity_history_start").set_value(datetime.date(2026, 2, 1))
    app.date_input(key="activity_history_end").set_value(datetime.date(2026, 1, 1)).run(timeout=30)
    assert not app.exception
    assert app.warning[0].value == "A data inicial deve ser anterior ou igual à data final."
    app.date_input(key="activity_history_start").set_value(datetime.date(2026, 1, 1)).run(timeout=30)
    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    app.date_input(key="activity_history_start").set_value(datetime.date(2000, 1, 1)).run(timeout=30)
    assert not app.exception
    assert len(app.dataframe[0].value) == 1

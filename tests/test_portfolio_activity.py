from services.portfolio_read_service import PortfolioReadService
import pandas as pd
import pytest

from services.assets_service import AssetService


def test_activity_combines_sources_orders_and_limits_without_changing_contributions():
    AssetService.add_transaction("BBAS3", "2026-01-01", "BUY", 10, 20, 2)
    AssetService.add_transaction("BBAS3", "2026-01-03", "SELL", 2, 25, 1)
    AssetService.add_dividend("BBAS3", "2026-01-02", "DIVIDEND", 12)
    before = PortfolioReadService.read_planning(year=2026).ytd_contributions

    activity = AssetService.get_portfolio_activity()

    assert activity["event"].tolist() == ["Venda", "Dividendo", "Compra"]
    assert activity["ticker"].tolist() == ["BBAS3"] * 3
    assert activity["value"].tolist() == [49, 12, 202]
    assert activity.iloc[1]["quantity"] == 10
    assert activity.iloc[1]["quantity_status"] == "estimated"
    assert AssetService.get_portfolio_activity(limit=2).equals(activity.head(2))
    assert PortfolioReadService.read_planning(year=2026).ytd_contributions == before


def test_activity_preserves_corporate_custody_and_pending_cost_semantics():
    movements = []
    for day, kind, quantity in [
        ("01/01/2026", "Aquisição", 10),
        ("02/01/2026", "Desdobro", 10),
        ("03/01/2026", "Bonificação em Ativos", 2),
        ("04/01/2026", "Transferência", 30),
    ]:
        movements.append({
            "Data": day, "Movimentação": kind, "Produto": "BBAS3",
            "Quantidade": quantity, "Preço unitário": 0, "Valor da Operação": 0,
            "Entrada/Saída": "Crédito",
        })
    AssetService.process_b3_import(pd.DataFrame(movements))
    AssetService.add_transaction("BBAS3", "2026-01-05", "GROUP", 5, 0)
    AssetService.add_transaction("BBAS3", "2026-01-06", "BUY", 3, 0)

    activity = AssetService.get_portfolio_activity(limit=None)

    assert activity["event"].tolist() == [
        "Desdobro / Bonificação", "Grupamento", "Transferência recebida",
        "Bonificação", "Desdobro", "Compra",
    ]
    assert activity["quantity"].tolist() == [3, 5, 30, 2, 10, 10]
    assert activity["value_status"].tolist() == [
        "known", "known", "not_applicable", "known", "known", "pending",
    ]
    assert activity.iloc[[0, 1, 3, 4]]["value"].tolist() == [0, 0, 0, 0]
    assert pd.isna(activity.iloc[2]["value"])
    assert pd.isna(activity.iloc[5]["value"])

    pending_id = int(AssetService.get_pending_costs().iloc[0]["id"])
    assert AssetService.regularize_cost(pending_id, 20, fees=2)
    updated = AssetService.get_portfolio_activity(limit=None)
    assert updated.iloc[-1]["value"] == 202
    assert updated.iloc[-1]["value_status"] == "known"


def test_activity_empty_full_history_limit_and_stable_ties():
    assert AssetService.get_portfolio_activity().empty
    for day in range(1, 13):
        AssetService.add_dividend("ABCD3", f"2026-01-{day:02}", "JCP", day)
    AssetService.add_dividend("ABCD3", "2026-01-12", "YIELD", 15)
    AssetService.add_transaction("ABCD3", "2026-01-12", "BUY", 1, 10)
    AssetService.add_transaction("ABCD3", "2026-01-12", "SELL", 1, 12)

    recent = AssetService.get_portfolio_activity()
    assert len(recent) == 10
    assert recent["event"].head(4).tolist() == ["Venda", "Compra", "Rendimento", "JCP"]
    assert len(AssetService.get_portfolio_activity(limit=None)) == 15
    assert AssetService.get_portfolio_activity(limit=0).empty
    assert AssetService.get_portfolio_activity().equals(recent)


@pytest.mark.parametrize("limit", [-1, 1.5, True, "10"])
def test_activity_rejects_invalid_limits(limit):
    with pytest.raises(ValueError):
        AssetService.get_portfolio_activity(limit=limit)


def test_activity_isolates_portfolios_after_switching_the_active_adapter(tmp_path):
    from core.database import DatabaseManager
    from core.daos.portfolio_dao import PortfolioDAO

    portfolios = []
    for filename, ticker in [("first.db", "BBAS3"), ("second.db", "CXSE3")]:
        manager = DatabaseManager(tmp_path / filename)
        manager.init_personal_db()
        repo = PortfolioDAO(manager)
        service = AssetService(portfolio_repo=repo)
        service.add_transaction(ticker, "2026-01-01", "BUY", 1, 10)
        service.add_dividend(ticker, "2026-01-02", "DIVIDEND", 2)
        portfolios.append((repo, ticker))

    for repo, ticker in [*portfolios, portfolios[0]]:
        AssetService.set_adapters(portfolio_repo=repo)
        history = AssetService.get_portfolio_activity(limit=None)
        assert history["ticker"].tolist() == [ticker, ticker]
        assert history["event"].tolist() == ["Dividendo", "Compra"]

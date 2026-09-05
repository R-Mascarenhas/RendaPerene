import json
import sqlite3
from contextlib import closing

import pandas as pd
import pytest

from core.daos.portfolio_dao import PortfolioDAO
from core.utils.b3_parser import B3ExcelParserAdapter
from services.assets_service import AssetService


def movement(
    kind="Aquisição", date="02/01/2024", quantity=100, value=None, price=None, direction="Crédito"
):
    return {
        "Movimentação": kind,
        "Data": date,
        "Produto": "BBAS3",
        "Quantidade": quantity,
        "Preço unitário": price,
        "Valor da Operação": value,
        "Entrada/Saída": direction,
    }


@pytest.mark.parametrize("missing", [None, float("nan"), "-", "", 0])
def test_acquisition_without_value_remains_visible_and_pending(missing):
    assert AssetService.process_b3_import(pd.DataFrame([movement(value=missing, price=20)])) == (
        1,
        0,
    )
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 100
    assert position["cost_pending"]
    assert pd.isna(position["average_price"])
    assert pd.isna(position["invested_amount"])
    assert len(AssetService.get_pending_costs()) == 1


@pytest.mark.parametrize("total_mode,value", [(False, 20), (True, 2000)])
def test_regularization_replays_costs_after_sale_and_reimport(total_mode, value, monkeypatch):
    frame = pd.DataFrame([movement(), movement("Venda", "03/01/2024", 40, 1200, 30, "Débito")])
    AssetService.process_b3_import(frame)
    pending = AssetService.get_pending_costs().iloc[0]
    source = pending["source_record"]
    assert json.loads(source)["movement"] == "Aquisição"
    assert AssetService.regularize_cost(
        int(pending["id"]), value, value_is_total=total_mode, fees=10
    )
    assert AssetService.process_b3_import(frame.iloc[::-1]) == (0, 0)
    assert AssetService.get_pending_costs().empty
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 60
    assert position["average_price"] == pytest.approx(20.1)
    assert position["invested_amount"] == pytest.approx(1206)
    assert not position["cost_pending"]
    monkeypatch.setattr(
        AssetService.get_default()._market_data_api,
        "get_batch_quotes",
        lambda tickers: {"BBAS3": 30},
    )
    positions, _ = AssetService.get_portfolio_summary_metrics(AssetService.calculate_positions())
    assert positions.iloc[0]["profit_loss"] == pytest.approx(594)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert (
            conn.execute(
                "SELECT source_record FROM b3_import_records WHERE transaction_id=?",
                (int(pending["id"]),),
            ).fetchone()[0]
            == source
        )


@pytest.mark.parametrize(
    "history",
    [
        [],
        [movement("Aquisição", "01/01/2024")],
        [movement("Desdobramento", "01/01/2024")],
        [movement("Grupamento", "01/01/2024")],
        [movement("Compra", "03/01/2024", value=2000, price=20)],
        [movement("Compra", "01/01/2024", quantity=50, value=1000, price=20)],
        [
            movement("Compra", "01/01/2024", value=2000, price=20),
            movement("Venda", "01/01/2024", value=2000, price=20),
        ],
    ],
)
def test_transfer_needs_sufficient_prior_cost(history):
    frame = pd.DataFrame([movement("Transferência")] + history)
    AssetService.process_b3_import(frame)
    pending = AssetService.get_pending_costs()
    assert any(
        json.loads(source)["movement"] == "Transferência" for source in pending["source_record"]
    )
    assert AssetService.process_b3_import(frame) == (0, 0)


def test_transfer_ignored_with_chronological_history_and_stays_ignored():
    frame = pd.DataFrame(
        [movement("Transferência"), movement("Compra", "01/01/2024", value=2000, price=20)]
    )
    assert AssetService.process_b3_import(frame) == (1, 0)
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 100
    assert position["invested_amount"] == 2000
    assert AssetService.get_pending_costs().empty
    AssetService.add_transaction("BBAS3", "2024-01-03", "SELL", 100, 30)
    assert AssetService.process_b3_import(frame) == (0, 0)
    assert AssetService.calculate_positions().empty


def test_same_day_custody_pair_is_ignored_without_cost_history():
    frame = pd.DataFrame(
        [
            movement("Transferência", direction="Débito"),
            movement("Transferência", direction="Crédito"),
        ]
    )
    assert AssetService.process_b3_import(frame) == (0, 0)
    assert AssetService.calculate_positions().empty
    assert AssetService.get_pending_costs().empty
    assert AssetService.process_b3_import(frame.iloc[::-1]) == (0, 0)


def test_transfer_liquidation_without_value_is_pending_acquisition():
    frame = pd.DataFrame([movement("Transferência - Liquidação")])
    transactions, _ = B3ExcelParserAdapter().parse_b3_excel(frame)
    parsed = transactions.iloc[0]
    assert parsed["event_kind"] == "TRADE"
    assert parsed["transaction_type"] == "BUY"
    assert parsed["cost_status"] == "PENDING"
    assert not parsed["matched_custody_transfer"]
    assert AssetService.process_b3_import(frame) == (1, 0)
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 100
    assert position["cost_pending"]


def test_transfer_liquidation_with_value_is_regular_trade():
    frame = pd.DataFrame([movement("Transferência - Liquidação", value=2000, price=20)])
    transactions, _ = B3ExcelParserAdapter().parse_b3_excel(frame)
    parsed = transactions.iloc[0]
    assert parsed["event_kind"] == "TRADE"
    assert parsed["cost_status"] == "KNOWN"
    assert AssetService.process_b3_import(frame) == (1, 0)
    position = AssetService.calculate_positions().iloc[0]
    assert position["average_price"] == 20
    assert not position["cost_pending"]


@pytest.mark.parametrize(
    "kind", ["Bonificação em Ativos", "Desdobro", "Desdobramento", "Grupamento"]
)
def test_corporate_events_preserve_known_cost(kind):
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 100, 20, 10)
    AssetService.process_b3_import(pd.DataFrame([movement(kind, quantity=50)]))
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == (50 if kind == "Grupamento" else 150)
    assert position["invested_amount"] == pytest.approx(2010)
    assert not position["cost_pending"]


@pytest.mark.parametrize(
    "value,fees",
    [(0, 0), (-1, 0), (float("nan"), 0), (float("inf"), 0), (20, -1), (20, float("inf"))],
)
def test_regularization_rejects_invalid_cost(value, fees):
    AssetService.process_b3_import(pd.DataFrame([movement()]))
    identifier = int(AssetService.get_pending_costs().iloc[0]["id"])
    with pytest.raises(ValueError):
        AssetService.regularize_cost(identifier, value, fees=fees)
    assert len(AssetService.get_pending_costs()) == 1


def test_schema_migration_is_idempotent_and_preserves_legacy_cost():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, date TEXT, ticker TEXT, transaction_type TEXT, quantity INTEGER, unit_price REAL, fees REAL)"
    )
    conn.execute("INSERT INTO transactions VALUES (1, '2024-01-01', 'BBAS3', 'BUY', 100, 20, 5)")
    dao = PortfolioDAO()
    dao.initialize_tables(conn)
    dao.initialize_tables(conn)
    assert conn.execute("SELECT unit_price, fees, cost_status FROM transactions").fetchone() == (
        20,
        5,
        "KNOWN",
    )
    conn.close()


def test_import_adopts_matching_legacy_transaction():
    AssetService.add_transaction("BBAS3", "2024-01-02", "BUY", 100, 0)
    frame = pd.DataFrame([movement()])
    assert AssetService.process_b3_import(frame) == (0, 0)
    assert AssetService.calculate_positions().iloc[0]["quantity"] == 100
    assert len(AssetService.get_pending_costs()) == 1


def test_regularized_transfer_is_not_a_new_contribution():
    frame = pd.DataFrame([movement("Transferência")])
    AssetService.process_b3_import(frame)
    identifier = int(AssetService.get_pending_costs().iloc[0]["id"])
    assert AssetService.regularize_cost(identifier, 20, fees=10)
    assert AssetService.get_ytd_contributions(2024) == 0
    assert AssetService.get_monthly_contributions_by_year().empty
    assert AssetService.calculate_historical_evolution().iloc[-1]["cumulative_invested"] == 0
    assert (
        AssetService.get_raw_transactions_for_chart("BBAS3").iloc[0]["transaction_type"]
        == "TRANSFER_IN"
    )
    assert (
        AssetService.get_asset_transactions("BBAS3").iloc[0]["Operação"] == "Transferência recebida"
    )
    assert AssetService.process_b3_import(frame) == (0, 0)
    assert AssetService.calculate_positions().iloc[0]["invested_amount"] == pytest.approx(2010)


def test_corporate_event_does_not_turn_unknown_cost_into_known_cost():
    frame = pd.DataFrame(
        [
            movement("Compra", "01/01/2024", value=2000, price=20),
            movement("Aquisição", "02/01/2024"),
            movement("Desdobro", "03/01/2024", quantity=200),
            movement("Transferência", "04/01/2024", quantity=250),
        ]
    )
    AssetService.process_b3_import(frame)
    assert len(AssetService.get_pending_costs()) == 2


def test_pending_cost_hides_portfolio_profit_and_holdings_metrics(monkeypatch):
    AssetService.process_b3_import(pd.DataFrame([movement()]))
    api = AssetService.get_default()._market_data_api
    monkeypatch.setattr(api, "get_batch_quotes", lambda tickers: {"BBAS3": 30})
    monkeypatch.setattr(api, "get_ticker_market_analysis", lambda *args, **kwargs: {})
    positions, metrics = AssetService.get_portfolio_summary_metrics(
        AssetService.calculate_positions()
    )
    assert metrics["total_equity"] == 3000
    assert metrics["cost_pending"]
    assert pd.isna(metrics["overall_return"])
    display, _ = AssetService.get_detailed_holdings_dataframe(positions, 6)
    from core.strings import DISPLAY_AVG_PRICE, DISPLAY_INVESTED, DISPLAY_RETURN_PCT

    assert display.iloc[0][DISPLAY_AVG_PRICE] == "Custo pendente"
    assert display.iloc[0][DISPLAY_INVESTED] == "Custo pendente"
    assert display.iloc[0][DISPLAY_RETURN_PCT] == "Custo pendente"


@pytest.mark.parametrize("mode,value", [("Preço unitário", 20), ("Valor total da aquisição", 2000)])
def test_pending_cost_form_regularizes_operation(mode, value):
    from streamlit.testing.v1 import AppTest

    AssetService.process_b3_import(pd.DataFrame([movement()]))

    def script():
        from views.operations_view import OperationsView

        OperationsView()._render_pending_costs()

    app = AppTest.from_function(script).run()
    assert not app.exception
    assert app.warning
    app.selectbox[1].select(mode)
    app.number_input[0].set_value(value)
    app.number_input[1].set_value(10)
    app.button[0].click().run()
    assert not app.exception
    assert AssetService.get_pending_costs().empty
    assert AssetService.calculate_positions().iloc[0]["average_price"] == pytest.approx(20.1)

import json
import sqlite3
from contextlib import closing

import pandas as pd
import pytest

from core.daos.portfolio_dao import PortfolioDAO
from core.utils.b3_parser import B3ExcelParserAdapter
from services.assets_service import AssetService
from services.planning_service import SimulationService


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


def test_pending_trade_withholds_contribution_totals():
    AssetService.process_b3_import(pd.DataFrame([movement()]))

    assert AssetService.get_ytd_contributions(2024) is None
    assert AssetService.get_monthly_contributions_by_year().empty


def test_pending_trade_withholds_historical_investment_evolution():
    AssetService.process_b3_import(pd.DataFrame([movement()]))
    AssetService.add_transaction("BBAS3", "2024-02-01", "SELL", 10, 25)

    assert AssetService.calculate_historical_evolution().empty


def test_reimport_with_known_cost_reconciles_pending_b3_purchase():
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)
    assert len(AssetService.get_pending_costs()) == 1

    assert AssetService.process_b3_import(pd.DataFrame([movement(value=2000, price=20)])) == (0, 0)
    assert AssetService.process_b3_import(pd.DataFrame([movement(value=2000, price=20)])) == (0, 0)
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (0, 0)

    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 100
    assert position["average_price"] == pytest.approx(20)
    assert not position["cost_pending"]
    assert AssetService.get_pending_costs().empty
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_reimport_with_known_cost_preserves_manual_b3_correction():
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)
    pending_id = int(AssetService.get_pending_costs().iloc[0]["id"])
    assert AssetService.regularize_cost(pending_id, 15)

    assert AssetService.process_b3_import(pd.DataFrame([movement(value=2000, price=20)])) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        transaction = conn.execute(
            "SELECT unit_price, cost_status FROM transactions WHERE id=?", (pending_id,)
        ).fetchone()
        assert transaction == (15.0, "CORRECTED")
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_reimport_with_accent_variant_reconciles_pending_b3_purchase():
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)
    assert AssetService.process_b3_import(
        pd.DataFrame([movement(value=2000, price=20, direction="Credito")])
    ) == (0, 0)
    assert AssetService.calculate_positions().iloc[0]["quantity"] == 100


def test_same_day_known_b3_trades_with_distinct_costs_remain_separate():
    first = movement(value=2000, price=20)
    second = movement(value=3000, price=30)

    assert AssetService.process_b3_import(pd.DataFrame([first, second])) == (2, 0)

    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 200
    assert position["invested_amount"] == pytest.approx(5000)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_partial_export_reuses_known_trade_identity():
    full_frame = pd.DataFrame([movement(value=2000, price=20), movement(value=3000, price=30)])
    partial_frame = pd.DataFrame([movement(value=3000, price=30)])

    assert AssetService.process_b3_import(full_frame) == (2, 0)
    assert AssetService.process_b3_import(partial_frame) == (0, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_pending_occurrences_align_with_divergent_known_costs():
    pending_frame = pd.DataFrame([movement(), movement()])
    known_frame = pd.DataFrame([movement(value=2000, price=20), movement(value=3000, price=30)])

    assert AssetService.process_b3_import(pending_frame) == (2, 0)
    assert AssetService.process_b3_import(known_frame) == (0, 0)
    assert AssetService.get_pending_costs().empty
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 200
    assert position["invested_amount"] == pytest.approx(5000)


def test_partial_known_cost_targets_remaining_pending_operation():
    pending_frame = pd.DataFrame([movement(), movement()])
    assert AssetService.process_b3_import(pending_frame) == (2, 0)
    first_pending_id = int(AssetService.get_pending_costs().iloc[0]["id"])
    assert AssetService.regularize_cost(first_pending_id, 15)

    assert AssetService.process_b3_import(pd.DataFrame([movement(value=3000, price=30)])) == (0, 0)
    assert AssetService.get_pending_costs().empty
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT unit_price, cost_status FROM transactions ORDER BY id"
        ).fetchall() == [(15.0, "CORRECTED"), (30.0, "KNOWN")]


def test_reordered_full_export_does_not_reconcile_to_wrong_known_cost():
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)
    assert AssetService.process_b3_import(pd.DataFrame([movement(value=3000, price=30)])) == (0, 0)

    reordered_full_frame = pd.DataFrame(
        [movement(value=2000, price=20), movement(value=3000, price=30)]
    )
    assert AssetService.process_b3_import(reordered_full_frame) == (1, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT quantity, unit_price, cost_status FROM transactions ORDER BY id"
        ).fetchall() == [(100, 30.0, "KNOWN"), (100, 20.0, "KNOWN")]
        assert conn.execute("SELECT SUM(quantity * unit_price) FROM transactions").fetchone()[
            0
        ] == pytest.approx(5000)


def test_reconciled_trade_does_not_consume_duplicate_known_trade():
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)
    assert AssetService.process_b3_import(
        pd.DataFrame([movement(value=2000, price=20)])
    ) == (0, 0)

    duplicate_export = pd.DataFrame(
        [movement(value=2000, price=20), movement(value=2000, price=20)]
    )
    assert AssetService.process_b3_import(duplicate_export) == (1, 0)

    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 200
    assert position["invested_amount"] == pytest.approx(4000)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_reconciled_corrected_trade_does_not_consume_duplicate_known_trade():
    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)
    pending_id = int(AssetService.get_pending_costs().iloc[0]["id"])
    assert AssetService.regularize_cost(pending_id, 20)

    duplicate_export = pd.DataFrame(
        [movement(value=2000, price=20), movement(value=2000, price=20)]
    )
    assert AssetService.process_b3_import(duplicate_export) == (1, 0)

    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 200
    assert position["invested_amount"] == pytest.approx(4000)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_partial_export_reconciles_corrected_trade_after_occurrence_renumbering():
    assert AssetService.process_b3_import(pd.DataFrame([movement(), movement()])) == (2, 0)
    pending = AssetService.get_pending_costs()
    first_id = int(pending.iloc[0]["id"])
    second_id = int(pending.iloc[1]["id"])
    assert AssetService.regularize_cost(first_id, 30)
    assert AssetService.regularize_cost(second_id, 20)

    partial_export = pd.DataFrame([movement(value=2000, price=20)])
    assert AssetService.process_b3_import(partial_export) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT unit_price, cost_status FROM transactions ORDER BY id"
        ).fetchall() == [(30.0, "CORRECTED"), (20.0, "CORRECTED")]


def test_identical_same_day_b3_trades_remain_separate_and_idempotent():
    frame = pd.DataFrame([movement(value=2000, price=20), movement(value=2000, price=20)])

    assert AssetService.process_b3_import(frame) == (2, 0)
    assert AssetService.process_b3_import(frame) == (0, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


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


def test_reimport_reconciles_legacy_positive_cost_custody_entry():
    AssetService.add_transaction("BBAS3", "2024-01-02", "BUY", 100, 20)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        transaction_id = conn.execute(
            "SELECT id FROM transactions WHERE ticker='BBAS3'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO b3_import_records (source_key, source_record, event_kind, transaction_id, status) "
            "VALUES (?, ?, 'CUSTODY', ?, 'IMPORTED')",
            (
                "legacy-source",
                json.dumps(
                    {
                        "date": "2024-01-02",
                        "ticker": "BBAS3",
                        "movement": "Transferência",
                        "direction": "Crédito",
                        "quantity": 100,
                        "price": 20,
                        "value": 2000,
                        "institution": "",
                    },
                    ensure_ascii=False,
                ),
                transaction_id,
            ),
        )
        conn.commit()

    frame = pd.DataFrame([movement("Transferência", date="02/01/2024", value=2000, price=20)])
    assert AssetService.process_b3_import(frame) == (0, 0)
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 100
    assert position["average_price"] == pytest.approx(20)
    assert not position["cost_pending"]
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 1


def test_reimport_does_not_adopt_unprovenanced_legacy_custody():
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees) "
            "VALUES ('2024-01-02', 'BBAS3', 'BUY', 100, 20, 0)"
        )
        conn.commit()
    frame = pd.DataFrame([movement("Transferência", date="02/01/2024", value=2000, price=20)])

    assert AssetService.process_b3_import(frame) == (1, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 1
        assert conn.execute("SELECT event_kind FROM b3_import_records").fetchone()[0] == "CUSTODY"


def test_reimport_reconciles_trade_previously_corrected_by_legacy_parser():
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(date, ticker, transaction_type, quantity, unit_price, fees) "
            "VALUES ('2021-04-30', 'CXSE3', 'BUY', 340, 9.67, 0)"
        )
        conn.commit()
    legacy_ipo = movement(
        "Transferência - Liquidação",
        date="30/04/2021",
        quantity=340,
    )
    legacy_ipo["Produto"] = "CXSE3"

    assert AssetService.process_b3_import(pd.DataFrame([legacy_ipo])) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        transaction = conn.execute(
            "SELECT unit_price, cost_status, transaction_origin FROM transactions WHERE ticker='CXSE3'"
        ).fetchone()
        assert transaction == (9.67, "PENDING", "B3")
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT event_kind FROM b3_import_records").fetchone()[0] == "TRADE"


def test_pending_import_does_not_adopt_an_unidentified_legacy_trade():
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "INSERT INTO transactions "
            "(date, ticker, transaction_type, quantity, unit_price, fees) "
            "VALUES ('2024-01-02', 'BBAS3', 'BUY', 100, 20, 0)"
        )
        conn.commit()

    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_known_b3_adoption_reconciles_legacy_origin_after_value_change():
    AssetService.add_transaction("BBAS3", "2024-01-02", "BUY", 100, 20)
    first_import = pd.DataFrame([movement(value=2000, price=20)])
    second_import = pd.DataFrame([movement(value=2100, price=20)])

    assert AssetService.process_b3_import(first_import) == (0, 0)
    assert AssetService.process_b3_import(second_import) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute(
            "SELECT transaction_origin, cost_status FROM transactions"
        ).fetchone() == ("B3", "KNOWN")


def test_known_import_reconciles_derived_price_with_official_price():
    derived_price = pd.DataFrame([movement(value=2000, price=0)])
    official_price = pd.DataFrame([movement(value=2000, price=19.99)])

    assert AssetService.process_b3_import(derived_price) == (1, 0)
    assert AssetService.process_b3_import(official_price) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT unit_price FROM transactions").fetchone()[0] == pytest.approx(
            19.99
        )


def test_pending_import_does_not_adopt_manual_zero_cost_entry():
    AssetService.add_transaction("BBAS3", "2024-01-02", "BUY", 100, 0, 0)

    assert AssetService.process_b3_import(pd.DataFrame([movement()])) == (1, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_custody_price_fallback_does_not_adopt_provenanced_trade():
    frame = pd.DataFrame(
        [
            movement("Compra", date="02/01/2024", value=2000, price=20),
            movement("Transferência", date="02/01/2024", value=2000, price=20),
        ]
    )

    assert AssetService.process_b3_import(frame) == (2, 0)
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 200
    assert position["cost_pending"]
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_custody_price_fallback_does_not_adopt_manual_trade():
    AssetService.add_transaction("BBAS3", "2024-01-02", "BUY", 100, 20)
    frame = pd.DataFrame([movement("Transferência", date="02/01/2024", value=2000, price=20)])

    assert AssetService.process_b3_import(frame) == (1, 0)
    position = AssetService.calculate_positions().iloc[0]
    assert position["quantity"] == 200


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


def test_import_does_not_adopt_ambiguous_legacy_transaction():
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees) "
            "VALUES ('2024-01-02', 'BBAS3', 'BUY', 100, 0, 0)"
        )
        conn.commit()
    frame = pd.DataFrame([movement()])
    assert AssetService.process_b3_import(frame) == (1, 0)
    assert AssetService.calculate_positions().iloc[0]["quantity"] == 200
    assert len(AssetService.get_pending_costs()) == 1
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE transaction_origin='B3'"
            ).fetchone()[0]
            == 1
        )


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


def test_retirement_planning_ignores_positions_with_pending_cost():
    AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 100, 20)
    pending = movement(quantity=50)
    pending["Produto"] = "TAEE11"
    AssetService.process_b3_import(pd.DataFrame([pending]))
    SimulationService.save_configuration(
        birth_date="1990-01-01",
        retirement_age=65,
        desired_income_mw=10,
        annual_interest_rate=6,
        mw_value=1518,
        initial_equity_input=0,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=15180,
    )

    simulation = SimulationService.get_current_simulation()

    assert simulation is not None
    assert simulation["total_invested"] == 2000
    assert simulation["updated_monthly_contribution"] > 0

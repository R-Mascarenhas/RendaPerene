import json
import tracemalloc
from contextlib import closing

import pandas as pd
import pytest

from core.daos.portfolio_dao import PortfolioDAO
from core.database import db
from services.assets_service import AssetService


def b3_trade(date, kind="Compra", price=20.0, quantity=100):
    return pd.DataFrame(
        [
            {
                "Movimentação": kind,
                "Data": date,
                "Produto": "BBAS3",
                "Instituição": "Corretora Teste",
                "Quantidade": quantity,
                "Preço unitário": price,
                "Valor da Operação": price * quantity,
                "Entrada/Saída": "Crédito" if kind == "Compra" else "Débito",
            }
        ]
    )


def test_repository_import_accepts_explicit_confirmation_and_batch_context():
    from core.b3_reconciliation import B3ImportContext

    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0, 7.5)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    transactions, _ = AssetService.get_default()._excel_parser.parse_b3_excel(frame)
    records = transactions.to_dict("records")
    context = B3ImportContext.from_records(
        records, {candidate["source_key"]: candidate["manual_groups"][0]["ids"]}
    )
    request = context.request(records[0])

    assert request.occurrence_count == 1
    assert PortfolioDAO().import_b3_transaction(request, context)
    assert not PortfolioDAO().import_b3_transaction(request, context)
    activity = AssetService.get_portfolio_activity(limit=None)
    assert len(activity) == 1
    assert activity.iloc[0]["date"] == "2026-10-02"
    assert activity.iloc[0]["value"] == 2007.5


@pytest.mark.parametrize(
    ("manual_date", "business_date", "price", "reported_value", "compatible"),
    [
        ("2026-10-02", False, 20.0005, 2000.05, True),
        ("2026-10-02", False, 20.000501, 2000.05, False),
        ("2026-10-02", False, 20.0, 2000.059999, True),
        ("2026-10-02", False, 20.0, 2000.060001, False),
        ("2026-09-30", False, 20.0, 2000.0, True),
        ("2026-09-29", False, 20.0, 2000.0, False),
        ("2026-10-04", False, 20.0, 2000.0, True),
        ("2026-10-05", False, 20.0, 2000.0, False),
        ("2026-10-06", True, 20.0, 2000.0, True),
        ("2026-10-05", True, 20.0, 2000.0, False),
    ],
)
def test_suggestion_and_confirmation_agree_at_price_value_and_date_limits(
    manual_date, business_date, price, reported_value, compatible
):
    assert AssetService.add_transaction("BBAS3", manual_date, "BUY", 100, 20.0, 7.5)
    manual_id = int(PortfolioDAO().load_ledger().transactions.iloc[0]["id"])
    frame = b3_trade("2026-10-06", price=price)
    frame.loc[0, "Valor da Operação"] = reported_value
    if business_date:
        frame = frame.rename(columns={"Data": "Data do Negócio"})
    transactions, _ = AssetService.get_default()._excel_parser.parse_b3_excel(frame)
    source_key = transactions.iloc[0]["source_key"]

    assert bool(AssetService.find_b3_manual_trade_candidates(frame)) == compatible
    if compatible:
        assert AssetService.process_b3_import(
            frame, manual_trade_links={source_key: manual_id}
        ) == (1, 0)
        assert AssetService.process_b3_import(frame) == (0, 0)
    else:
        with pytest.raises(ValueError, match="não corresponde mais"):
            AssetService.process_b3_import(frame, manual_trade_links={source_key: manual_id})
    activity = AssetService.get_portfolio_activity(limit=None)
    assert len(activity) == 1
    assert activity.iloc[0]["value"] == 2007.5
    assert activity.iloc[0]["date"] == manual_date


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE transactions SET unit_price=21 WHERE id=?",
        "UPDATE transactions SET date='2026-09-29' WHERE id=?",
        "UPDATE transactions SET transaction_origin='B3' WHERE id=?",
        "DELETE FROM transactions WHERE id=?",
    ],
)
def test_confirmation_rejects_changed_or_removed_manual_candidate(change):
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0, 7.5)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    manual_id = candidate["manual_groups"][0]["ids"][0]
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(change, (manual_id,))
        conn.commit()
    before = PortfolioDAO().load_ledger().transactions

    with pytest.raises(ValueError, match="não corresponde mais"):
        AssetService.process_b3_import(
            frame, manual_trade_links={candidate["source_key"]: manual_id}
        )

    pd.testing.assert_frame_equal(PortfolioDAO().load_ledger().transactions, before)


def test_failed_confirmation_preserves_previously_imported_batch_record():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0, 7.5)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    manual_id = candidate["manual_groups"][0]["ids"][0]
    earlier = b3_trade("2026-09-01", quantity=10)
    batch = pd.concat([earlier, frame], ignore_index=True)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute("UPDATE transactions SET quantity=99 WHERE id=?", (manual_id,))
        conn.commit()

    with pytest.raises(ValueError, match="não corresponde mais"):
        AssetService.process_b3_import(
            batch, manual_trade_links={candidate["source_key"]: manual_id}
        )

    activity = AssetService.get_portfolio_activity(limit=None)
    assert len(activity) == 2
    assert activity.iloc[1]["date"] == "2026-09-01"
    assert activity.iloc[1]["value"] == 200.0
    assert AssetService.process_b3_import(earlier) == (0, 0)


def test_b3_source_identity_remains_compatible_with_existing_date_only_imports():
    transactions, _ = AssetService.get_default()._excel_parser.parse_b3_excel(
        b3_trade("2026-10-06")
    )
    assert transactions.iloc[0]["source_key"] == (
        "a241991e0020cfca67578447c1bf478e199a68c61a7d50851650bb3d7a17b1d3"
    )
    source = json.loads(transactions.iloc[0]["source_record"])
    assert source["date"] == "2026-10-06"
    assert "trade_date" not in source
    assert "settlement_date" not in source


@pytest.mark.parametrize(
    ("trade_date", "settlement_date"),
    [("2026-10-02", "2026-10-06"), ("2026-04-02", "2026-04-07")],
)
@pytest.mark.parametrize(("kind", "tx_type"), [("Compra", "BUY"), ("Venda", "SELL")])
def test_confirmed_manual_trade_is_linked_and_keeps_manual_fees(
    trade_date, settlement_date, kind, tx_type
):
    assert AssetService.add_transaction("BBAS3", trade_date, tx_type, 100, 20.0, 7.5)
    frame = b3_trade(settlement_date, kind)

    candidates = AssetService.find_b3_manual_trade_candidates(frame)
    assert len(candidates) == 1
    assert candidates[0]["manual_candidates"][0]["date"] == trade_date

    assert AssetService.process_b3_import(
        frame,
        manual_trade_links={
            candidates[0]["source_key"]: candidates[0]["manual_candidates"][0]["id"]
        },
    ) == (1, 0)
    assert AssetService.process_b3_import(
        frame,
        manual_trade_links={
            candidates[0]["source_key"]: candidates[0]["manual_candidates"][0]["id"]
        },
    ) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        rows = conn.execute(
            """SELECT date, fees, transaction_origin
               FROM transactions"""
        ).fetchall()
        assert rows == [(trade_date, 7.5, "MANUAL")]
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 1
        source = json.loads(conn.execute("SELECT source_record FROM b3_import_records").fetchone()[0])
        assert source["date"] == settlement_date
    activity = AssetService.get_portfolio_activity(limit=None)
    assert activity.iloc[0]["date"] == trade_date


def test_manual_and_b3_trades_remain_separate_when_user_does_not_confirm():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0, 7.5)

    assert AssetService.process_b3_import(b3_trade("2026-10-06")) == (1, 0)
    assert AssetService.find_b3_manual_trade_candidates(b3_trade("2026-10-06")) == []

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT date, fees FROM transactions ORDER BY id"
        ).fetchall() == [
            ("2026-10-02", 7.5),
            ("2026-10-06", 0.0),
        ]


def test_reconciled_trade_is_not_reused_for_a_different_b3_institution():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)
    frame = b3_trade("2026-10-02").rename(columns={"Data": "Data do Negócio"})
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    assert AssetService.process_b3_import(
        frame, manual_trade_links={candidate["source_key"]: candidate["manual_groups"][0]["ids"]}
    ) == (1, 0)
    other_institution = frame.copy()
    other_institution.loc[0, "Instituição"] = "Outra Corretora"

    assert AssetService.process_b3_import(other_institution) == (1, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_reimport_preserves_reconciliation_created_with_previous_date_metadata():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    assert AssetService.process_b3_import(
        frame, manual_trade_links={candidate["source_key"]: candidate["manual_groups"][0]["ids"]}
    ) == (1, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        source = json.loads(conn.execute("SELECT source_record FROM b3_import_records").fetchone()[0])
        source.update(trade_date=None, settlement_date="2026-10-06")
        conn.execute(
            "UPDATE b3_import_records SET source_key=?, source_record=?",
            ("previous-date-metadata-source", json.dumps(source)),
        )
        conn.execute(
            "UPDATE b3_manual_reconciliations SET source_key=?",
            ("previous-date-metadata-source",),
        )
        conn.commit()
    assert AssetService.add_transaction("BBAS3", "2026-10-01", "BUY", 100, 20.0)

    assert AssetService.find_b3_manual_trade_candidates(frame) == []
    assert AssetService.process_b3_import(frame) == (0, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 1


def test_known_manual_trade_with_different_price_is_not_suggested():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)

    assert AssetService.find_b3_manual_trade_candidates(b3_trade("2026-10-06", price=21.0)) == []


def test_b3_aggregate_can_be_reconciled_to_multiple_manual_trades():
    assert AssetService.add_transaction("CMIG4", "2026-10-02", "BUY", 200, 10.86, 0.75)
    assert AssetService.add_transaction("CMIG4", "2026-10-02", "BUY", 5, 10.93, 0.25)
    frame = pd.DataFrame(
        [
            {
                "Movimentação": "Compra",
                "Data": "2026-10-06",
                "Produto": "CMIG4",
                "Instituição": "Corretora Teste",
                "Quantidade": 205,
                "Preço unitário": 10.862,
                "Valor da Operação": 2226.71,
                "Entrada/Saída": "Crédito",
            }
        ]
    )

    candidates = AssetService.find_b3_manual_trade_candidates(frame)

    assert len(candidates) == 1
    group = next(
        group
        for group in candidates[0]["manual_groups"]
        if len(group["transactions"]) == 2
    )
    assert group["quantity"] == 205
    assert group["weighted_unit_price"] == pytest.approx(10.861707317, abs=1e-8)

    assert AssetService.process_b3_import(
        frame,
        manual_trade_links={candidates[0]["source_key"]: group["ids"]},
    ) == (1, 0)
    assert AssetService.process_b3_import(
        frame,
        manual_trade_links={candidates[0]["source_key"]: group["ids"]},
    ) == (0, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        trades = conn.execute(
            "SELECT date, quantity, unit_price, fees, transaction_origin "
            "FROM transactions ORDER BY id"
        ).fetchall()
        assert trades == [
            ("2026-10-02", 200, 10.86, 0.75, "MANUAL"),
            ("2026-10-02", 5, 10.93, 0.25, "MANUAL"),
        ]
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM b3_manual_reconciliations"
        ).fetchone()[0] == 2


def test_late_matching_group_is_found_without_duplicate_financial_effect():
    for index, price in enumerate([21.0] * 10 + [20.0] * 10):
        assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 1, price, index / 100)
    frame = b3_trade("2026-10-06", quantity=10)

    candidates = AssetService.find_b3_manual_trade_candidates(frame)

    assert len(candidates) == 1
    group = candidates[0]["manual_groups"][0]
    assert len(group["ids"]) == 10
    assert all(row["unit_price"] == 20.0 for row in group["transactions"])
    assert AssetService.process_b3_import(
        frame, manual_trade_links={candidates[0]["source_key"]: group["ids"]}
    ) == (1, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT SUM(quantity), COUNT(*) FROM transactions").fetchone() == (20, 20)


def test_equivalent_subset_states_keep_distinct_valid_suggestions():
    for index in range(20):
        assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 1, 20, index / 100)

    candidate = AssetService.find_b3_manual_trade_candidates(
        b3_trade("2026-10-06", quantity=10)
    )[0]

    groups = candidate["manual_groups"]
    assert len(groups) == 25
    assert len({tuple(group["ids"]) for group in groups}) == 25
    assert all(len(group["ids"]) == 10 for group in groups)


@pytest.mark.parametrize(
    ("prices", "first_quantity", "second_quantity", "second_price"),
    [([20.0] * 20, 10, 10, 20.0), ([20.0] * 8 + [19.0] * 2 + [21.0] * 2, 6, 2, 21.0)],
)
def test_multiple_b3_rows_offer_a_disjoint_manual_assignment(
    prices, first_quantity, second_quantity, second_price
):
    for index, price in enumerate(prices):
        assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 1, price, index / 100)
    first = b3_trade("2026-10-06", quantity=first_quantity)
    second = b3_trade("2026-10-06", price=second_price, quantity=second_quantity)
    second.loc[0, "Instituição"] = "Outra Corretora"
    frame = pd.concat([first, second], ignore_index=True)

    candidates = AssetService.find_b3_manual_trade_candidates(frame)

    assert len(candidates) == 2
    assert set(candidates[0]["manual_groups"][0]["ids"]).isdisjoint(
        candidates[1]["manual_groups"][0]["ids"]
    )
    assert all(len(candidate["manual_groups"]) <= 25 for candidate in candidates)
    assignment = next(
        (
            (first_group, second_group)
            for first_group in candidates[0]["manual_groups"]
            for second_group in candidates[1]["manual_groups"]
            if set(first_group["ids"]).isdisjoint(second_group["ids"])
        ),
        None,
    )
    assert assignment is not None
    assert AssetService.process_b3_import(
        frame,
        manual_trade_links={
            candidate["source_key"]: group["ids"]
            for candidate, group in zip(candidates, assignment, strict=True)
        },
    ) == (2, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == len(prices)
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 2


def test_distinct_price_search_does_not_store_every_full_subset():
    rows = [
        {"id": index, "date": "2026-10-02", "quantity": 1, "unit_price": 20 + 2**index / 10**7}
        for index in range(20)
    ]
    tracemalloc.start()
    try:
        groups = AssetService._find_matching_manual_groups(
            rows, {"quantity": 10, "unit_price": 100}, {"value": 1000}
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert groups == []
    assert peak_bytes < 10 * 1024 * 1024


def test_manual_group_is_revalidated_on_import():
    assert AssetService.add_transaction("CMIG4", "2026-10-02", "BUY", 200, 10.86)
    assert AssetService.add_transaction("CMIG4", "2026-10-02", "BUY", 5, 10.93)
    frame = pd.DataFrame(
        [
            {
                "Movimentação": "Compra",
                "Data": "2026-10-06",
                "Produto": "CMIG4",
                "Instituição": "Corretora Teste",
                "Quantidade": 205,
                "Preço unitário": 10.862,
                "Valor da Operação": 2226.71,
                "Entrada/Saída": "Crédito",
            }
        ]
    )
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    group = next(group for group in candidate["manual_groups"] if len(group["ids"]) == 2)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "UPDATE transactions SET quantity=4 WHERE id=?", (group["ids"][1],)
        )
        conn.commit()

    with pytest.raises(ValueError, match="não corresponde mais"):
        AssetService.process_b3_import(
            frame, manual_trade_links={candidate["source_key"]: group["ids"]}
        )
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM b3_manual_reconciliations").fetchone()[0] == 0


def test_aggregate_does_not_combine_manual_trades_from_different_dates():
    assert AssetService.add_transaction("CMIG4", "2026-10-02", "BUY", 200, 10.86)
    assert AssetService.add_transaction("CMIG4", "2026-10-03", "BUY", 5, 10.93)
    frame = pd.DataFrame(
        [
            {
                "Movimentação": "Compra",
                "Data": "2026-10-07",
                "Produto": "CMIG4",
                "Instituição": "Corretora Teste",
                "Quantidade": 205,
                "Preço unitário": 10.862,
                "Valor da Operação": 2226.71,
                "Entrada/Saída": "Crédito",
            }
        ]
    )

    assert AssetService.find_b3_manual_trade_candidates(frame) == []


def test_manual_trade_with_different_reported_total_is_not_suggested():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)
    frame = b3_trade("2026-10-06")
    frame.loc[0, "Valor da Operação"] = 2001.0

    assert AssetService.find_b3_manual_trade_candidates(frame) == []


def test_explicit_b3_business_date_matches_same_day_manual_trade():
    frame = b3_trade("2026-10-02").rename(columns={"Data": "Data do Negócio"})
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)

    candidates = AssetService.find_b3_manual_trade_candidates(frame)

    assert len(candidates) == 1
    assert candidates[0]["manual_candidates"][0]["date"] == "2026-10-02"
    transactions, _ = AssetService.get_default()._excel_parser.parse_b3_excel(frame)
    assert transactions.loc[0, "date"] == "2026-10-02"
    assert transactions.loc[0, "date_is_business"]


def test_selected_candidate_is_revalidated_before_linking():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    manual_id = candidate["manual_candidates"][0]["id"]
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute("UPDATE transactions SET quantity=99 WHERE id=?", (manual_id,))
        conn.commit()

    with pytest.raises(ValueError, match="não corresponde mais"):
        AssetService.process_b3_import(
            frame, manual_trade_links={candidate["source_key"]: manual_id}
        )

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 0


def test_manual_candidate_linked_by_another_import_cannot_be_reused():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    manual_id = candidate["manual_candidates"][0]["id"]
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "INSERT INTO b3_import_records "
            "(source_key, source_record, event_kind, transaction_id, status) "
            "VALUES (?, ?, 'TRADE', ?, 'IMPORTED')",
            ("another-import", json.dumps({"date": "2026-10-05"}), manual_id),
        )
        conn.commit()

    with pytest.raises(ValueError, match="não corresponde mais"):
        AssetService.process_b3_import(
            frame, manual_trade_links={candidate["source_key"]: manual_id}
        )
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM b3_import_records").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM b3_manual_reconciliations").fetchone()[0] == 0


def test_schema_migration_preserves_dates_without_adding_date_columns():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0)
    assert AssetService.process_b3_import(b3_trade("2026-11-02")) == (1, 0)

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute("DROP TABLE b3_manual_reconciliations")
        conn.execute("PRAGMA user_version=4")
        conn.commit()

    db.init_personal_db()

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        dates = conn.execute(
            "SELECT transaction_origin, date "
            "FROM transactions ORDER BY id"
        ).fetchall()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
        assert "trade_date" not in columns
        assert "settlement_date" not in columns
        assert conn.execute("SELECT COUNT(*) FROM b3_manual_reconciliations").fetchone()[0] == 0
    assert dates == [("MANUAL", "2026-10-02"), ("B3", "2026-11-02")]


def test_initialization_restores_only_provenanced_manual_reconciliations():
    assert AssetService.add_transaction("BBAS3", "2026-10-02", "BUY", 100, 20.0, 7.5)
    frame = b3_trade("2026-10-06")
    candidate = AssetService.find_b3_manual_trade_candidates(frame)[0]
    manual_ids = candidate["manual_groups"][0]["ids"]
    assert AssetService.process_b3_import(
        frame, manual_trade_links={candidate["source_key"]: manual_ids}
    ) == (1, 0)
    assert AssetService.process_b3_import(b3_trade("2026-11-02")) == (1, 0)
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.execute(
            "UPDATE transactions SET transaction_origin='B3' WHERE id=?", (manual_ids[0],)
        )
        conn.commit()
        financial_rows = conn.execute(
            "SELECT id, date, ticker, transaction_type, quantity, unit_price, fees "
            "FROM transactions ORDER BY id"
        ).fetchall()
        source_rows = conn.execute("SELECT * FROM b3_import_records ORDER BY source_key").fetchall()
        links = conn.execute("SELECT * FROM b3_manual_reconciliations").fetchall()

    db.init_personal_db()
    db.init_personal_db()

    with closing(PortfolioDAO().get_personal_connection()) as conn:
        assert conn.execute(
            "SELECT transaction_origin FROM transactions ORDER BY id"
        ).fetchall() == [("MANUAL",), ("B3",)]
        assert conn.execute(
            "SELECT id, date, ticker, transaction_type, quantity, unit_price, fees "
            "FROM transactions ORDER BY id"
        ).fetchall() == financial_rows
        assert conn.execute(
            "SELECT * FROM b3_import_records ORDER BY source_key"
        ).fetchall() == source_rows
        assert conn.execute("SELECT * FROM b3_manual_reconciliations").fetchall() == links
    assert AssetService.find_b3_manual_trade_candidates(frame) == []
    assert AssetService.process_b3_import(frame) == (0, 0)

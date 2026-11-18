"""B3 receipt matching through the public import and review workflow."""

from contextlib import closing

import pandas as pd
import pytest

from core.daos.portfolio_dao import PortfolioDAO
from services.assets_service import AssetService


def b3_receipt(date="10/11/2026", total=100, quantity=100, price=1):
    return pd.DataFrame([{
        "Movimentação": "Dividendo", "Data": date, "Produto": "BBAS3",
        "Quantidade": quantity, "Preço unitário": price,
        "Valor da Operação": total, "Entrada/Saída": "Crédito",
        "Instituição": "Corretora Teste",
    }])


def test_old_unrelated_receipt_does_not_require_confirmation():
    AssetService.add_dividend("BBAS3", "2021-01-04", "DIVIDEND", 100)
    statement = b3_receipt()

    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 1)
    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 0)
    payments = AssetService.get_dividend_payments("BBAS3")
    assert len(payments) == 2
    assert {row["date"] for row in payments} == {"2021-01-04", "2026-11-10"}


@pytest.mark.parametrize("date", ["2026-11-02", "2026-11-18"])
def test_receipt_more_than_seven_days_away_is_not_suggested(date):
    AssetService.add_dividend("BBAS3", date, "DIVIDEND", 100)
    assert AssetService.find_b3_dividend_candidates(b3_receipt()) == []


@pytest.mark.parametrize("stored_total", [94.99, 105.01])
def test_receipt_outside_five_percent_is_not_suggested(stored_total):
    AssetService.add_dividend("BBAS3", "2026-11-09", "DIVIDEND", stored_total)
    statement = b3_receipt()
    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 1)
    assert len(AssetService.get_dividend_payments("BBAS3")) == 2


@pytest.mark.parametrize("stored_date", ["2026-11-03", "2026-11-17"])
@pytest.mark.parametrize("stored_total", [95, 105])
def test_nearby_receipt_at_both_limits_requires_confirmation(stored_date, stored_total):
    AssetService.add_dividend("BBAS3", stored_date, "DIVIDEND", stored_total)
    statement = b3_receipt()
    revision = AssetService.get_local_projection_revision()
    candidates = AssetService.find_b3_dividend_candidates(statement)
    assert AssetService.get_local_projection_revision() == revision
    assert len(candidates) == 1
    assert len(candidates[0]["payments"]) == 1
    candidate = candidates[0]
    payment_id = candidate["payments"][0]["id"]

    with pytest.raises(ValueError, match="Confirme"):
        AssetService.process_b3_import(statement)
    assert AssetService.get_local_projection_revision() == revision
    assert AssetService.process_b3_import(statement, dividend_links={
        candidate["source_key"]: payment_id,
    }) == (0, 1)
    payments = AssetService.get_dividend_payments("BBAS3")
    assert len(payments) == 1
    assert payments[0]["id"] == payment_id
    assert payments[0]["date"] == "2026-11-10"
    assert payments[0]["total_value"] == 100
    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 0)


@pytest.mark.parametrize("stored_total,review", [(0.08, True), (0.12, True), (0.07, False), (0.13, False)])
def test_small_receipts_use_a_two_cent_minimum_tolerance(stored_total, review):
    AssetService.add_dividend("BBAS3", "2026-11-09", "DIVIDEND", stored_total)
    assert bool(AssetService.find_b3_dividend_candidates(b3_receipt(total=0.1))) == review


def test_exact_legacy_receipt_takes_priority_over_nearby_payments():
    AssetService.add_dividend("BBAS3", "2026-11-10", "DIVIDEND", 100)
    exact = AssetService.get_dividend_payments("BBAS3")[0]
    AssetService.add_dividend("BBAS3", "2026-11-09", "DIVIDEND", 99)
    AssetService.add_dividend("BBAS3", "2021-01-04", "DIVIDEND", 100)
    statement = b3_receipt()

    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 1)
    payments = AssetService.get_dividend_payments("BBAS3")
    assert len(payments) == 3
    matched = next(row for row in payments if row["id"] == exact["id"])
    assert matched["date"] == "2026-11-10"
    assert matched["total_value"] == 100
    assert matched["quantity"] == 100
    assert matched["unit_price"] == 1
    assert AssetService.process_b3_import(statement) == (0, 0)


def test_ambiguous_exact_legacy_receipts_require_explicit_choice():
    # Reproduce duplicate receipts already present in an older portfolio database.
    with closing(PortfolioDAO().get_personal_connection()) as conn:
        conn.executemany(
            "INSERT INTO dividends (date,ticker,dividend_type,total_value) VALUES (?,?,?,?)",
            [("2026-11-10", "BBAS3", "DIVIDEND", 100)] * 2,
        )
        conn.commit()
    statement = b3_receipt()
    candidates = AssetService.find_b3_dividend_candidates(statement)
    assert len(candidates) == 1
    assert len(candidates[0]["payments"]) == 2
    with pytest.raises(ValueError, match="Confirme"):
        AssetService.process_b3_import(statement)
    selected_id = candidates[0]["payments"][0]["id"]
    assert AssetService.process_b3_import(statement, dividend_links={
        candidates[0]["source_key"]: selected_id,
    }) == (0, 1)
    payments = AssetService.get_dividend_payments("BBAS3")
    assert len(payments) == 2
    assert next(row for row in payments if row["id"] == selected_id)["quantity"] == 100
    assert AssetService.process_b3_import(statement) == (0, 0)


@pytest.mark.parametrize("changed_date", ["2026-11-02", "2026-11-08"])
def test_changed_payment_is_revalidated_before_the_confirmed_link_is_saved(changed_date):
    AssetService.add_dividend("BBAS3", "2026-11-09", "DIVIDEND", 99)
    candidate = AssetService.find_b3_dividend_candidates(b3_receipt())[0]
    expected = candidate["payments"][0]
    choices = {candidate["source_key"]: {"id": expected["id"], "expected": expected}}
    AssetService.reschedule_dividend(
        expected["id"], changed_date, AssetService.get_local_projection_revision(),
    )
    before = AssetService.get_dividend_payments("BBAS3")
    revision = AssetService.get_local_projection_revision()

    with pytest.raises(ValueError, match="mudou"):
        PortfolioDAO().import_b3_dividend(candidate["b3"], choices)

    assert AssetService.get_dividend_payments("BBAS3") == before
    assert AssetService.get_local_projection_revision() == revision

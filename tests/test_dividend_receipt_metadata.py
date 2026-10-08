from services.portfolio_read_service import PortfolioReadService
import pandas as pd
import pytest

from services.assets_service import AssetService


def receipt(kind="Dividendo", quantity=80, unit_price=0.125, total=10):
    return pd.DataFrame([{
        "Movimentação": kind, "Data": "02/01/2026", "Produto": "BBAS3",
        "Quantidade": quantity, "Preço unitário": unit_price,
        "Valor da Operação": total, "Entrada/Saída": "Crédito",
    }])


@pytest.mark.parametrize("kind,event", [
    ("Dividendo", "Dividendo"), ("Juros Sobre Capital Próprio", "JCP"),
    ("Rendimento", "Rendimento"),
])
def test_imported_receipt_preserves_quantity_price_and_authoritative_total(kind, event):
    # The reported receipt need not match the holding on its payment date.
    AssetService.add_transaction("BBAS3", "2026-01-01", "BUY", 100, 20)
    assert AssetService.process_b3_import(receipt(kind, total=9.25)) == (0, 1)
    activity = AssetService.get_portfolio_activity().iloc[0]
    assert activity["event"] == event
    assert activity["quantity"] == 80
    assert activity["quantity_status"] == "reported"
    assert activity["value"] == 9.25
    detailed = PortfolioReadService.read_asset("BBAS3").dividend_details.iloc[0]
    assert detailed["Unitário"] == 0.125
    assert detailed["Total"] == 9.25


@pytest.mark.parametrize("kind", [
    "Juros Sobre Capital Próprio", "Dividendo", "Rendimento",
])
@pytest.mark.parametrize("direction", ["Crédito", "Débito"])
@pytest.mark.parametrize("movement_column", ["Movimentação", "Tipo de Movimentação"])
def test_transferred_dividend_right_does_not_create_receipt_or_position(
    kind, direction, movement_column,
):
    statement = receipt(f"{kind} - Transferido").rename(
        columns={"Movimentação": movement_column},
    )
    statement["Entrada/Saída"] = direction

    assert AssetService.process_b3_import(statement) == (0, 0)
    assert AssetService.get_portfolio_activity(limit=None).empty
    assert PortfolioReadService.read_planning().positions.empty


def test_transferred_right_does_not_duplicate_or_enrich_actual_payment():
    payment = receipt("Juros Sobre Capital Próprio", quantity=None, unit_price=None)
    transfer = receipt("Juros Sobre Capital Próprio - Transferido")

    assert AssetService.process_b3_import(payment) == (0, 1)
    revision = AssetService.get_local_projection_revision()
    assert AssetService.process_b3_import(transfer) == (0, 0)
    assert AssetService.get_local_projection_revision() == revision
    assert AssetService.process_b3_import(payment) == (0, 0)
    activity = AssetService.get_portfolio_activity(limit=None)
    assert len(activity) == 1
    assert activity.iloc[0]["event"] == "JCP"
    assert activity.iloc[0]["value"] == 10
    assert pd.isna(activity.iloc[0]["quantity"])


def test_reimport_completes_legacy_receipt_once_without_changing_total():
    AssetService.add_dividend("BBAS3", "2026-01-02", "DIVIDEND", 10)
    before_revision = AssetService.get_local_projection_revision()
    assert AssetService.process_b3_import(receipt()) == (0, 1)
    assert AssetService.get_local_projection_revision() > before_revision
    assert AssetService.process_b3_import(receipt()) == (0, 0)
    history = AssetService.get_portfolio_activity(limit=None)
    assert len(history) == 1
    assert history.iloc[0]["quantity"] == 80
    assert history["value"].sum() == 10
    assert AssetService.process_b3_import(receipt(quantity=90)) == (0, 0)
    assert AssetService.get_portfolio_activity().iloc[0]["quantity"] == 80


@pytest.mark.parametrize("missing", [None, float("nan"), "-", "", 0, -5, float("inf")])
def test_missing_receipt_quantity_uses_unrounded_reported_unit_price(missing):
    assert AssetService.process_b3_import(receipt(quantity=missing)) == (0, 1)
    activity = AssetService.get_portfolio_activity().iloc[0]
    assert activity["quantity"] == 80
    assert activity["quantity_status"] == "estimated"
    assert activity["value"] == 10


def test_legacy_fallback_uses_historical_payment_position_and_retains_unknown_quantity():
    AssetService.add_transaction("BBAS3", "2026-01-01", "BUY", 30, 20)
    AssetService.add_dividend("BBAS3", "2026-01-02", "DIVIDEND", 1)
    AssetService.add_transaction("BBAS3", "2026-01-03", "BUY", 70, 20)
    AssetService.add_dividend("CXSE3", "2026-01-04", "JCP", 10)
    activity = AssetService.get_portfolio_activity(limit=None)
    known = activity.loc[activity["event"] == "Dividendo"].iloc[0]
    unknown = activity.loc[activity["event"] == "JCP"].iloc[0]
    assert known["quantity"] == pytest.approx(30)
    assert known["quantity_status"] == "estimated"
    assert pd.isna(unknown["quantity"])
    assert unknown["quantity_status"] == "unavailable"


def test_invalid_metadata_does_not_drop_receipt_or_fabricate_quantity():
    assert AssetService.process_b3_import(receipt(quantity="invalid", unit_price="invalid")) == (0, 1)
    activity = AssetService.get_portfolio_activity().iloc[0]
    assert pd.isna(activity["quantity"])
    assert activity["quantity_status"] == "unavailable"
    assert activity["value"] == 10


def test_reported_fractional_quantity_is_preserved_and_supplies_missing_unit_value():
    AssetService.process_b3_import(receipt(quantity=0.5, unit_price="-"))
    assert AssetService.get_portfolio_activity().iloc[0]["quantity"] == 0.5
    assert PortfolioReadService.read_asset("BBAS3").dividend_details.iloc[0]["Unitário"] == 20


def test_receipt_schema_migration_preserves_old_rows_and_is_repeatable(tmp_path):
    import sqlite3
    from core.database import CURRENT_SCHEMA_VERSION, DatabaseManager
    from core.daos.portfolio_dao import PortfolioDAO

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE dividends (id INTEGER PRIMARY KEY, date TEXT NOT NULL, "
                     "ticker TEXT NOT NULL, dividend_type TEXT NOT NULL, total_value REAL NOT NULL)")
        conn.execute("INSERT INTO dividends VALUES (1, '2026-01-02', 'BBAS3', 'DIVIDEND', 10)")
        conn.execute("PRAGMA user_version = 3")
    manager = DatabaseManager(path)
    manager.init_personal_db()
    manager.init_personal_db()
    service = AssetService(portfolio_repo=PortfolioDAO(manager))
    assert service.get_portfolio_activity().iloc[0]["value"] == 10
    assert service.add_dividend("BBAS3", "2026-01-02", "DIVIDEND", 10, 80, 0.125)
    assert len(service.get_portfolio_activity(limit=None)) == 1
    class NoQuotes:
        def get_batch_quotes(self, tickers):
            return {}

    reads = PortfolioReadService(repository=PortfolioDAO(manager), quotes=NoQuotes())
    assert reads.read_asset("BBAS3").dividend_details.iloc[0]["Unitário"] == 0.125
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_concurrent_receipts_are_saved_only_once():
    from concurrent.futures import ThreadPoolExecutor

    def save():
        return AssetService.add_dividend("BBAS3", "2026-01-02", "DIVIDEND", 10, 80, 0.125)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: save(), range(2)))
    assert sorted(results) == [False, True]
    history = AssetService.get_portfolio_activity(limit=None)
    assert len(history) == 1
    assert history["value"].sum() == 10


@pytest.mark.parametrize("kind,quantity,unit_price,total", [
    ("Dividendo", 80, 0.125, 10),
    ("Juros Sobre Capital Próprio", 80, 0.125, 9.25),
    ("Rendimento", 80, None, 10),
    ("Dividendo", None, 0.125, 10),
])
def test_annual_per_share_metric_honors_receipt_metadata(kind, quantity, unit_price, total):
    AssetService.add_transaction("BBAS3", "2025-01-01", "BUY", 40, 20)
    AssetService.add_transaction("BBAS3", "2026-01-01", "BUY", 60, 20)
    assert AssetService.process_b3_import(receipt(kind, quantity, unit_price, total)) == (0, 1)
    metrics = PortfolioReadService.read_asset("BBAS3").annual_dividends["2026"]
    assert metrics["total_paid_per_share"] == 0.125
    assert PortfolioReadService.read_asset("BBAS3").dividend_details.iloc[0]["Unitário"] == 0.125
    assert metrics["qty_end_of_year"] == 100
    assert metrics["qty_prev_year"] == 40


def test_annual_per_share_metric_sums_selected_year_with_legacy_fallback():
    AssetService.add_transaction("BBAS3", "2025-01-01", "BUY", 40, 20)
    AssetService.add_transaction("BBAS3", "2026-01-01", "BUY", 60, 20)
    AssetService.add_dividend("BBAS3", "2025-02-01", "DIVIDEND", 40, unit_price=1)
    AssetService.add_dividend("BBAS3", "2026-01-02", "JCP", 9.25, quantity=80, unit_price=0.125)
    AssetService.add_dividend("BBAS3", "2026-02-01", "YIELD", 10, quantity=50)
    AssetService.add_dividend("BBAS3", "2026-03-01", "DIVIDEND", 10)
    metrics = PortfolioReadService.read_asset("BBAS3").annual_dividends["2026"]
    assert metrics["total_paid_per_share"] == pytest.approx(0.425)
    assert metrics["qty_end_of_year"] == 100
    assert metrics["qty_prev_year"] == 40


def test_annual_per_share_metric_uses_reported_price_without_historical_position():
    AssetService.add_dividend("BBAS3", "2026-01-02", "JCP", 10, unit_price=0.125)
    AssetService.add_dividend("BBAS3", "2026-02-01", "DIVIDEND", 10)
    metrics = PortfolioReadService.read_asset("BBAS3").annual_dividends["2026"]
    assert metrics["total_paid_per_share"] == 0.125
    assert metrics["qty_end_of_year"] == 0
    assert metrics["qty_prev_year"] == 0

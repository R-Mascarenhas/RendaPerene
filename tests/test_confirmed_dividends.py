import datetime

import pytest
import pandas as pd

from core.dividends import DividendEvent, DividendPayment
from services.assets_service import AssetService
from services.portfolio_read_service import PortfolioReadService


def test_future_payment_only_counts_from_its_payment_date():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2027-06-30", "JCP", 3.5, 100, 0.035)

    before = PortfolioReadService.read_asset(
        "CMIG4", today_date=datetime.date(2027, 6, 29),
    )
    assert before.position["total_dividends"] == 0
    assert before.position["ytd_dividends"] == 0
    assert before.position["l12m_dividends"] == 0
    assert before.annual_dividends == {}
    assert before.dividend_details.iloc[0]["Tipo"] == "JCP - a receber"

    paid = PortfolioReadService.read_asset(
        "CMIG4", today_date=datetime.date(2027, 6, 30),
    )
    assert paid.position["total_dividends"] == 3.5
    assert paid.position["ytd_dividends"] == 3.5
    assert paid.position["l12m_dividends"] == 3.5
    assert paid.annual_dividends["2027"]["total"] == 3.5
    assert paid.dividend_details.iloc[0]["Tipo"] == "JCP"


class FakeDividends:
    def __init__(self, events):
        self.events = events

    def get_events(self, ticker, start_date):
        return self.events


def test_detection_is_read_only_and_confirmed_installments_survive_new_service():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    provider = FakeDividends([event])
    service = AssetService(dividend_provider=provider)
    revision = service.get_local_projection_revision()
    suggestions = service.get_dividend_suggestions()
    assert len(suggestions["suggestions"]) == 1
    assert service.get_local_projection_revision() == revision
    assert PortfolioReadService.read_asset("CMIG4").dividends.empty

    payments = [
        DividendPayment("2027-06-30", 100, 0.035),
        DividendPayment("2027-12-30", 100, 0.035),
    ]
    assert service.confirm_dividend(event, "JCP", payments, revision)
    assert len(PortfolioReadService.read_asset("CMIG4").dividends) == 2
    restarted = AssetService(dividend_provider=provider)
    assert restarted.get_dividend_suggestions()["suggestions"] == []
    assert not restarted.confirm_dividend(event, "JCP", payments, revision)


@pytest.mark.parametrize("payment", [
    DividendPayment("", 100, 0.035),
    DividendPayment("2027-02-30", 100, 0.035),
    DividendPayment("2027-06-30", 0, 0.035),
    DividendPayment("2027-06-30", 100, float("nan")),
])
def test_invalid_payment_never_saves_partial_installments(payment):
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    service = AssetService(dividend_provider=FakeDividends([event]))
    revision = service.get_local_projection_revision()
    with pytest.raises(ValueError):
        service.confirm_dividend(
            event, "JCP", [DividendPayment("2027-06-30", 100, 0.035), payment], revision,
        )
    assert service.get_portfolio_activity(limit=None).empty


def test_b3_requires_review_then_replaces_only_the_chosen_installment():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.035),
        DividendPayment("2027-12-30", 100, 0.035),
    ], AssetService.get_local_projection_revision())
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "28/06/2027",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": 0.03,
        "Valor da Operação": 3.0, "Entrada/Saída": "Crédito",
    }])
    candidates = AssetService.find_b3_dividend_candidates(statement)
    assert len(candidates) == 1
    first_id = candidates[0]["payments"][0]["id"]
    with pytest.raises(ValueError, match="Confirme"):
        AssetService.process_b3_import(statement)
    assert AssetService.process_b3_import(
        statement, dividend_links={candidates[0]["source_key"]: first_id},
    ) == (0, 1)
    details = PortfolioReadService.read_asset("CMIG4").dividends
    assert len(details) == 2
    assert sorted(details["Data"]) == ["2027-06-28", "2027-12-30"]
    assert sorted(details["Total"]) == [3.0, 3.5]
    assert AssetService.process_b3_import(statement) == (0, 0)


def test_existing_payment_link_preserves_manual_correction_and_dismissal_is_durable():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2027-06-30", "JCP", 2.75, 100, 0.0275)
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    second = DividendEvent("CMIG4", "2026-09-24", 0.02)
    service = AssetService(dividend_provider=FakeDividends([event, second]))
    result = service.get_dividend_suggestions()
    assert [item["event"] for item in result["suggestions"]] == [second]
    receipt_id = service.get_dividend_payments("CMIG4")[0]["id"]
    service.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.07, receipt_id),
    ], result["revision"])
    service.ignore_dividend(second, service.get_local_projection_revision())
    restarted = AssetService(dividend_provider=FakeDividends([event, second]))
    assert restarted.get_dividend_suggestions()["suggestions"] == []
    details = PortfolioReadService.read_asset("CMIG4").dividends
    assert len(details) == 1
    assert details.iloc[0]["Total"] == 2.75


def test_stale_confirmation_does_not_change_existing_data():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    revision = AssetService.get_local_projection_revision()
    AssetService.add_dividend("CMIG4", "2027-06-30", "JCP", 2.75)
    with pytest.raises(ValueError, match="carteira mudou"):
        AssetService.confirm_dividend(
            event, "JCP", [DividendPayment("2027-12-30", 100, 0.035)], revision,
        )
    assert len(PortfolioReadService.read_asset("CMIG4").dividends) == 1


def test_payment_date_can_be_corrected_without_changing_confirmed_amount():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.035),
    ], AssetService.get_local_projection_revision())
    payment = AssetService.get_dividend_payments("CMIG4")[0]
    AssetService.reschedule_dividend(
        payment["id"], "2027-07-15", AssetService.get_local_projection_revision(),
    )
    updated = AssetService.get_dividend_payments("CMIG4")[0]
    assert updated["date"] == "2027-07-15"
    assert updated["total_value"] == 3.5
    assert updated["quantity"] == 100
    assert updated["unit_price"] == 0.035


def test_source_failure_is_explicit_and_does_not_prevent_manual_entries():
    class Unavailable:
        def get_events(self, ticker, start_date):
            raise TimeoutError("unavailable")

    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    service = AssetService(dividend_provider=Unavailable())
    result = service.get_dividend_suggestions()
    assert result["suggestions"] == []
    assert result["unavailable"] == ["CMIG4"]
    assert service.add_dividend("CMIG4", "2026-09-30", "JCP", 3.5)


def test_source_change_does_not_overwrite_confirmed_payment():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.025),
    ], AssetService.get_local_projection_revision())
    service = AssetService(dividend_provider=FakeDividends([
        DividendEvent("CMIG4", "2026-09-23", 0.08),
    ]))
    result = service.get_dividend_suggestions()
    assert result["suggestions"] == []
    assert result["changed"] == ["CMIG4"]
    assert service.get_dividend_payments("CMIG4")[0]["total_value"] == 2.5


def test_failed_existing_association_rolls_back_new_installments():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    revision = AssetService.get_local_projection_revision()
    with pytest.raises(ValueError):
        AssetService.confirm_dividend(event, "JCP", [
            DividendPayment("2027-06-30", 100, 0.035),
            DividendPayment("2027-12-30", 100, 0.035, 99999),
        ], revision)
    assert AssetService.get_dividend_payments("CMIG4") == []
    assert AssetService.get_local_projection_revision() == revision


def test_future_payment_in_current_month_does_not_enter_historical_received_totals(monkeypatch):
    class ReferenceDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 10)

    monkeypatch.setattr("services._portfolio_projection.datetime.date", ReferenceDate)
    AssetService.add_transaction("CMIG4", "2026-01-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2026-01-05", "JCP", 2.0)
    AssetService.add_dividend("CMIG4", "2026-01-20", "JCP", 3.0)
    history = PortfolioReadService.read_history().evolution
    assert history.iloc[-1]["cumulative_dividends"] == 2.0
    activity = AssetService.get_portfolio_activity(limit=None)
    assert activity.iloc[0]["event"] == "JCP - a receber"


def test_b3_can_be_explicitly_imported_as_separate_payment():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.035),
    ], AssetService.get_local_projection_revision())
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "30/06/2027",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": 0.035,
        "Valor da Operação": 3.5, "Entrada/Saída": "Crédito",
    }])
    key = AssetService.find_b3_dividend_candidates(statement)[0]["source_key"]
    assert AssetService.process_b3_import(statement, dividend_links={key: None}) == (0, 1)
    assert len(AssetService.get_dividend_payments("CMIG4")) == 2
    assert AssetService.process_b3_import(statement) == (0, 0)


def test_empty_remote_data_never_creates_a_zero_payment():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    service = AssetService(dividend_provider=FakeDividends([]))
    result = service.get_dividend_suggestions()
    assert result["suggestions"] == []
    assert result["unavailable"] == []
    assert service.get_dividend_payments("CMIG4") == []


def test_manual_payment_remains_reconcilable_after_its_scheduled_date(monkeypatch):
    class ReferenceDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 10)

    monkeypatch.setattr("core.daos.dividend_sync.datetime.date", ReferenceDate)
    AssetService.add_dividend("CMIG4", "2026-01-01", "JCP", 3.5, 100, 0.035)
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "02/01/2026",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": 0.03,
        "Valor da Operação": 3.0, "Entrada/Saída": "Crédito",
    }])
    candidates = AssetService.find_b3_dividend_candidates(statement)
    assert len(candidates) == 1
    receipt_id = candidates[0]["payments"][0]["id"]
    with pytest.raises(ValueError, match="Confirme"):
        AssetService.process_b3_import(statement)
    assert AssetService.process_b3_import(statement, dividend_links={
        candidates[0]["source_key"]: receipt_id,
    }) == (0, 1)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == 1
    assert payments[0]["date"] == "2026-01-02"
    assert payments[0]["total_value"] == 3.0


def test_equal_b3_credits_from_different_institutions_reconcile_distinct_installments():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.035),
        DividendPayment("2027-06-30", 100, 0.035),
    ], AssetService.get_local_projection_revision())
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "28/06/2027",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": 0.03,
        "Valor da Operação": 3.0, "Entrada/Saída": "Crédito",
        "Instituição": institution,
    } for institution in ("Banco de teste A", "Banco de teste B")])
    candidates = AssetService.find_b3_dividend_candidates(statement)
    assert len(candidates) == 2
    assert len({row["source_key"] for row in candidates}) == 2
    payments = AssetService.get_dividend_payments("CMIG4")
    links = {row["source_key"]: payment["id"]
             for row, payment in zip(candidates, payments, strict=True)}
    assert AssetService.process_b3_import(statement, dividend_links=links) == (0, 2)
    updated = AssetService.get_dividend_payments("CMIG4")
    assert len(updated) == 2
    assert [row["total_value"] for row in updated] == [3.0, 3.0]
    assert {row["date"] for row in updated} == {"2027-06-28"}
    assert AssetService.process_b3_import(statement) == (0, 0)


def test_equal_b3_credits_preserve_distinct_institutions_without_suggestions():
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "28/06/2027",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": 0.03,
        "Valor da Operação": 3.0, "Entrada/Saída": "Crédito",
        "Instituição": institution,
    } for institution in ("Banco de teste A", "Banco de teste B")])
    AssetService.process_b3_import(statement)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == 2
    assert sum(payment["total_value"] for payment in payments) == 6
    AssetService.process_b3_import(statement)
    assert len(AssetService.get_dividend_payments("CMIG4")) == 2


def test_dividend_imports_work_in_a_fresh_interpreter():
    import subprocess
    import sys

    result = subprocess.run([
        sys.executable, "-c",
        "from core.dividends import DividendEvent; "
        "from services.assets_service import AssetService",
    ], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr


def test_distinct_b3_institutions_with_different_totals_import_without_review():
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "02/01/2026",
        "Produto": "CMIG4", "Quantidade": quantity, "Preço unitário": 0.03,
        "Valor da Operação": quantity * 0.03, "Entrada/Saída": "Crédito",
        "Instituição": institution,
    } for institution, quantity in (("Banco de teste A", 100), ("Banco de teste B", 200))])
    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 2)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == 2
    assert sum(payment["total_value"] for payment in payments) == 9
    assert AssetService.process_b3_import(statement) == (0, 0)


@pytest.mark.parametrize("institution", ["Banco de teste A", ""])
def test_same_batch_distinct_credits_do_not_become_correction_candidates(institution):
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "02/01/2026",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": unit_price,
        "Valor da Operação": 100 * unit_price, "Entrada/Saída": "Crédito",
        "Instituição": institution,
    } for unit_price in (0.03, 0.06)])
    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 2)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == 2
    assert sum(payment["total_value"] for payment in payments) == 9
    assert AssetService.process_b3_import(statement) == (0, 0)


def test_prepared_dividend_search_uses_snapshot_without_reading_database_again(monkeypatch):
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    service = AssetService(dividend_provider=FakeDividends([event]))
    revision = service.get_local_projection_revision()
    search = service.prepare_dividend_search()
    AssetService.add_transaction("CMIG4", "2026-09-02", "BUY", 50, 10)
    def forbidden(*args, **kwargs):
        raise AssertionError("Background search must not read the database")
    monkeypatch.setattr(service._portfolio_repo, "get_personal_connection", forbidden)
    result = search()
    assert result["revision"] == revision
    assert result["suggestions"][0]["quantity"] == 100


@pytest.mark.parametrize("kind", ["DIVIDEND", "JCP", "YIELD"])
def test_registered_payment_is_silently_filtered_without_saving_a_decision(kind):
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2027-06-30", kind, 7, 100, 0.07)
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    service = AssetService(dividend_provider=FakeDividends([event]))
    revision = service.get_local_projection_revision()
    assert service.get_dividend_suggestions()["suggestions"] == []
    assert service.get_local_projection_revision() == revision
    assert service._portfolio_repo.get_dividend_reviews() == {}
    assert len(service.get_dividend_payments("CMIG4")) == 1


def test_registered_installment_is_silently_filtered():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2027-06-30", "JCP", 3.5, 100, 0.035)
    service = AssetService(dividend_provider=FakeDividends([
        DividendEvent("CMIG4", "2026-09-23", 0.07),
    ]))
    assert service.get_dividend_suggestions()["suggestions"] == []


def test_previous_payment_does_not_hide_a_new_event_with_the_same_unit_value():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2026-09-10", "JCP", 7, 100, 0.07)
    service = AssetService(dividend_provider=FakeDividends([
        DividendEvent("CMIG4", "2026-09-23", 0.07),
    ]))
    result = service.get_dividend_suggestions()
    assert len(result["suggestions"]) == 1


def test_receipt_linked_to_another_event_does_not_hide_a_new_dividend():
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    first = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(first, "JCP", [
        DividendPayment("2027-06-30", 100, 0.07),
    ], AssetService.get_local_projection_revision())
    second = DividendEvent("CMIG4", "2026-09-24", 0.07)
    result = AssetService(dividend_provider=FakeDividends([first, second])).get_dividend_suggestions()
    assert [item["event"] for item in result["suggestions"]] == [second]


@pytest.mark.parametrize("announced,registered", [
    (0.069913, 0.035),
    (0.0349567, 0.035),
    (0.07, 0.0595),
    (0.10, 0.03),
])
def test_possible_legacy_duplicates_are_silently_filtered(announced, registered):
    AssetService.add_transaction("CMIG4", "2026-09-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2027-06-30", "JCP", round(100 * registered, 2), 100, registered)
    service = AssetService(dividend_provider=FakeDividends([
        DividendEvent("CMIG4", "2026-09-23", announced),
    ]))
    revision = service.get_local_projection_revision()
    result = service.get_dividend_suggestions()
    assert result["suggestions"] == []
    assert service.get_local_projection_revision() == revision
    assert service.get_dividend_payments("CMIG4")[0]["unit_price"] == registered


def test_paid_history_is_filtered_while_unmatched_event_remains_pending():
    AssetService.add_transaction("CMIG4", "2026-01-01", "BUY", 100, 10)
    AssetService.add_dividend("CMIG4", "2026-06-30", "JCP", 3.5, 100, 0.035)
    paid = DividendEvent("CMIG4", "2026-03-23", 0.07)
    pending = DividendEvent("CMIG4", "2026-09-23", 0.07)
    service = AssetService(dividend_provider=FakeDividends([paid, pending]))
    revision = service.get_local_projection_revision()
    result = service.get_dividend_suggestions()
    assert [item["event"] for item in result["suggestions"]] == [pending]
    assert service.get_local_projection_revision() == revision
    assert len(service.get_dividend_payments("CMIG4")) == 1


def test_source_failure_for_closed_position_is_not_reported_as_unavailable():
    today = datetime.date.today()
    buy_date = (today - datetime.timedelta(days=60)).isoformat()
    sale_date = (today - datetime.timedelta(days=1)).isoformat()
    AssetService.add_transaction("NUBR33", buy_date, "BUY", 100, 10)
    AssetService.add_transaction("NUBR33", sale_date, "SELL", 100, 10)

    class Unavailable:
        def get_events(self, ticker, start_date):
            raise TimeoutError("unavailable")

    service = AssetService(dividend_provider=Unavailable())
    revision = service.get_local_projection_revision()
    result = service.get_dividend_suggestions()
    assert result["unavailable"] == []
    assert result["suggestions"] == []
    assert service.get_local_projection_revision() == revision


def test_closed_position_still_preserves_historical_dividend_entitlement():
    today = datetime.date.today()
    buy_date = (today - datetime.timedelta(days=60)).isoformat()
    sale_date = (today - datetime.timedelta(days=1)).isoformat()
    ex_date = (today - datetime.timedelta(days=30)).isoformat()
    AssetService.add_transaction("NUBR33", buy_date, "BUY", 100, 10)
    AssetService.add_transaction("NUBR33", sale_date, "SELL", 100, 10)
    event = DividendEvent("NUBR33", ex_date, 0.07)
    service = AssetService(dividend_provider=FakeDividends([event]))
    result = service.get_dividend_suggestions()
    assert result["unavailable"] == []
    assert [item["event"] for item in result["suggestions"]] == [event]
    assert result["suggestions"][0]["quantity"] == 100


@pytest.mark.parametrize("origin", ["manual", "b3"])
def test_b3_metadata_conflict_requires_review_even_when_date_and_total_match(origin):
    def statement(quantity, unit_price):
        return pd.DataFrame([{
            "Movimentação": "Juros Sobre Capital Próprio", "Data": "02/01/2026",
            "Produto": "CMIG4", "Quantidade": quantity, "Preço unitário": unit_price,
            "Valor da Operação": 7.0, "Entrada/Saída": "Crédito",
            "Instituição": "Banco de teste A",
        }])

    if origin == "manual":
        AssetService.add_dividend("CMIG4", "2026-01-02", "JCP", 7, 100, 0.07)
    else:
        assert AssetService.process_b3_import(statement(100, 0.07)) == (0, 1)
    corrected = statement(200, 0.035)
    candidates = AssetService.find_b3_dividend_candidates(corrected)
    assert len(candidates) == 1
    with pytest.raises(ValueError, match="Confirme"):
        AssetService.process_b3_import(corrected)
    receipt_id = candidates[0]["payments"][0]["id"]
    assert AssetService.process_b3_import(corrected, dividend_links={
        candidates[0]["source_key"]: receipt_id,
    }) == (0, 1)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == 1
    assert payments[0]["quantity"] == 200
    assert payments[0]["unit_price"] == 0.035
    assert payments[0]["total_value"] == 7
    assert AssetService.process_b3_import(corrected) == (0, 0)


@pytest.mark.parametrize("confirmed_kind,b3_movement,b3_kind", [
    ("DIVIDEND", "Juros Sobre Capital Próprio", "JCP"),
    ("JCP", "Dividendo", "DIVIDEND"),
])
@pytest.mark.parametrize("separate", [False, True])
def test_b3_reviews_yahoo_payment_with_different_type(confirmed_kind, b3_movement, b3_kind, separate):
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, confirmed_kind, [
        DividendPayment("2027-06-30", 100, 0.07),
    ], AssetService.get_local_projection_revision())
    payment_id = AssetService.get_dividend_payments("CMIG4")[0]["id"]
    statement = pd.DataFrame([{
        "Movimentação": b3_movement, "Data": "30/06/2027", "Produto": "CMIG4",
        "Quantidade": 100, "Preço unitário": 0.07, "Valor da Operação": 7,
        "Entrada/Saída": "Crédito", "Instituição": "Banco de teste A",
    }])
    candidates = AssetService.find_b3_dividend_candidates(statement)
    assert len(candidates) == 1
    assert candidates[0]["payments"][0]["id"] == payment_id
    revision = AssetService.get_local_projection_revision()
    with pytest.raises(ValueError, match="Confirme"):
        AssetService.process_b3_import(statement)
    assert AssetService.get_local_projection_revision() == revision
    assert AssetService.process_b3_import(statement, dividend_links={
        candidates[0]["source_key"]: None if separate else payment_id,
    }) == (0, 1)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == (2 if separate else 1)
    assert sum(row["total_value"] for row in payments) == (14 if separate else 7)
    authoritative = next(row for row in payments if row["dividend_type"] == b3_kind)
    assert authoritative["quantity"] == 100
    assert authoritative["unit_price"] == 0.07
    if not separate:
        assert authoritative["id"] == payment_id
    assert AssetService.process_b3_import(statement) == (0, 0)


def test_yahoo_payment_already_reconciled_by_b3_is_not_offered_across_types():
    event = DividendEvent("CMIG4", "2026-09-23", 0.07)
    AssetService.confirm_dividend(event, "JCP", [
        DividendPayment("2027-06-30", 100, 0.07),
    ], AssetService.get_local_projection_revision())
    statement = pd.DataFrame([{
        "Movimentação": "Juros Sobre Capital Próprio", "Data": "30/06/2027",
        "Produto": "CMIG4", "Quantidade": 100, "Preço unitário": 0.07,
        "Valor da Operação": 7, "Entrada/Saída": "Crédito",
        "Instituição": "Banco de teste A",
    }])
    candidate = AssetService.find_b3_dividend_candidates(statement)[0]
    receipt_id = candidate["payments"][0]["id"]
    AssetService.process_b3_import(statement, dividend_links={candidate["source_key"]: receipt_id})
    statement["Movimentação"] = "Dividendo"
    assert AssetService.find_b3_dividend_candidates(statement) == []
    assert AssetService.process_b3_import(statement) == (0, 1)
    payments = AssetService.get_dividend_payments("CMIG4")
    assert len(payments) == 2
    assert {row["dividend_type"] for row in payments} == {"JCP", "DIVIDEND"}

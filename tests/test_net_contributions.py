import pandas as pd
import pytest

from services.assets_service import AssetService


def test_same_month_reallocation_is_not_a_new_contribution():
    assert AssetService.add_transaction("BBAS3", "2024-01-01", "BUY", 100, 100)
    assert AssetService.add_transaction("BBAS3", "2024-02-01", "SELL", 100, 100)
    assert AssetService.add_transaction("CXSE3", "2024-02-02", "BUY", 100, 100)

    monthly = AssetService.get_monthly_contributions_by_year(start_date="2024-02-01")

    assert monthly.to_dict("records") == [{"year": "2024", "month": "02", "amount": 0.0}]
    assert AssetService.get_ytd_contributions(2024) == 10_000


@pytest.mark.parametrize(
    "buy_fees,sell_fees,expected", [(0, 0, 0), (10, 0, 10), (0, 20, 20), (10, 20, 30)]
)
def test_reallocation_counts_purchase_and_sale_fees(buy_fees, sell_fees, expected):
    assert AssetService.add_transaction("BBAS3", "2023-12-01", "BUY", 100, 100)
    assert AssetService.add_transaction("BBAS3", "2024-01-01", "SELL", 100, 100, sell_fees)
    assert AssetService.add_transaction("CXSE3", "2024-01-02", "BUY", 100, 100, buy_fees)

    monthly = AssetService.get_monthly_contributions_by_year("2024-01-01")

    assert monthly.to_dict("records") == [{"year": "2024", "month": "01", "amount": expected}]
    assert AssetService.get_ytd_contributions(2024) == expected
    evolution = AssetService.calculate_historical_evolution("2024-01-01")
    assert evolution.iloc[-1]["cumulative_invested"] == expected


def test_sale_and_purchase_in_different_months_preserve_negative_cash_flow():
    assert AssetService.add_transaction("BBAS3", "2023-12-01", "BUY", 100, 100)
    assert AssetService.add_transaction("BBAS3", "2024-01-01", "SELL", 100, 100, 20)
    assert AssetService.add_transaction("CXSE3", "2024-02-01", "BUY", 50, 100, 10)

    monthly = AssetService.get_monthly_contributions_by_year("2024-01-01")

    assert monthly.to_dict("records") == [
        {"year": "2024", "month": "01", "amount": -9_980},
        {"year": "2024", "month": "02", "amount": 5_010},
    ]
    assert AssetService.get_ytd_contributions(2024) == -4_970
    assert AssetService.get_monthly_contributions_by_year("2024-02-01")["amount"].sum() == 5_010


def test_empty_portfolio_has_zero_ytd_and_no_monthly_contributions():
    assert AssetService.get_ytd_contributions(2024) == 0
    assert AssetService.get_monthly_contributions_by_year().empty


def test_grouping_does_not_create_contributions():
    assert AssetService.add_transaction("BBAS3", "2024-01-01", "GROUP", 10, 999, 10)

    assert AssetService.get_ytd_contributions(2024) == 0
    assert AssetService.get_monthly_contributions_by_year().empty


def test_pending_trade_before_selected_period_does_not_withhold_totals():
    frame = pd.DataFrame([{
        "Movimentação": "Aquisição",
        "Data": "02/01/2023",
        "Produto": "BBAS3",
        "Quantidade": 100,
        "Preço unitário": None,
        "Valor da Operação": None,
        "Entrada/Saída": "Crédito",
    }])
    assert AssetService.process_b3_import(frame) == (1, 0)
    assert AssetService.add_transaction("BBAS3", "2024-01-01", "SELL", 100, 10, 20)

    assert AssetService.get_ytd_contributions(2023) is None
    assert AssetService.get_monthly_contributions_by_year().empty
    assert AssetService.get_ytd_contributions(2024) == -980
    assert AssetService.get_monthly_contributions_by_year("2024-01-01").to_dict("records") == [
        {"year": "2024", "month": "01", "amount": -980},
    ]

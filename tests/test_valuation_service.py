import pytest

from core.strings import MODEL_CLASSIC, MODEL_IPCA_SPREAD, MODEL_SELIC
from services.valuation_service import ValuationService


@pytest.mark.parametrize(
    ("model", "kwargs", "expected"),
    [
        (MODEL_CLASSIC, {"classic_target_yield": 6.0}, 6.0),
        (MODEL_SELIC, {"selic_rate": 13.75}, 13.75),
        (MODEL_IPCA_SPREAD, {"ipca_rate": 4.5, "target_spread": 3.0}, 7.5),
    ],
)
def test_calculate_target_yield_for_each_bazin_model(model, kwargs, expected):
    assert ValuationService.calculate_target_yield(model, **kwargs) == expected


def test_calculate_bazin_ceiling_price_converts_percentage_to_decimal():
    assert ValuationService.calculate_bazin_ceiling_price(1.20, 6.0) == pytest.approx(20.0)


def test_calculate_bazin_ceiling_price_returns_zero_for_non_positive_yield():
    assert ValuationService.calculate_bazin_ceiling_price(1.20, 0.0) == 0.0


def test_calculate_required_dividend_uses_the_target_yield_percentage():
    assert ValuationService.calculate_required_dividend(20.0, 6.0) == pytest.approx(1.2)


def test_calculate_dividend_yield_and_margin_of_safety():
    assert ValuationService.calculate_dividend_yield(1.2, 15.0) == pytest.approx(8.0)
    assert ValuationService.calculate_margin_of_safety(15.0, 20.0) == pytest.approx(100 / 3)


@pytest.mark.parametrize("invalid_price", [None, 0.0, float("nan")])
def test_valuation_ratios_reject_invalid_current_prices(invalid_price):
    assert ValuationService.calculate_dividend_yield(1.2, invalid_price) is None
    assert ValuationService.calculate_margin_of_safety(invalid_price, 20.0) is None


def test_apply_bazin_valuation_adds_derived_values_without_mutating_raw_data():
    raw_data = {
        "avg_dividend_5y": 1.20,
        "current_price": 20.0,
        "dividends_history": {2025: 1.284, 2024: 2.832, 2023: 2.486},
        "annual_closing_prices": {
            2025: 23.8662,
            2024: 26.1980,
            2023: 30.1333,
        },
    }

    valued = ValuationService.apply_bazin_valuation(raw_data, 6.0)

    assert valued["ceiling_price"] == pytest.approx(20.0)
    assert valued["avg_dy_5y"] == pytest.approx(6.0)
    assert valued["margin_of_safety_pct"] == pytest.approx(0.0)
    assert valued["required_dividend"] == pytest.approx(1.2)
    assert valued["dividend_yields_history"][2025] == pytest.approx(5.38, abs=0.01)
    assert valued["dividend_yields_history"][2024] == pytest.approx(10.81, abs=0.01)
    assert valued["dividend_yields_history"][2023] == pytest.approx(8.25, abs=0.01)
    assert "ceiling_price" not in raw_data

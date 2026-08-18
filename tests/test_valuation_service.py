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


def test_apply_bazin_valuation_adds_derived_values_without_mutating_raw_data():
    raw_data = {"avg_dividend_5y": 1.20, "current_price": 15.0}

    valued = ValuationService.apply_bazin_valuation(raw_data, 6.0)

    assert valued["ceiling_price"] == pytest.approx(20.0)
    assert valued["avg_dy_5y"] == pytest.approx(8.0)
    assert "ceiling_price" not in raw_data

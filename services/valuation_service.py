"""Pure Bazin valuation rules.

This module deliberately has no Streamlit, database, or market-data dependency so
the financial rules can be used and tested independently of the presentation and
integration layers.
"""

from core.strings import MODEL_IPCA_SPREAD, MODEL_SELIC


class ValuationService:
    """Calculates Bazin target yields and ceiling prices."""

    @staticmethod
    def calculate_target_yield(
        model: str,
        *,
        classic_target_yield: float = 6.0,
        selic_rate: float = 0.0,
        ipca_rate: float = 0.0,
        target_spread: float = 0.0,
    ) -> float:
        """Return the annual target yield percentage for the selected model.

        Unknown persisted model values fall back to the classic model, preserving
        the application's previous behaviour for legacy configurations.
        """
        if model == MODEL_SELIC:
            return float(selic_rate)
        if model == MODEL_IPCA_SPREAD:
            return float(ipca_rate) + float(target_spread)
        return float(classic_target_yield)

    @staticmethod
    def calculate_bazin_ceiling_price(avg_dividend_5y: float, target_yield_pct: float) -> float:
        """Return Bazin's ceiling price from the five-year dividend average."""
        target_yield_decimal = float(target_yield_pct) / 100
        return float(avg_dividend_5y) / target_yield_decimal if target_yield_decimal > 0 else 0.0

    @staticmethod
    def calculate_average_dividend_yield(avg_dividend_5y: float, current_price: float) -> float:
        """Return the five-year average dividend yield as a percentage."""
        return (float(avg_dividend_5y) / float(current_price) * 100) if current_price > 0 else 0.0

    @staticmethod
    def calculate_required_dividend(current_price: float, target_yield_pct: float) -> float:
        """Return the annual dividend per share required for a target Bazin yield."""
        return float(current_price) * (float(target_yield_pct) / 100)

    @classmethod
    def apply_bazin_valuation(cls, raw_market_data: dict, target_yield_pct: float) -> dict:
        """Copy raw market data and add its Bazin ceiling and average yield."""
        data = raw_market_data.copy()
        avg_dividend_5y = data.get("avg_dividend_5y", 0.0)
        current_price = data.get("current_price", 0.0)
        data["ceiling_price"] = cls.calculate_bazin_ceiling_price(avg_dividend_5y, target_yield_pct)
        data["avg_dy_5y"] = cls.calculate_average_dividend_yield(avg_dividend_5y, current_price)
        return data

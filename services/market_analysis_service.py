"""Portfolio-aware orchestration for market analysis."""

import datetime
import math

from core.ports import DividendCorrectionPort, MarketDataPort
from services.valuation_service import ValuationService


class MarketAnalysisService:
    """Combine cached remote market data with active-portfolio corrections."""

    def __init__(
        self,
        remote_market_data: MarketDataPort,
        correction_repo: DividendCorrectionPort,
    ):
        self._remote_market_data = remote_market_data
        self._correction_repo = correction_repo

    def get_ticker_market_analysis(self, ticker: str, target_yield_pct: float = 6.0) -> dict:
        """Return the final portfolio-aware analysis for a normalized ticker."""
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            return {}

        reference_year = datetime.date.today().year
        try:
            snapshot = self._remote_market_data.get_ticker_market_snapshot(
                normalized_ticker, reference_year
            )
        except Exception:
            return {}

        if not snapshot:
            return {}
        try:
            current_price = float(snapshot.get("current_price", 0.0))
        except (TypeError, ValueError):
            return {}
        if not math.isfinite(current_price) or current_price <= 0:
            return {}

        try:
            corrections = self._correction_repo.get_dividend_corrections(normalized_ticker)
        except Exception:
            return {}

        try:
            corrections = {int(year): float(total) for year, total in corrections.items()}
        except (AttributeError, TypeError, ValueError):
            return {}
        if any(not math.isfinite(total) or total <= 0 for total in corrections.values()):
            return {}

        analysis = snapshot.copy()
        dividends_5y = dict(snapshot.get("dividends_5y", {}))
        dividends_history = dict(snapshot.get("dividends_history", {}))
        annual_closing_prices = dict(snapshot.get("annual_closing_prices", {}))

        for year, corrected_total in corrections.items():
            if year in dividends_5y:
                dividends_5y[year] = corrected_total
            if year in dividends_history:
                dividends_history[year] = corrected_total

        listing_year = analysis.pop("listing_year", None)
        history_listing_year = analysis.pop("history_listing_year", None)
        if listing_year is None and any(dividends_history.values()):
            listing_year = history_listing_year

        average_period = [
            year
            for year in range(reference_year - 1, reference_year - 6, -1)
            if listing_year is None or year >= listing_year
        ]
        average_years = len(average_period)

        analysis["dividends_5y"] = dividends_5y
        analysis["dividends_history"] = dividends_history
        analysis["annual_closing_prices"] = (
            annual_closing_prices if any(dividends_history.values()) else {}
        )
        analysis["avg_dividend_5y"] = (
            sum(dividends_5y.get(year, 0.0) for year in average_period) / average_years
            if average_years
            else 0.0
        )
        analysis["dividend_average_years"] = average_years
        analysis["dividend_history_status"] = (
            "complete" if average_years == 5 else "partial" if average_years > 0 else "unavailable"
        )
        return ValuationService.apply_bazin_valuation(analysis, target_yield_pct)

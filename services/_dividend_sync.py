"""Internal dividend review use cases owned by AssetService."""

import datetime
import logging
import math

from core.dividends import DividendEvent, DividendPayment
from core.ports import DividendProvider, PortfolioPort
from core.utils.ticker import normalize_b3_ticker
from services._portfolio_projection import PortfolioProjection

logger = logging.getLogger(__name__)


class DividendSync:
    def __init__(self, repository: PortfolioPort, provider: DividendProvider | None):
        self.repository = repository
        self.provider = provider

    def suggestions(self, ticker=None):
        return self.prepare_search(ticker)()

    def prepare_search(self, ticker=None):
        """Capture local inputs before handing remote work to a background worker."""
        if ticker is not None:
            ticker = normalize_b3_ticker(ticker)
        ledger = self.repository.load_ledger()
        reviewed = self.repository.get_dividend_reviews()
        provider = self.provider
        return lambda: self._search_snapshot(ticker, ledger, reviewed, provider)

    @staticmethod
    def _search_snapshot(ticker, ledger, reviewed, provider):
        projection = PortfolioProjection(ledger, None, None, None)
        transactions = ledger.transactions
        tickers = [ticker] if ticker else sorted(transactions["ticker"].unique())
        suggestions = []
        linked_ids = {
            receipt_id
            for review in reviewed.values()
            for receipt_id in review.get("receipt_ids", [])
        }
        unavailable = []
        changed = []
        today = datetime.date.today().isoformat()
        for symbol in tickers:
            records = transactions.loc[transactions["ticker"].eq(symbol)]
            if records.empty:
                continue
            start = records["date"].min()
            try:
                if provider is None:
                    raise RuntimeError("Dividend provider unavailable")
                events = provider.get_events(symbol, start)
                seen = set()
                for event in events:
                    event.validate()
                    if event.ticker != symbol or event.ex_date < start:
                        continue
                    if event.source_key in seen:
                        continue
                    seen.add(event.source_key)
                    if event.source_key in reviewed:
                        if reviewed[event.source_key]["unit_value"] != event.unit_value:
                            changed.append(symbol)
                        continue
                    cutoff = (
                        datetime.date.fromisoformat(event.ex_date) - datetime.timedelta(days=1)
                    ).isoformat()
                    quantity = projection.quantity_on_date(symbol, cutoff)
                    if quantity <= 0:
                        continue
                    existing = ledger.dividends.loc[ledger.dividends["ticker"].eq(symbol)]
                    available = [
                        row
                        for row in existing.to_dict("records")
                        if row["id"] not in linked_ids and row["date"] >= event.ex_date
                    ]
                    if any(
                        DividendSync._possible_payment(event, quantity, row) for row in available
                    ):
                        continue
                    suggestions.append(
                        {"event": event, "quantity": quantity, "existing": available}
                    )
            except Exception as error:
                logger.warning("dividends.source_failed error_type=%s", type(error).__name__)
                if projection.quantity_on_date(symbol, today) > 0:
                    unavailable.append(symbol)
        return {
            "suggestions": suggestions,
            "unavailable": unavailable,
            "changed": sorted(set(changed)),
            "revision": ledger.revision,
        }

    @staticmethod
    def _possible_payment(event, quantity, payment):
        """Suppress uncertain legacy matches without recording a review decision."""
        unit_price = payment.get("unit_price")
        if unit_price is None or not math.isfinite(unit_price) or unit_price <= 0:
            paid_quantity = payment.get("quantity")
            if paid_quantity is None or not math.isfinite(paid_quantity) or paid_quantity <= 0:
                paid_quantity = quantity
            unit_price = payment["total_value"] / paid_quantity
        if 0 < unit_price <= event.unit_value:
            return True
        tolerance = 5e-4 if unit_price == round(unit_price, 3) else 5e-7
        return math.isclose(unit_price, event.unit_value, rel_tol=1e-5, abs_tol=tolerance)

    @staticmethod
    def prepare(event: DividendEvent, kind: str, payments: list[DividendPayment]):
        event.validate()
        if kind not in {"DIVIDEND", "JCP", "YIELD"}:
            raise ValueError("Confirme o tipo do provento.")
        if not payments:
            raise ValueError("Informe pelo menos uma parcela.")
        records = [payment.to_record() for payment in payments]
        linked = [row["existing_id"] for row in records if row["existing_id"] is not None]
        if len(linked) != len(set(linked)):
            raise ValueError("Cada pagamento existente pode ser associado a apenas uma parcela.")
        return records

    def confirm(self, event, kind, payments, revision):
        records = self.prepare(event, kind, payments)
        return self.repository.save_dividend_review(event, kind, records, revision)

    def ignore(self, event, revision):
        event.validate()
        return self.repository.save_dividend_review(event, None, [], revision)

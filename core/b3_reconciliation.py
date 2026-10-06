"""Shared B3 reconciliation policy and explicit, import-scoped context."""

import json
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd


@dataclass(frozen=True)
class B3ImportRequest:
    """One normalized source record and the user's optional confirmed manual group."""

    record: dict
    occurrence_count: int
    confirmed_manual_ids: tuple[int, ...] | None = None


@dataclass
class B3ImportContext:
    """Batch-local state; database writes remain atomic for each request separately.

    Multiplicity describes the current export, not a stable identity across exports.
    Consumed IDs prevent an existing B3 transaction from covering two source rows.
    Callers create requests here rather than annotating normalized source records.
    """

    occurrence_counts: Counter = field(default_factory=Counter)
    confirmed_links: dict[str, tuple[int, ...]] = field(default_factory=dict)
    consumed_transaction_ids: set[int] = field(default_factory=set)

    @staticmethod
    def _identity(record: dict) -> tuple:
        source = json.loads(record["source_record"])
        return (
            record["date"],
            record["ticker"],
            record["transaction_type"],
            record["quantity"],
            source.get("movement", ""),
            source.get("direction", ""),
            source.get("institution", ""),
        )

    @classmethod
    def from_records(
        cls, records: list[dict], manual_trade_links: dict[str, int | list[int]] | None = None
    ) -> "B3ImportContext":
        counts = Counter(
            cls._identity(record)
            for record in records
            if record.get("source_key") and record.get("source_record")
        )
        links = {}
        for source_key, selected in (manual_trade_links or {}).items():
            if selected is not None:
                values = selected if isinstance(selected, (list, tuple, set)) else [selected]
                links[source_key] = tuple(int(value) for value in values)
        return cls(counts, links)

    def request(self, record: dict) -> B3ImportRequest:
        return B3ImportRequest(
            record=dict(record),
            occurrence_count=self.occurrence_counts[self._identity(record)],
            confirmed_manual_ids=self.confirmed_links.get(record["source_key"]),
        )


class B3ReconciliationPolicy:
    """Pure decisions shared by suggestion searches and locked SQLite confirmation."""

    PRICE_TOLERANCE = 0.0005
    FLOAT_MARGIN = 1e-12

    @staticmethod
    def date_gap(record: dict) -> tuple[int, int]:
        return (0, 0) if record.get("date_is_business") else (2, 6)

    @classmethod
    def value_tolerance(cls, quantity: int) -> float:
        return max(0.02, quantity * cls.PRICE_TOLERANCE + 0.01)

    @classmethod
    def search_value_bounds(cls, record: dict, source: dict) -> tuple[Decimal, Decimal]:
        """Conservative lookup bounds; matches_manual_group makes the final decision."""
        quantity = int(record["quantity"])
        price = Decimal(str(record["unit_price"]))
        margin = Decimal(str(cls.PRICE_TOLERANCE)) + Decimal(str(cls.FLOAT_MARGIN))
        lower, upper = quantity * (price - margin), quantity * (price + margin)
        if source.get("value") is not None:
            value = Decimal(str(source["value"]))
            tolerance = Decimal(str(cls.value_tolerance(quantity)))
            lower, upper = max(lower, value - tolerance), min(upper, value + tolerance)
        return lower - Decimal("1e-8"), upper + Decimal("1e-8")

    @classmethod
    def matches_manual_group(cls, record: dict, rows: list[dict]) -> bool:
        if not rows or len({row["id"] for row in rows}) != len(rows):
            return False
        minimum_gap, maximum_gap = cls.date_gap(record)
        if len({row["date"] for row in rows}) != 1 or any(
            row["ticker"] != record["ticker"]
            or row["transaction_type"] != record["transaction_type"]
            or row.get("transaction_origin", "MANUAL") != "MANUAL"
            or not minimum_gap
            <= (pd.Timestamp(record["date"]) - pd.Timestamp(row["date"])).days
            <= maximum_gap
            for row in rows
        ):
            return False
        quantity = sum(int(row["quantity"]) for row in rows)
        if quantity <= 0 or quantity != int(record["quantity"]):
            return False
        total = sum(int(row["quantity"]) * float(row["unit_price"]) for row in rows)
        if abs(total / quantity - float(record["unit_price"])) > (
            cls.PRICE_TOLERANCE + cls.FLOAT_MARGIN
        ):
            return False
        value = json.loads(record["source_record"]).get("value")
        return value is None or abs(float(value) - total) <= cls.value_tolerance(quantity)

    @staticmethod
    def has_sufficient_cost_history(history: pd.DataFrame, required_quantity: int) -> bool:
        quantity, known_quantity, known_zero_cost_quantity, cost = 0, 0.0, 0.0, 0.0
        for row in history.to_dict("records"):
            qty = row["quantity"]
            if row["transaction_type"] == "BUY":
                if row.get("cost_status") != "PENDING":
                    is_zero_cost_deposit = (
                        row.get("event_kind") == "TRADE" and row["unit_price"] == 0
                    )
                    quantity_factor = known_quantity / quantity if quantity > 0 else 1.0
                    known_quantity += (
                        qty
                        if is_zero_cost_deposit
                        else qty * quantity_factor
                        if row["unit_price"] == 0
                        else qty
                    )
                    if is_zero_cost_deposit:
                        known_zero_cost_quantity += qty
                    elif row.get("event_kind") != "TRADE" and row["unit_price"] == 0:
                        known_zero_cost_quantity += (
                            qty * quantity_factor if known_zero_cost_quantity > 0 else 0.0
                        )
                    cost += qty * row["unit_price"] + row["fees"]
                quantity += qty
            elif row["transaction_type"] == "SELL":
                remaining = max(0, quantity - qty)
                cost = cost * remaining / quantity if quantity else 0.0
                known_quantity = known_quantity * remaining / quantity if quantity else 0.0
                known_zero_cost_quantity = (
                    known_zero_cost_quantity * remaining / quantity if quantity else 0.0
                )
                quantity = remaining
            elif row["transaction_type"] == "GROUP":
                known_quantity = known_quantity * qty / quantity if quantity else 0.0
                known_zero_cost_quantity = (
                    known_zero_cost_quantity * qty / quantity if quantity else 0.0
                )
                quantity = qty
        return known_quantity >= required_quantity and (
            cost > 0 or known_zero_cost_quantity >= required_quantity
        )

"""Confirmed payment dates and remote event dates are deliberately different inputs."""

import datetime
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class DividendEvent:
    ticker: str
    ex_date: str
    unit_value: float

    @property
    def source_key(self) -> str:
        return f"yahoo-dividend:{self.ticker}:{self.ex_date}"

    def validate(self) -> None:
        from core.utils.ticker import normalize_b3_ticker

        if normalize_b3_ticker(self.ticker) != self.ticker:
            raise ValueError("Confira o ticker do provento.")
        datetime.date.fromisoformat(self.ex_date)
        positive_number(self.unit_value)


@dataclass(frozen=True)
class DividendPayment:
    date: str
    quantity: float
    unit_value: float
    existing_id: int | None = None

    def to_record(self) -> dict:
        try:
            date = datetime.date.fromisoformat(self.date).isoformat()
            quantity = positive_number(self.quantity)
            unit_value = positive_number(self.unit_value)
        except (ValueError, TypeError) as error:
            raise ValueError(
                "Informe data de pagamento, quantidade e valor por ação válidos."
            ) from error
        total = float(
            (Decimal(str(quantity)) * Decimal(str(unit_value))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        positive_number(total)
        return {
            "date": date,
            "quantity": quantity,
            "unit_price": unit_value,
            "total_value": total,
            "existing_id": self.existing_id,
        }


def positive_number(value) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Informe um valor positivo e finito.")
    return result


def payment_event_label(kind: str, date: str, today: datetime.date | None = None) -> str:
    label = {"DIVIDEND": "Dividendo", "JCP": "JCP", "YIELD": "Rendimento"}.get(kind, kind)
    if date > (today or datetime.date.today()).isoformat():
        label += " - a receber"
    return label

"""Shared event classification for display and database history filters."""

import json

ACTIVITY_EVENTS = (
    "Compra",
    "Venda",
    "Dividendo",
    "JCP",
    "Rendimento",
    "Grupamento",
    "Desdobro",
    "Bonificação",
    "Desdobro / Bonificação",
    "Transferência recebida",
    "Evento societário",
)
ACTIVITY_PAGE_SIZE = 25
ACTIVITY_EVENT_FIELDS = (
    "source",
    "event_type",
    "event_kind",
    "source_record",
    "cost_status",
    "unit_price",
    "fees",
)


def activity_event(row):
    """Keep event names identical when filtering in SQLite and rendering in services."""
    source, event_type, event_kind, source_record, cost_status, price, fees = (
        row[field] for field in ACTIVITY_EVENT_FIELDS
    )
    labels = {
        "BUY": "Compra",
        "SELL": "Venda",
        "GROUP": "Grupamento",
        "DIVIDEND": "Dividendo",
        "JCP": "JCP",
        "YIELD": "Rendimento",
    }
    if source == "dividend":
        return labels.get(event_type, "Evento societário")
    if event_kind == "CUSTODY":
        return "Transferência recebida"
    if cost_status == "PENDING" or event_type == "GROUP":
        return labels.get(event_type, "Evento societário")
    if event_kind == "CORPORATE":
        try:
            record = json.loads(source_record)
        except (TypeError, ValueError):
            record = {}
        movement = str(record.get("movement", "")).casefold() if isinstance(record, dict) else ""
        if "bonifica" in movement:
            return "Bonificação"
        if "desdobr" in movement:
            return "Desdobro"
        return "Evento societário"
    if event_type == "BUY" and not isinstance(event_kind, str) and price == 0 and fees == 0:
        return "Desdobro / Bonificação"
    return labels.get(event_type, "Evento societário")

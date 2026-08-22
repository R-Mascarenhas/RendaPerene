"""Pure transformations for historical dividend events."""

from collections.abc import Iterable
from datetime import date


def count_dividend_events_by_month(events: Iterable[dict]) -> list[int]:
    """Count dividend events for each calendar month from January to December."""
    month_counts = [0] * 12
    for event in events:
        event_date = event.get("date")
        if not event_date:
            continue
        month = int(str(event_date)[5:7])
        if 1 <= month <= 12:
            month_counts[month - 1] += 1
    return month_counts


def build_dividend_event_heatmap(events: Iterable[dict], current_year: int) -> dict:
    """Build an eleven-year event matrix and its month-by-month recurrence summary."""
    years = list(range(current_year, current_year - 11, -1))
    events_by_year = {year: [0] * 12 for year in years}
    event_details_by_year = {year: [[] for _ in range(12)] for year in years}

    for event in events:
        event_date = str(event.get("date", ""))
        try:
            year = int(event_date[:4])
            month = int(event_date[5:7])
        except ValueError:
            continue
        if year in events_by_year and 1 <= month <= 12:
            events_by_year[year][month - 1] += 1
            event_details_by_year[year][month - 1].append(event)

    recurrence = [sum(events_by_year[year][month] > 0 for year in years) for month in range(12)]
    return {
        "years": years,
        "events_by_year": events_by_year,
        "event_details_by_year": event_details_by_year,
        "recurrence": recurrence,
    }


def get_recent_dividend_payments(events: Iterable[dict], limit: int = 5) -> list[dict]:
    """Return the most recent Yahoo Finance dividend payments in descending date order."""
    valid_events = []
    for event in events:
        try:
            payment_date = date.fromisoformat(str(event["date"]))
            value = float(event["value"])
        except (KeyError, TypeError, ValueError):
            continue
        valid_events.append({"date": payment_date, "value": value})

    return sorted(valid_events, key=lambda event: event["date"], reverse=True)[:limit]

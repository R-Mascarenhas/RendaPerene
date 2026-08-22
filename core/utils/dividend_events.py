"""Pure transformations for historical dividend events."""

from collections.abc import Iterable
from datetime import date


def build_dividend_event_heatmap(
    events: Iterable[dict], current_year: int, current_month: int
) -> dict:
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

    recurrence = []
    recurrence_opportunities = []
    for month in range(12):
        opportunity_years = years if month + 1 < current_month else years[1:]
        recurrence.append(sum(events_by_year[year][month] > 0 for year in opportunity_years))
        recurrence_opportunities.append(len(opportunity_years))
    recurrence_ratio = [
        count / opportunities
        for count, opportunities in zip(recurrence, recurrence_opportunities, strict=True)
    ]
    presence_by_year = {year: [int(count > 0) for count in events_by_year[year]] for year in years}
    totals_by_year = {
        year: [
            sum(float(event["value"]) for event in event_details_by_year[year][month])
            for month in range(12)
        ]
        for year in years
    }
    return {
        "years": years,
        "recurrence": recurrence,
        "recurrence_opportunities": recurrence_opportunities,
        "recurrence_ratio": recurrence_ratio,
        "presence_by_year": presence_by_year,
        "totals_by_year": totals_by_year,
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

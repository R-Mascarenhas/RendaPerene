from core.utils.dividend_events import (
    build_dividend_event_heatmap,
    get_recent_dividend_payments,
)


def test_build_dividend_event_heatmap_returns_summary_and_a_row_per_year():
    events = [
        {"date": "2025-01-15", "value": 0.5},
        {"date": "2025-01-30", "value": 0.4},
        {"date": "2024-01-10", "value": 0.7},
        {"date": "2024-06-10", "value": 0.2},
    ]

    heatmap = build_dividend_event_heatmap(events, current_year=2025, current_month=8)

    assert heatmap["years"] == list(range(2025, 2014, -1))
    assert heatmap["recurrence"][:6] == [2, 0, 0, 0, 0, 1]
    assert heatmap["recurrence_ratio"][0] == 2 / 11
    assert heatmap["presence_by_year"][2025][:6] == [1, 0, 0, 0, 0, 0]
    assert heatmap["totals_by_year"][2025][0] == 0.9


def test_build_dividend_event_heatmap_excludes_future_months_from_recurrence():
    events = [
        {"date": f"{year}-12-15", "value": 0.5}
        for year in range(2015, 2025)
    ]

    heatmap = build_dividend_event_heatmap(
        events,
        current_year=2025,
        current_month=8,
    )

    assert heatmap["recurrence"][11] == 10
    assert heatmap["recurrence_opportunities"][11] == 10
    assert heatmap["recurrence_ratio"][11] == 1.0


def test_get_recent_dividend_payments_sorts_yahoo_payment_dates():
    events = [
        {"date": "2025-05-01", "value": 0.2},
        {"date": "2025-08-01", "value": 0.3},
        {"date": "2024-12-01", "value": 0.1},
    ]

    payments = get_recent_dividend_payments(events, limit=2)

    assert [payment["value"] for payment in payments] == [0.3, 0.2]

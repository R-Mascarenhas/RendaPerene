from core.utils.dividend_events import (
    build_dividend_event_heatmap,
    count_dividend_events_by_month,
    get_recent_dividend_payments,
)


def test_count_dividend_events_by_month_counts_events_from_the_last_ten_years_data():
    events = [
        {"date": "2021-01-15", "value": 0.5},
        {"date": "2023-01-30", "value": 0.4},
        {"date": "2024-06-10", "value": 0.7},
    ]

    month_counts = count_dividend_events_by_month(events)

    assert month_counts == [2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]


def test_build_dividend_event_heatmap_returns_summary_and_a_row_per_year():
    events = [
        {"date": "2025-01-15", "value": 0.5},
        {"date": "2025-01-30", "value": 0.4},
        {"date": "2024-01-10", "value": 0.7},
        {"date": "2024-06-10", "value": 0.2},
    ]

    heatmap = build_dividend_event_heatmap(events, current_year=2025)

    assert heatmap["years"] == list(range(2025, 2014, -1))
    assert heatmap["recurrence"][:6] == [2, 0, 0, 0, 0, 1]
    assert heatmap["events_by_year"][2025][:6] == [2, 0, 0, 0, 0, 0]
    assert heatmap["event_details_by_year"][2025][0] == events[:2]


def test_get_recent_dividend_payments_sorts_yahoo_payment_dates():
    events = [
        {"date": "2025-05-01", "value": 0.2},
        {"date": "2025-08-01", "value": 0.3},
        {"date": "2024-12-01", "value": 0.1},
    ]

    payments = get_recent_dividend_payments(events, limit=2)

    assert [payment["value"] for payment in payments] == [0.3, 0.2]

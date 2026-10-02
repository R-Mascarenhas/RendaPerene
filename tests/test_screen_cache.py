import datetime
import sqlite3

import pandas as pd

from core.screen_cache import ScreenCache


def test_saved_dataframe_survives_reopening_cache(tmp_path):
    path = tmp_path / "cache" / "screen.db"
    first = ScreenCache(path)
    frame = pd.DataFrame({"ticker": ["ABCD3"], "quantity": [12], "price": [10.5]})

    first.put("projection", ("portfolio-a", 1), frame, ttl=3600)

    reopened = ScreenCache(path)
    result = reopened.get("projection", ("portfolio-a", 1))
    pd.testing.assert_frame_equal(result.value, frame)
    assert result.stale is False


def test_price_history_keeps_datetime_index_after_restart(tmp_path):
    path = tmp_path / "screen.db"
    frame = pd.DataFrame(
        {"Close": [10.5, 11.0]},
        index=pd.date_range("2026-01-02", periods=2, tz="America/Sao_Paulo"),
    )
    ScreenCache(path).put("market", ("history", "ABCD3", "1y", "1d"), frame, ttl=3600)

    restored = ScreenCache(path).get("market", ("history", "ABCD3", "1y", "1d"))
    pd.testing.assert_frame_equal(restored.value, frame, check_freq=False)


def test_numeric_quote_round_trips_through_cache_file(tmp_path):
    cache = ScreenCache(tmp_path / "bad-cache.db")
    cache.put("market", ("quote", "ABCD3"), 10.5, ttl=60)
    assert cache.get("market", ("quote", "ABCD3")).value == 10.5


def test_expired_value_remains_available_with_age(tmp_path):
    now = [datetime.datetime(2026, 9, 29, tzinfo=datetime.timezone.utc)]
    cache = ScreenCache(tmp_path / "screen.db", clock=lambda: now[0])
    cache.put("market", ("quote", "ABCD3"), 10.5, ttl=10)
    now[0] += datetime.timedelta(seconds=11)

    result = ScreenCache(tmp_path / "screen.db", clock=lambda: now[0]).get(
        "market", ("quote", "ABCD3")
    )
    assert result.value == 10.5
    assert result.stale is True
    assert result.age_seconds == 11


def test_market_snapshot_preserves_year_keys_and_event_dates(tmp_path):
    cache = ScreenCache(tmp_path / "screen.db")
    value = {
        "dividends_history": {2025: 1.25},
        "dividend_events": [{"date": datetime.date(2025, 5, 20), "value": 0.25}],
    }

    cache.put("market", ("snapshot", "ABCD3", 2025), value, ttl=600)

    assert cache.get("market", ("snapshot", "ABCD3", 2025)).value == value


def test_incompatible_file_is_ignored_without_modifying_it(tmp_path):
    path = tmp_path / "screen.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    cache = ScreenCache(path)

    assert cache.get("market", ("quote", "ABCD3")) is None
    assert not cache.put("market", ("quote", "ABCD3"), 10.0, ttl=60)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 99


def test_unavailable_directory_falls_back_without_exception(tmp_path):
    occupied = tmp_path / "occupied"
    occupied.write_text("not a directory", encoding="ascii")
    cache = ScreenCache(occupied / "screens.db")

    assert cache.get("market", ("quote", "ABCD3")) is None
    assert not cache.put("market", ("quote", "ABCD3"), 10.0, ttl=60)


def test_corrupt_file_is_ignored_without_deleting_it(tmp_path):
    path = tmp_path / "screens.db"
    path.write_bytes(b"not a SQLite database")
    cache = ScreenCache(path)

    assert cache.get("market", ("quote", "ABCD3")) is None
    assert not cache.put("market", ("quote", "ABCD3"), 10.0, ttl=60)
    assert path.read_bytes() == b"not a SQLite database"

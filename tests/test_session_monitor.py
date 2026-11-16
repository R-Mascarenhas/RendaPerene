from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import core.utils.session as session_module


class _ScenarioFinished(Exception):
    pass


def run_monitor_scenario(monkeypatch, samples):
    """Drive the real monitor with independent elapsed and wall clocks."""
    clock = SimpleNamespace(monotonic=0.0, wall=1_700_000_000.0, count=0, sessions=0)
    remaining = iter(samples)
    starting = True

    def sleep(seconds):
        nonlocal starting
        if starting:
            starting = False
            clock.monotonic += seconds
            clock.wall += seconds
            return
        try:
            elapsed, wall_elapsed, clock.sessions = next(remaining)
        except StopIteration:
            raise _ScenarioFinished from None
        clock.monotonic += elapsed
        clock.wall += wall_elapsed
        clock.count += 1

    runtime = SimpleNamespace(
        _session_mgr=SimpleNamespace(list_active_sessions=lambda: [object()] * clock.sessions),
        stop=Mock(),
    )
    fake_time = SimpleNamespace(
        sleep=sleep,
        monotonic=lambda: clock.monotonic,
        time=lambda: clock.wall,
    )
    monkeypatch.setattr(session_module, "time", fake_time)
    monkeypatch.setattr("streamlit.runtime.get_instance", lambda: runtime)
    try:
        session_module.monitor_active_sessions()
    except _ScenarioFinished:
        pass
    return runtime, clock


def test_last_tab_closure_still_stops_after_two_normal_checks(monkeypatch):
    runtime, clock = run_monitor_scenario(monkeypatch, [(5, 5, 1), (5, 5, 0), (5, 5, 0)])
    runtime.stop.assert_called_once()
    assert clock.count == 3


@pytest.mark.parametrize("pause", [(600, 600, 0), (5, 600, 0)])
def test_resume_allows_reconnection_without_stopping(monkeypatch, pause):
    runtime, clock = run_monitor_scenario(monkeypatch, [(5, 5, 1), pause, (5, 5, 0), (5, 5, 1)])
    runtime.stop.assert_not_called()
    assert clock.count == 4


def test_resume_restarts_a_preexisting_shutdown_countdown(monkeypatch):
    runtime, clock = run_monitor_scenario(
        monkeypatch, [(5, 5, 1), (5, 5, 0), (600, 600, 0), (5, 5, 0), (5, 5, 1)]
    )
    runtime.stop.assert_not_called()
    assert clock.count == 5


def test_stale_active_connection_after_resume_does_not_cancel_grace(monkeypatch):
    runtime, clock = run_monitor_scenario(
        monkeypatch, [(5, 5, 1), (600, 600, 1), (5, 5, 0), (5, 5, 0), (5, 5, 1)]
    )
    runtime.stop.assert_not_called()
    assert clock.count == 5


def test_reconnected_tab_closure_uses_normal_shutdown_delay(monkeypatch):
    runtime, clock = run_monitor_scenario(
        monkeypatch,
        [(5, 5, 1), (600, 600, 0), (5, 5, 0), (5, 5, 1), (5, 5, 0), (5, 5, 0)],
    )
    runtime.stop.assert_called_once()
    assert clock.count == 6


def test_resume_without_reconnection_exits_after_120_seconds(monkeypatch):
    runtime, clock = run_monitor_scenario(
        monkeypatch, [(5, 5, 1), (600, 600, 0)] + [(5, 5, 0)] * 24
    )
    runtime.stop.assert_called_once()
    assert clock.count == 26


def test_resume_grace_survives_another_suspension(monkeypatch):
    runtime, clock = run_monitor_scenario(
        monkeypatch,
        [(5, 5, 1), (600, 600, 0)] + [(5, 5, 0)] * 20 + [(600, 600, 0), (5, 5, 0), (5, 5, 1)],
    )
    runtime.stop.assert_not_called()
    assert clock.count == 25

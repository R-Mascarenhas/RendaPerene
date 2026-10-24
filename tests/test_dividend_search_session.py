import datetime
from concurrent.futures import Future

import pytest

from services.dividend_search_session import DividendSearchSession


class ControlledExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, callback):
        future = Future()
        future.set_running_or_notify_cancel()
        self.jobs.append((future, callback))
        return future

    def complete(self, index=0):
        future, callback = self.jobs[index]
        future.set_result(callback())


class SearchSource:
    revision = 0

    def __init__(self):
        self.prepared = []

    def get_local_projection_revision(self):
        return self.revision

    def prepare_dividend_search(self, ticker=None):
        self.prepared.append(ticker)
        revision = self.revision
        return lambda: {
            "suggestions": [ticker], "revision": revision,
            "unavailable": [], "changed": [],
        }


def test_pending_search_is_reused_and_collected_through_poll():
    source = SearchSource()
    executor = ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "generation-1"))
    assert session.poll("CMIG4").searching
    assert session.poll("CMIG4").result is None
    assert len(executor.jobs) == 1
    executor.complete()
    state = session.poll("CMIG4")
    assert not state.searching
    assert not state.failed
    assert state.result["suggestions"] == ["CMIG4"]
    assert session.poll("CMIG4").result == state.result
    assert source.prepared == ["CMIG4"]


def test_failure_is_remembered_and_manual_retry_can_succeed():
    source, executor = SearchSource(), ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "generation-1"))
    session.poll()
    executor.jobs[0][0].set_exception(TimeoutError("private provider details"))
    state = session.poll()
    assert state.failed and state.result is None and not state.searching
    assert session.poll().failed
    assert len(executor.jobs) == 1
    assert session.poll(retry=True).searching
    executor.complete(1)
    assert not session.poll().failed
    assert session.poll().result is not None


@pytest.mark.parametrize("change", ["portfolio", "generation", "day", "revision", "ticker"])
@pytest.mark.parametrize("pending", [False, True])
def test_context_change_discards_review_and_running_result(change, pending):
    source, executor = SearchSource(), ControlledExecutor()
    context = ["a", "generation-1"]
    day = [datetime.date(2026, 10, 24)]
    session = DividendSearchSession(source, executor, lambda: tuple(context), lambda: day[0])
    first = session.poll("CMIG4")
    executor.complete()
    session.poll("CMIG4")
    session.draft = {"event": "reviewed"}
    assert session.draft == {"event": "reviewed"}
    if pending:
        session.poll("CMIG4", retry=True)
    if change == "portfolio":
        context[0] = "b"
    elif change == "generation":
        context[1] = "generation-2"
    elif change == "day":
        day[0] = datetime.date(2026, 10, 25)
    elif change == "revision":
        source.revision = 1
    ticker = "BBAS3" if change == "ticker" else "CMIG4"
    state = session.poll(ticker)
    assert state.key != first.key
    assert state.result is None and session.draft is None
    if pending:
        executor.complete(1)  # Cancellation cannot stop an already running worker.
        assert session.poll(ticker).result is None
    executor.complete(2 if pending else 1)
    assert session.poll(ticker).result["suggestions"] == [ticker]


def test_retry_invalidates_current_result_and_draft_until_replacement_completes():
    source, executor = SearchSource(), ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "g"))
    session.poll()
    executor.complete()
    session.poll()
    session.draft = {"payments": [1]}
    pending = session.poll(retry=True)
    assert pending.result is None and session.draft is None
    assert pending.searching
    executor.jobs[1][0].set_exception(RuntimeError("offline"))
    assert session.poll().failed
    assert session.draft is None and session.poll().result is None


@pytest.mark.parametrize("failure", ["prepare", "submit"])
def test_start_failure_is_visible_and_remembered(failure):
    source, executor = SearchSource(), ControlledExecutor()
    attempts = []
    def fail(*args):
        attempts.append(True)
        raise RuntimeError("cannot start")
    if failure == "prepare":
        source.prepare_dividend_search = fail
    else:
        executor.submit = fail
    session = DividendSearchSession(source, executor, lambda: ("a", "g"))
    assert session.poll().failed
    assert session.poll().failed
    assert attempts == [True]
    assert not executor.jobs


def test_snapshot_from_another_revision_is_never_exposed():
    source, executor = SearchSource(), ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "g"))
    session.poll()
    executor.jobs[0][0].set_result({"revision": 999, "suggestions": ["obsolete"]})
    state = session.poll()
    assert state.result is None and not state.searching
    assert session.draft is None
    session.poll()
    assert len(executor.jobs) == 1


def test_invalidation_discards_draft_and_attempt_and_restarts_on_next_poll():
    source, executor = SearchSource(), ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "g"))
    session.poll()
    executor.complete()
    session.poll()
    session.draft = {"payments": [1]}
    session.invalidate()
    assert session.draft is None
    assert session.poll().searching
    assert len(executor.jobs) == 2


def test_draft_is_invalidated_when_revision_changes_between_polls():
    source, executor = SearchSource(), ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "g"))
    session.poll()
    executor.complete()
    session.poll()
    session.draft = {"payments": [1]}
    source.revision = 1
    assert session.draft is None


def test_pending_work_is_cancelled_when_a_new_attempt_replaces_it():
    future = Future()
    class QueuedExecutor:
        def submit(self, callback):
            return future
    session = DividendSearchSession(SearchSource(), QueuedExecutor(), lambda: ("a", "g"))
    session.poll()
    session.invalidate()
    assert future.cancelled()


def test_context_changed_during_snapshot_preparation_discards_the_attempt():
    source, executor = SearchSource(), ControlledExecutor()
    context = ["a", "g"]
    prepare = source.prepare_dividend_search
    def prepare_and_switch(ticker):
        snapshot = prepare(ticker)
        context[0] = "b"
        return snapshot
    source.prepare_dividend_search = prepare_and_switch
    session = DividendSearchSession(source, executor, lambda: tuple(context))
    assert session.poll().result is None
    executor.complete()
    assert session.poll().result is None
    executor.complete(1)
    assert session.poll().result is not None


def test_advance_review_updates_revision_without_submitting_another_search():
    source, executor = SearchSource(), ControlledExecutor()
    session = DividendSearchSession(source, executor, lambda: ("a", "g"))
    session.poll()
    executor.complete()
    previous = session.poll()
    session.draft = {"payments": [1]}
    source.revision += 1
    source.refresh_dividend_review = lambda result: {**result, "suggestions": [], "revision": 1}
    session.advance_review()
    current = session.poll()
    assert current.result["suggestions"] == []
    assert current.result["revision"] == 1
    assert current.key != previous.key
    assert session.draft is None
    assert len(executor.jobs) == 1


def test_advance_review_does_not_carry_events_to_another_portfolio():
    source, executor = SearchSource(), ControlledExecutor()
    context = ["a", "g"]
    session = DividendSearchSession(source, executor, lambda: tuple(context))
    session.poll()
    executor.complete()
    session.poll()
    context[0] = "b"
    session.advance_review()
    assert session.poll().result is None
    assert session.draft is None
    assert len(executor.jobs) == 2

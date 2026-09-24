from core.constants import SESSION_UPDATE_CHECK_FUTURE
from views import update_notification


class FakeFuture:
    def __init__(self):
        self.completed = False

    def done(self):
        return self.completed

    def result(self):
        return None


def test_update_notification_reruns_after_background_check_completes(monkeypatch):
    future = FakeFuture()
    monkeypatch.setattr(
        update_notification.st, "session_state", {SESSION_UPDATE_CHECK_FUTURE: future}
    )
    scheduled_fragments = []

    def fragment(run_every):
        assert run_every == 1

        def decorate(func):
            scheduled_fragments.append(func)
            return func

        return decorate

    reruns = []
    monkeypatch.setattr(update_notification.st, "fragment", fragment)
    monkeypatch.setattr(update_notification.st, "rerun", lambda: reruns.append(True))

    update_notification.render_update_notification("1.0.0", object())

    assert len(scheduled_fragments) == 1
    future.completed = True
    scheduled_fragments[0]()

    assert reruns == [True]

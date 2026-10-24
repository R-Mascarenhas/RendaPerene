"""Session-owned dividend search transitions, independent of presentation frameworks."""

import datetime
import logging
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass

from core.ports import DividendSearchSourcePort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DividendSearchState:
    key: str
    result: dict | None
    searching: bool
    failed: bool


class DividendSearchSession:
    def __init__(
        self,
        source: DividendSearchSourcePort,
        executor: Executor,
        context: Callable[[], tuple],
        today: Callable[[], datetime.date] = datetime.date.today,
    ):
        self._source = source
        self._executor = executor
        self._context = context
        self._today = today
        self._identity = None
        self._future = None
        self._result = None
        self._draft = None
        self._failed = False
        self._serial = 0

    def poll(self, ticker=None, *, retry=False) -> DividendSearchState:
        """Advance search and return display state without exposing Future ordering."""
        identity = self._read_identity(ticker)
        if identity != self._identity or retry:
            self.invalidate()
            self._identity = identity
            self._serial += 1
            try:
                # Capture SQLite inputs here; the submitted callback owns only its snapshot.
                search = self._source.prepare_dividend_search(ticker)
                self._future = self._executor.submit(search)
            except Exception:
                self._record_failure()
        if self._future is not None and self._future.done():
            future = self._future
            self._future = None
            try:
                result = future.result()
                if result["revision"] == identity[-1]:
                    self._result = result
            except Exception:
                self._record_failure()
        self._discard_if_obsolete()
        return DividendSearchState(
            f"dividend_search_{self._serial}_",
            self._result,
            self._future is not None,
            self._failed,
        )

    def _read_identity(self, ticker):
        revision = self._source.get_local_projection_revision()
        return (self._context(), self._today(), ticker, revision)

    def _record_failure(self):
        logger.warning("dividends.review_read_failed")
        self._failed = True

    def _discard_if_obsolete(self):
        if self._identity is not None and self._read_identity(self._identity[2]) != self._identity:
            self.invalidate()

    @property
    def draft(self):
        """Return only a draft belonging to the current portfolio context and revision."""
        self._discard_if_obsolete()
        return self._draft

    @draft.setter
    def draft(self, value):
        self._discard_if_obsolete()
        self._draft = value if self._result is not None else None

    def invalidate(self):
        """Forget attempts and review state after a write, portfolio change or disposal."""
        if self._future is not None:
            self._future.cancel()
        self._future = None
        self._identity = None
        self._result = None
        self._draft = None
        self._failed = False

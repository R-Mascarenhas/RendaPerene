"""Bounded, nonblocking market cache independent of Streamlit."""

import copy
import logging
import queue
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.ports import ScreenCachePort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketDataStatus:
    available: bool = False
    updating: bool = False
    stale: bool = False
    failed: bool = False
    age_seconds: float | None = None
    revision: int = 0


@dataclass
class _Entry:
    value: Any = None
    available: bool = False
    updated_at: float | None = None
    expires_at: float = 0.0
    retry_at: float = 0.0
    updating: bool = False
    failed: bool = False
    generation: int = 0
    revision: int = 0
    loader: Callable[[], Any] | None = None
    ttl: float = 0.0
    valid: Callable[[Any], bool] | None = None


class MarketDataCache:
    """Read snapshots immediately and refresh at most once per key in the background.

    Loaders must use remote inputs only, without UI or portfolio state. Readers own
    their returned copies. Invalid or failed refreshes retain the last valid value.
    """

    def __init__(  # noqa: PLR0913 - independent cache bounds and injected clock/store
        self,
        *,
        workers: int = 2,
        max_entries: int = 512,
        max_pending: int = 128,
        retry_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
        store: ScreenCachePort | None = None,
    ):
        if workers < 1 or max_entries < 1 or max_pending < 1:
            raise ValueError("Cache limits must be positive.")
        self._entries = OrderedDict()
        self._condition = threading.Condition()
        self._queue = queue.Queue(maxsize=max_pending)
        self._max_entries = max_entries
        self._retry_seconds = retry_seconds
        self._clock = clock
        self._store = store
        self._closed = threading.Event()
        self._jobs = 0
        self._revision = 0
        self._workers = [
            threading.Thread(target=self._work, name="market-refresh", daemon=True)
            for _ in range(workers)
        ]
        for worker in self._workers:
            worker.start()

    def read(
        self,
        key: tuple,
        loader: Callable[[], Any],
        *,
        ttl: float,
        default: Any,
        valid: Callable[[Any], bool] = lambda value: value is not None,
    ) -> Any:
        """Return a copy without waiting for remote I/O, even on misses and expiration."""
        with self._condition:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry()
                if self._store is not None:
                    saved = self._store.get("market", key)
                    if saved is not None:
                        try:
                            accepted = valid(saved.value)
                        except (TypeError, ValueError, KeyError):
                            accepted = False
                        if accepted:
                            now = self._clock()
                            entry.value = saved.value
                            entry.available = True
                            entry.updated_at = now - saved.age_seconds
                            entry.expires_at = (
                                now + saved.remaining_seconds if not saved.stale else now
                            )
                            self._revision += 1
                            entry.revision = self._revision
                self._entries[key] = entry
            self._entries.move_to_end(key)
            entry.loader = loader
            entry.ttl = ttl
            entry.valid = valid
            now = self._clock()
            if (
                not self._closed.is_set()
                and not entry.updating
                and now >= entry.retry_at
                and (not entry.available or now >= entry.expires_at)
            ):
                try:
                    self._queue.put_nowait((key, entry, entry.generation, loader, ttl, valid))
                except queue.Full:
                    # Retry on a later render; the reader never waits for queue capacity.
                    pass
                else:
                    entry.updating = True
                    self._jobs += 1
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            value = entry.value if entry.available else default
        return copy.deepcopy(value)

    def retry_due(self, keys: set[tuple] | None = None) -> int:
        """Reschedule failed reads whose backoff expired without waiting for a UI rerun."""
        scheduled = 0
        now = self._clock()
        with self._condition:
            for key, entry in self._entries.items():
                if keys is not None and key not in keys:
                    continue
                if (
                    not entry.failed
                    or entry.updating
                    or now < entry.retry_at
                    or entry.loader is None
                    or entry.valid is None
                ):
                    continue
                try:
                    self._queue.put_nowait(
                        (key, entry, entry.generation, entry.loader, entry.ttl, entry.valid)
                    )
                except queue.Full:
                    continue
                entry.updating = True
                entry.failed = False
                self._jobs += 1
                scheduled += 1
        return scheduled

    def status(self, key: tuple) -> MarketDataStatus:
        """Inspect availability without scheduling another request."""
        with self._condition:
            entry = self._entries.get(key)
            if entry is None:
                return MarketDataStatus()
            now = self._clock()
            return MarketDataStatus(
                available=entry.available,
                updating=entry.updating,
                stale=entry.available and now >= entry.expires_at,
                failed=entry.failed,
                age_seconds=(now - entry.updated_at) if entry.updated_at is not None else None,
                revision=entry.revision,
            )

    def refresh(self, prefix: tuple = ()) -> None:
        """Mark matching entries stale, preserving values and discarding old replies."""
        expired_keys = []
        with self._condition:
            for key, entry in self._entries.items():
                if key[: len(prefix)] == prefix:
                    entry.generation += 1
                    entry.expires_at = float("-inf")
                    entry.retry_at = float("-inf")
                    entry.updating = False
                    expired_keys.append(key)
        if self._store is not None and expired_keys:
            self._store.expire_many("market", expired_keys)

    def wait_idle(self, timeout: float = 5) -> bool:
        """Wait for scheduled work in diagnostics/tests; never used by UI reads."""
        with self._condition:
            return self._condition.wait_for(lambda: self._jobs == 0, timeout=timeout)

    def close(self) -> None:
        """Stop accepting requests; daemon workers finish their current remote call."""
        self._closed.set()

    def _work(self):
        while not self._closed.is_set():
            try:
                key, entry, generation, loader, ttl, valid = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                with self._condition:
                    current = self._entries.get(key) is entry and entry.generation == generation
                if not current:
                    continue
                try:
                    value = loader()
                    accepted = valid(value)
                    stored = copy.deepcopy(value) if accepted else None
                except Exception as error:
                    accepted = False
                    logger.warning(
                        "market_cache.refresh_failed error_type=%s", type(error).__name__
                    )
                with self._condition:
                    persisted = False
                    if self._entries.get(key) is entry and entry.generation == generation:
                        now = self._clock()
                        if accepted:
                            entry.value = stored
                            entry.available = True
                            entry.updated_at = now
                            entry.expires_at = now + ttl
                            persisted = True
                        entry.failed = not accepted
                        self._revision += 1
                        entry.revision = self._revision
                        entry.retry_at = now + self._retry_seconds if not accepted else 0.0
                        entry.updating = False
                if persisted and self._store is not None:
                    self._store.put("market", key, stored, ttl=ttl)
            finally:
                with self._condition:
                    self._jobs -= 1
                    self._condition.notify_all()
                self._queue.task_done()

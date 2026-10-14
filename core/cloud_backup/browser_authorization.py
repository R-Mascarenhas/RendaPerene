"""Session-scoped delivery of public OAuth URLs to the application browser."""

import logging
import threading
from collections import OrderedDict
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


class BrowserAuthorization:
    def __init__(self):
        self._lock = threading.Lock()
        self._owner = None
        self._url = ""
        self._cancelled = threading.Event()
        self._completion_revision = 0
        self._completed = OrderedDict()

    def begin(self, owner: str) -> None:
        if not isinstance(owner, str) or not owner:
            raise ValueError("Authorization needs an initiating browser session.")
        with self._lock:
            self._owner = owner
            self._url = ""
            self._cancelled.clear()
            logger.info("google_oauth.browser.started")

    def open(self, url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "accounts.google.com":
            return False
        with self._lock:
            if self._owner is None or self._cancelled.is_set():
                return False
            self._url = url
            logger.info("google_oauth.browser.url_ready")
            return True

    def pending_url(self, owner: str) -> str:
        with self._lock:
            return self._url if self._owner == owner else ""

    def active(self, owner: str) -> bool:
        with self._lock:
            return self._owner == owner

    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def completed_revision(self, owner: str) -> int:
        with self._lock:
            return self._completed.get(owner, 0)

    def cancel(self, owner: str) -> None:
        with self._lock:
            if self._owner == owner:
                self._cancelled.set()
                self._url = ""
                logger.info("google_oauth.browser.cancel_requested")

    def finish(self) -> None:
        with self._lock:
            if self._owner is not None:
                self._completion_revision += 1
                self._completed[self._owner] = self._completion_revision
                self._completed.move_to_end(self._owner)
                if len(self._completed) > 32:
                    self._completed.popitem(last=False)
                logger.info("google_oauth.browser.finished")
            self._cancelled.set()
            self._url = ""
            self._owner = None

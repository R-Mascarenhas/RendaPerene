"""Session-owned observation; remote workers never receive session state."""

import math
from dataclasses import dataclass

from core.background_market_data import MINIMUM_WAGE_KEY, BackgroundMarketData
from core.market_data_cache import MarketDataStatus


@dataclass(frozen=True)
class MarketDataPoll:
    statuses: tuple[MarketDataStatus, ...]
    changed: bool


@dataclass(frozen=True)
class MinimumWageRefresh:
    value: float | None = None
    failed: bool = False


class MarketDataObserver:
    """Keep revisions read by a screen distinct from replies completed afterwards."""

    def __init__(self, background: BackgroundMarketData):
        self._background = background
        self.market_data = background.observed(self._remember)
        self._requests: dict[tuple, int] = {}
        self._poll_ready = False
        self._minimum_wage_refresh: tuple[tuple[str, str | None], int] | None = None

    def _remember(self, key: tuple) -> None:
        if key not in self._requests:
            self._requests[key] = self._background.status(key).revision

    def begin_run(self) -> None:
        """Start tracking only the requests relevant to the next full screen render."""
        self._requests.clear()
        self._poll_ready = False
        if self.minimum_wage_pending:
            self.market_data.get_current_minimum_wage()

    def poll(self) -> MarketDataPoll:
        """Retry observed failures and retain first-poll changes for the next tick."""
        self._background.cache.retry_due(set(self._requests))
        statuses = [(key, self._background.status(key)) for key in self._requests]
        changed = any(status.revision != self._requests[key] for key, status in statuses)
        rerun = self._poll_ready and changed
        self._poll_ready = True
        if rerun:
            for key, status in statuses:
                self._requests[key] = status.revision
        return MarketDataPoll(tuple(status for _, status in statuses), rerun)

    def reset(self) -> None:
        self.cancel_minimum_wage_refresh()
        self.begin_run()

    @property
    def minimum_wage_pending(self) -> bool:
        return self._minimum_wage_refresh is not None

    def cancel_minimum_wage_refresh(self) -> None:
        self._minimum_wage_refresh = None

    def request_minimum_wage_refresh(self, portfolio: tuple[str, str | None]) -> None:
        """Invalidate only the indicator and associate its next reply with the requester."""
        revision = self._background.status(MINIMUM_WAGE_KEY).revision
        self._minimum_wage_refresh = (portfolio, revision)
        self._background.cache.refresh(MINIMUM_WAGE_KEY)
        self.market_data.get_current_minimum_wage()

    def take_minimum_wage_refresh(
        self, portfolio: tuple[str, str | None]
    ) -> MinimumWageRefresh | None:
        """Consume a completed reply once; persistence belongs to the UI caller."""
        pending = self._minimum_wage_refresh
        if pending is None:
            return None
        requester, revision = pending
        if requester != portfolio:
            self.cancel_minimum_wage_refresh()
            return None
        status = self._background.status(MINIMUM_WAGE_KEY)
        if status.revision == revision or status.updating:
            self.market_data.get_current_minimum_wage()
            return None
        self.cancel_minimum_wage_refresh()
        if status.failed or not status.available:
            return MinimumWageRefresh(failed=True)
        value = self.market_data.get_current_minimum_wage()
        if not math.isfinite(value) or not 1000 <= value <= 5000:
            return MinimumWageRefresh(failed=True)
        return MinimumWageRefresh(value=value)

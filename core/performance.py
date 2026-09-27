"""Opt-in, sanitized navigation timing for development measurements."""

import logging
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps

logger = logging.getLogger(__name__)
_SCREEN_IDENTIFIER = re.compile(
    r"^(?:dashboard|ativos|planejamento|restauracao|atualizacao)(?:\.[a-z][a-z0-9_]*)*$"
)
_PHASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def navigation_metrics_enabled() -> bool:
    """Return whether sanitized timing output is explicitly enabled in development."""
    return (
        os.environ.get("APP_ENV", "prod").strip().casefold() == "dev"
        and os.environ.get("RENDA_PERENE_NAVIGATION_METRICS", "false").strip().casefold() == "true"
    )


def _validate_metric_identifiers(screen: str, phase: str) -> None:
    """Reject UI text and dynamic values before they can reach the log."""
    if not _SCREEN_IDENTIFIER.fullmatch(screen) or not _PHASE_IDENTIFIER.fullmatch(phase):
        raise ValueError("Metric identifiers must be approved technical names.")


@contextmanager
def measure_navigation(screen: str, phase: str) -> Iterator[None]:
    """Log one safe duration without identifying a portfolio or its financial data."""
    _validate_metric_identifiers(screen, phase)
    if not navigation_metrics_enabled():
        yield
        return

    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.debug(
            "%s.%s duration: %s ms",
            screen,
            phase,
            elapsed_ms,
        )


def instrument_screen(screen: str):
    """Decorate a view renderer with a sanitized total-duration metric."""

    def decorate(renderer):
        @wraps(renderer)
        def measured(*args, **kwargs):
            with measure_navigation(screen, "total"):
                return renderer(*args, **kwargs)

        return measured

    return decorate

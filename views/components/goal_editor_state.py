import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st

from core.constants import (
    WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX,
    WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX,
    WIDGET_ASSET_ANNUAL_GOAL_PREFIX,
)


class GoalEditorState:
    """Coordinate recoverable edit errors and control reconstruction for both editors."""

    def __init__(self, context: str) -> None:
        self._error_key = f"{context}_error"
        self._revision_key = f"{context}_revision"

    @property
    def error(self) -> str | None:
        return st.session_state.get(self._error_key)

    @property
    def revision(self) -> int:
        return st.session_state.get(self._revision_key, 0)

    @contextmanager
    def editing(self) -> Iterator[None]:
        """Finish a save attempt, preserving validation details and hiding storage errors."""
        try:
            yield
        except ValueError as error:
            st.session_state[self._error_key] = str(error)
        except (RuntimeError, sqlite3.Error):
            st.session_state[self._error_key] = "Não foi possível salvar a meta. Tente novamente."
        else:
            st.session_state.pop(self._error_key, None)
        st.session_state[self._revision_key] = self.revision + 1


def _invalidate_prefixes(prefixes: tuple[str, ...]) -> None:
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith(prefixes):
            del st.session_state[key]


def invalidate_goal_plan_state() -> None:
    """Discard table snapshots and controls after an external target change."""
    _invalidate_prefixes(
        (WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX, WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX)
    )


def invalidate_asset_goal_state() -> None:
    """Discard detail controls and errors after an external target change."""
    _invalidate_prefixes((WIDGET_ASSET_ANNUAL_GOAL_PREFIX,))


def invalidate_goal_editor_state() -> None:
    """Discard both editors' derived state after a portfolio mutation."""
    invalidate_goal_plan_state()
    invalidate_asset_goal_state()

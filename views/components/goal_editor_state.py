import streamlit as st

from core.constants import (
    WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX,
    WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX,
)


def invalidate_goal_editor_state() -> None:
    """Discard goal editor snapshots after a portfolio or target change."""
    for key in list(st.session_state):
        if key.startswith(
            (WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX, WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX)
        ):
            del st.session_state[key]

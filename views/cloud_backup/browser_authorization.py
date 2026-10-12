"""Browser-side popup launch without moving OAuth secrets into the frontend."""

import logging
import threading
import weakref
from pathlib import Path

import streamlit as st
from streamlit.runtime import get_instance

from core.ports import BrowserAuthorizationPort

logger = logging.getLogger(__name__)
_POPUP_EVENTS = {"opened", "blocked", "navigated", "navigation_failed", "unavailable", "finished"}

_renderers = weakref.WeakKeyDictionary()
_renderer_lock = threading.Lock()


def _popup_renderer():
    # Registration belongs to the active Streamlit runtime, not to module import.
    runtime = get_instance()
    with _renderer_lock:
        if runtime not in _renderers:
            _renderers[runtime] = st.components.v2.component(
                "google_authorization_popup",
                js=Path(__file__).with_name("oauth_popup.js").read_text(encoding="utf-8"),
            )
        return _renderers[runtime]


def render_authorization_browser(
    browser: BrowserAuthorizationPort, owner: str, *, enabled: bool
) -> None:
    url = browser.pending_url(owner)
    result = _popup_renderer()(
        key="google_authorization_popup",
        data={
            "session": owner,
            "enabled": enabled,
            "active": browser.active(owner),
            "url": url,
            "completed": browser.completed_revision(owner),
        },
        on_popup_event_change=lambda: None,
    )
    _log_popup_event(result.get("popup_event"), owner)
    if url:
        st.caption("Se a janela de login não abriu, continue pelo link abaixo neste navegador.")
        st.link_button("Abrir login em nova aba", url, width="stretch")
        if st.button("Cancelar conexão com o Google", width="stretch"):
            browser.cancel(owner)


def _log_popup_event(event, owner: str) -> None:
    if not isinstance(event, dict):
        return
    name = event.get("event")
    sequence = event.get("sequence")
    if not isinstance(name, str) or name not in _POPUP_EVENTS or type(sequence) is not int:
        return
    key = f"google_popup_event_{owner}"
    if sequence <= st.session_state.get(key, 0):
        return
    st.session_state[key] = sequence
    logger.info("google_oauth.popup.%s", name)

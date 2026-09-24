"""Streamlit presentation for the optional application-update notification."""

import logging
import webbrowser
from concurrent.futures import ThreadPoolExecutor

import streamlit as st

from core.constants import (
    SESSION_UPDATE_CHECK_AVAILABLE,
    SESSION_UPDATE_CHECK_DISMISSED,
    SESSION_UPDATE_CHECK_EXECUTOR,
    SESSION_UPDATE_CHECK_FUTURE,
)
from core.ports import UpdateCheckerPort
from core.update_checker import AvailableUpdate

logger = logging.getLogger(__name__)


def render_update_notification(installed_version: str, update_checker: UpdateCheckerPort) -> None:
    """Start one background check per session and show its completed result."""
    if SESSION_UPDATE_CHECK_FUTURE not in st.session_state:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="update-check")
        st.session_state[SESSION_UPDATE_CHECK_EXECUTOR] = executor
        st.session_state[SESSION_UPDATE_CHECK_FUTURE] = executor.submit(
            update_checker.check, installed_version
        )

    future = st.session_state[SESSION_UPDATE_CHECK_FUTURE]
    if not future.done():

        @st.fragment(run_every=1)
        def await_update_check() -> None:
            if future.done():
                st.rerun()

        await_update_check()
        return

    if SESSION_UPDATE_CHECK_AVAILABLE not in st.session_state:
        try:
            st.session_state[SESSION_UPDATE_CHECK_AVAILABLE] = future.result()
        except Exception as error:  # Defensive boundary around the background worker.
            logger.warning("update_check.worker_failed error_type=%s", type(error).__name__)
            st.session_state[SESSION_UPDATE_CHECK_AVAILABLE] = None

    update = st.session_state.get(SESSION_UPDATE_CHECK_AVAILABLE)
    if isinstance(update, AvailableUpdate) and not st.session_state.get(
        SESSION_UPDATE_CHECK_DISMISSED
    ):
        _render_update_dialog(update)


@st.dialog("Atualização disponível")
def _render_update_dialog(update: AvailableUpdate) -> None:
    st.write(f"A versão {update.version} do Renda Perene está disponível.")
    if update.release_notes:
        st.text(update.release_notes)
    if st.button("Baixar atualização", use_container_width=True):
        if webbrowser.open(update.download_url):
            st.session_state[SESSION_UPDATE_CHECK_DISMISSED] = True
            st.rerun()
        else:
            logger.warning("update_check.browser_open_failed")
            st.error("Não foi possível abrir o navegador. Tente novamente.")
    if st.button("Agora não", use_container_width=True):
        st.session_state[SESSION_UPDATE_CHECK_DISMISSED] = True
        st.rerun()

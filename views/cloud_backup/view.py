"""Presentation of optional Drive backup and explicitly confirmed recovery."""

import uuid

import streamlit as st

from core.cloud_backup.models import CloudBackupError
from core.constants import (
    SESSION_PORTFOLIO_RESTORE_CLEANUP_WARNING,
    SESSION_PORTFOLIO_RESTORE_SUCCESS,
)
from core.utils import SessionManager
from services.cloud_backup.runtime import CloudBackupRuntime
from services.local_restore_service import BackupRestoreError
from views.backup_restore_view import _format_local_datetime
from views.cloud_backup.browser_authorization import render_authorization_browser


def render_cloud_backup(
    runtime: CloudBackupRuntime | None, labels: dict, *, configuration_error=""
):
    with st.sidebar.expander("☁️ Backup no Google Drive"):
        if runtime is None:
            st.write("Conecte sua conta Google para configurar o backup automático.")
            st.button(
                "Conectar ao Google",
                disabled=True,
                width="stretch",
                help="A conexão será habilitada quando a integração Google desta aplicação estiver disponível.",
            )
            if configuration_error:
                st.error(configuration_error)
                st.info(
                    "Não foi possível inicializar o backup no Google Drive. "
                    "Você pode continuar usando as carteiras e os backups locais."
                )
            else:
                st.info(
                    "A conexão com o Google ainda não está disponível nesta versão da aplicação. "
                    "O responsável pelo RendaPerene precisa habilitar a integração. "
                    "Você pode continuar usando as carteiras e os backups locais."
                )
            st.caption("Após conectar, você poderá escolher as carteiras com backup automático.")
            return
        if st.session_state.get("cloud_runtime_session") != id(runtime):
            st.session_state["cloud_runtime_session"] = id(runtime)
            try:
                if not runtime.busy and runtime.service.status().connected:
                    runtime.submit("discover")
            except CloudBackupError:
                pass  # Controls report the state error without interrupting local views.
        _render_controls(runtime, labels)


@st.fragment(run_every="2s")
def _render_controls(runtime, labels):
    runtime.poll()
    revision_key = f"cloud_processed_revision_{id(runtime)}"
    account_changed = st.session_state.get(revision_key) != runtime.revision
    if account_changed:
        st.session_state[revision_key] = runtime.revision
    _consume_result(runtime, account_changed=account_changed)
    runtime.schedule_due()
    try:
        status = runtime.service.status()
    except CloudBackupError as error:
        st.error(str(error))
        return
    if runtime.busy:
        st.info("Operação em andamento. Você pode continuar usando as outras telas.")
    if runtime.error and runtime.completed_operation not in {"inspect", "restore"}:
        st.error(runtime.error)
    if st.session_state.get("cloud_interactive_error"):
        st.error(st.session_state["cloud_interactive_error"])
    if status.error:
        st.error(status.error)
    if status.message:
        st.caption(status.message)
    st.warning(
        "O backup usa a proteção padrão do Google Drive, sem senha adicional. "
        "O Google e quem tiver acesso ao arquivo poderão ler os dados da carteira."
    )
    if not status.connected:
        if status.credential_removal_pending:
            st.warning(
                "A remoção das credenciais locais está pendente. Desbloqueie o cofre e tente novamente."
            )
            if st.button(
                "Tentar remover credenciais locais", disabled=runtime.busy, width="stretch"
            ):
                runtime.submit("disconnect")
            return
        st.write("Conecte sua conta Google para configurar o backup automático.")
        if st.button("Conectar ao Google", disabled=runtime.busy, width="stretch"):
            runtime.submit("connect", authorization_owner=_authorization_owner())
        _render_authorization_browser(runtime, enabled=not runtime.busy)
        st.caption("O login abre em uma janela deste navegador. O uso local permanece disponível.")
        return

    _render_authorization_browser(runtime, enabled=False)
    st.caption(
        "Verificação a cada 10 minutos enquanto a interface estiver aberta. "
        "Um arquivo por carteira e computador, sem histórico de versões gerenciado pelo aplicativo."
    )
    _render_preferences(runtime, status, labels)
    left, right = st.columns(2)
    with left:
        if st.button("Consultar backups", disabled=runtime.busy, width="stretch"):
            runtime.submit("discover")
    with right:
        if st.button("Desconectar", disabled=runtime.busy, width="stretch"):
            st.session_state.pop("cloud_restore_preview", None)
            runtime.submit("disconnect")
    st.markdown(
        "Desconectar remove os tokens locais e mantém os backups. Para revogar o acesso no Google, "
        "abra [as conexões da sua conta](https://myaccount.google.com/connections)."
    )
    _render_discovery(runtime, status)
    _render_restore(runtime, labels)


def _authorization_owner() -> str:
    if "cloud_authorization_owner" not in st.session_state:
        st.session_state["cloud_authorization_owner"] = uuid.uuid4().hex
    return st.session_state["cloud_authorization_owner"]


def _render_authorization_browser(runtime, *, enabled):
    browser = getattr(runtime, "authorization_browser", None)
    if browser is not None:
        render_authorization_browser(browser, _authorization_owner(), enabled=enabled)


def _render_preferences(runtime, status, labels):
    preferences = (status.selected_filenames, status.machine_name, status.enabled)
    if st.session_state.get("cloud_saved_preferences") != preferences:
        for key in ("cloud_selected_portfolios", "cloud_machine_name", "cloud_backup_enabled"):
            st.session_state.pop(key, None)
        st.session_state["cloud_saved_preferences"] = preferences
    with st.form("cloud_backup_preferences"):
        selected = st.multiselect(
            "Carteiras com backup automático",
            options=list(labels),
            default=[name for name in status.selected_filenames if name in labels],
            format_func=lambda name: labels[name],
            key="cloud_selected_portfolios",
            disabled=runtime.busy,
        )
        machine = st.text_input(
            "Nome deste computador",
            value=status.machine_name,
            max_chars=60,
            key="cloud_machine_name",
            disabled=runtime.busy,
        )
        enabled = st.checkbox(
            "Ativar backup automático",
            value=status.enabled,
            key="cloud_backup_enabled",
            disabled=runtime.busy,
        )
        if st.form_submit_button("Salvar preferências", disabled=runtime.busy, width="stretch"):
            runtime.submit("configure", tuple(selected), machine, enabled=enabled)


def _render_discovery(runtime, status):
    if not status.remote_backups:
        if status.discovery_complete:
            st.caption("Nenhum backup foi encontrado nesta conta.")
        else:
            st.warning(
                "Não foi possível concluir a consulta dos backups. A aplicação tentará novamente."
            )
        return
    st.markdown("#### Recuperar uma carteira")
    st.caption(
        "As cópias aparecem pelo horário de atualização no Drive. A primeira é uma sugestão; "
        "um envio recente pode conter dados antigos."
    )
    choices = {backup.file_id: backup for backup in status.remote_backups}
    chosen = st.selectbox(
        "Backup disponível",
        options=list(choices),
        key="cloud_remote_backup",
        format_func=lambda file_id: (
            f"{choices[file_id].display_name} — {choices[file_id].machine_name} — "
            f"{_format_local_datetime(choices[file_id].modified_at_utc)}"
        ),
        disabled=runtime.busy,
    )
    if st.button("Inspecionar backup", disabled=runtime.busy, width="stretch"):
        st.session_state.pop("cloud_restore_preview", None)
        st.session_state.pop("cloud_interactive_error", None)
        runtime.submit("inspect", choices[chosen], result_owner=_authorization_owner())


def _render_restore(runtime, labels):
    saved = st.session_state.get("cloud_restore_preview")
    if saved is None:
        return
    remote, preview = saved
    selected = preview.portfolios[0]
    st.write(f"**Carteira:** {selected.display_name}")
    st.write(f"**Computador de origem:** {remote.machine_name}")
    st.write(f"**Backup criado em:** {_format_local_datetime(preview.created_at_utc)}")
    st.write(f"**Versão do aplicativo:** {preview.app_version}")
    if preview.cleanup_warning_path is not None:
        st.warning(f"A limpeza falhou. Verifique e remova {preview.cleanup_warning_path}.")
    destination_valid = True
    if selected.target.replaces_existing:
        st.warning("A carteira local será substituída. Uma cópia de recuperação será preservada.")
    else:
        mode = st.radio(
            "Destino da recuperação",
            ("Substituir carteira local", "Criar nova carteira")
            if labels
            else ("Criar nova carteira",),
            key=f"cloud_restore_mode_{preview.package_sha256}",
        )
        if mode == "Substituir carteira local":
            filename = st.selectbox(
                "Carteira local a substituir",
                options=tuple(labels),
                index=None,
                format_func=lambda name: f"{labels[name]} ({name})",
                placeholder="Selecione a carteira que será substituída",
                key=f"cloud_restore_target_{preview.package_sha256}",
            )
            destination_valid = filename is not None
            if destination_valid:
                try:
                    selected = runtime.choose_existing_destination(selected, filename)
                    st.warning(
                        "A carteira escolhida será substituída. Uma cópia de recuperação será preservada."
                    )
                except BackupRestoreError as error:
                    st.error(str(error))
                    destination_valid = False
        else:
            requested_name = st.text_input("Nome da carteira recuperada", key="cloud_restore_name")
            destination_valid = bool(requested_name.strip())
            if destination_valid:
                try:
                    selected = runtime.choose_new_destination(selected, requested_name)
                except BackupRestoreError as error:
                    st.error(str(error))
                    destination_valid = False
    if destination_valid:
        st.info(f"**Destino:** {labels.get(selected.target.filename, selected.target.filename)}")
    if selected.backup_is_older_than_local:
        st.warning("O backup pode ser anterior às alterações locais. Confira antes de recuperar.")
    confirmed = st.checkbox(
        "Confirmo a recuperação desta carteira",
        key=f"cloud_confirm_{preview.package_sha256}_{selected.target.filename if destination_valid else 'pending'}_{getattr(selected.target, 'state_token', '')}",
    )
    if st.button(
        "Restaurar carteira do Drive",
        disabled=runtime.busy or not confirmed or not destination_valid,
        width="stretch",
    ):
        st.session_state.pop("cloud_interactive_error", None)
        runtime.submit("restore", remote, selected, result_owner=_authorization_owner())


def _consume_result(runtime, *, account_changed):
    if (
        account_changed
        and not runtime.error
        and runtime.completed_operation in {"connect", "resume", "disconnect"}
    ):
        for key in (
            "cloud_selected_portfolios",
            "cloud_machine_name",
            "cloud_backup_enabled",
            "cloud_restore_preview",
            "cloud_remote_backup",
            "cloud_restore_name",
            "cloud_interactive_error",
        ):
            st.session_state.pop(key, None)
    completion = runtime.consume_result(_authorization_owner())
    if completion is None:
        return
    if completion.error:
        st.session_state["cloud_interactive_error"] = completion.error
        return
    st.session_state.pop("cloud_interactive_error", None)
    if completion.operation == "inspect" and completion.result is not None:
        st.session_state["cloud_restore_preview"] = completion.result
        st.session_state.pop("cloud_restore_name", None)
    elif completion.operation == "restore" and completion.result is not None:
        result = completion.result
        st.session_state.pop("cloud_restore_preview", None)
        st.session_state["active_db"] = result.database.name
        SessionManager.reset_portfolio_state()
        recovery = (
            f" A carteira anterior foi preservada em {result.recovery_directory}."
            if result.recovery_directory
            else ""
        )
        st.session_state[SESSION_PORTFOLIO_RESTORE_SUCCESS] = (
            f"Carteira recuperada do Drive.{recovery}"
        )
        if result.cleanup_warning_path is not None:
            st.session_state[SESSION_PORTFOLIO_RESTORE_CLEANUP_WARNING] = (
                f"A recuperação terminou, mas a limpeza falhou. Remova {result.cleanup_warning_path}."
            )
        st.rerun()

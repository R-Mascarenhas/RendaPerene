import hashlib
from collections.abc import Mapping
from datetime import datetime, tzinfo

import streamlit as st

from core.application_paths import PortfolioRestoreTarget
from core.constants import (
    SESSION_PORTFOLIO_RESTORE_PREVIEW,
    WIDGET_PORTFOLIO_RESTORE_CONFIRMATION_PREFIX,
    WIDGET_PORTFOLIO_RESTORE_CREDENTIAL_KIND,
    WIDGET_PORTFOLIO_RESTORE_LOCAL_PACKAGE,
    WIDGET_PORTFOLIO_RESTORE_NEW_NAME_PREFIX,
    WIDGET_PORTFOLIO_RESTORE_PACKAGE,
    WIDGET_PORTFOLIO_RESTORE_PASSWORD,
    WIDGET_PORTFOLIO_RESTORE_RECOVERY_KEY,
    WIDGET_PORTFOLIO_RESTORE_SELECTION_PREFIX,
    WIDGET_PORTFOLIO_RESTORE_SOURCE,
)
from services.local_restore_service import (
    BackupRestoreError,
    LocalRestoreService,
    RestoreCredential,
)


def render_local_restore(local_restore: LocalRestoreService, destination_labels: Mapping[str, str]):
    """Render package validation and explicit restore confirmation controls."""
    st.markdown("---")
    st.markdown("#### Restaurar backup")
    try:
        local_packages = local_restore.list_local_packages()
    except BackupRestoreError as error:
        st.error(str(error))
        local_packages = ()
    if local_packages:
        source = st.radio(
            "Origem do pacote",
            options=("Backups locais", "Enviar outro arquivo"),
            key=WIDGET_PORTFOLIO_RESTORE_SOURCE,
        )
    else:
        st.info("Nenhum pacote local encontrado. Envie um arquivo .rpb para restaurar.")
        source = "Enviar outro arquivo"
    package_content = None
    if source == "Backups locais":
        local_filename = st.selectbox(
            "Pacotes salvos nesta instalação",
            options=local_packages,
            key=WIDGET_PORTFOLIO_RESTORE_LOCAL_PACKAGE,
        )
        st.caption(
            "Pacotes mais recentes primeiro. Os dados da carteira aparecem após a validação."
        )
        try:
            package_content = local_restore.read_local_package(local_filename)
        except BackupRestoreError as error:
            st.error(str(error))
    else:
        package_upload = st.file_uploader(
            "Pacote de backup (.rpb)",
            type=["rpb"],
            key=WIDGET_PORTFOLIO_RESTORE_PACKAGE,
        )
        package_content = package_upload.getvalue() if package_upload is not None else None
    credential_kind = st.radio(
        "Credencial",
        options=("Senha", "Chave de recuperação"),
        horizontal=True,
        key=WIDGET_PORTFOLIO_RESTORE_CREDENTIAL_KIND,
    )
    credential = _render_credential(credential_kind)
    package_sha256 = hashlib.sha256(package_content).hexdigest() if package_content else None
    preview = st.session_state.get(SESSION_PORTFOLIO_RESTORE_PREVIEW)
    if preview is not None and preview.package_sha256 != package_sha256:
        st.session_state.pop(SESSION_PORTFOLIO_RESTORE_PREVIEW, None)
        preview = None

    if st.button(
        "Validar pacote",
        disabled=package_content is None or credential is None,
        use_container_width=True,
    ):
        try:
            with st.spinner("Validando criptografia, hashes e carteiras..."):
                preview = local_restore.inspect_package(package_content, credential)
        except BackupRestoreError as error:
            st.session_state.pop(SESSION_PORTFOLIO_RESTORE_PREVIEW, None)
            st.error(str(error))
            preview = None
        else:
            st.session_state[SESSION_PORTFOLIO_RESTORE_PREVIEW] = preview
            st.success("Pacote autenticado e validado com sucesso.")

    if preview is None:
        return None

    if preview.cleanup_warning_path is not None:
        st.warning(
            "O pacote foi validado, mas a limpeza dos arquivos temporários falhou. "
            f"Feche o aplicativo e remova manualmente {preview.cleanup_warning_path}."
        )
    st.write(f"**Data do backup:** {_format_local_datetime(preview.created_at_utc)}")
    selection_key = f"{WIDGET_PORTFOLIO_RESTORE_SELECTION_PREFIX}{preview.package_sha256}"
    selected = st.selectbox(
        "Carteira do pacote",
        options=preview.portfolios,
        format_func=lambda portfolio: portfolio.display_name,
        key=selection_key,
    )
    destination_ready = True
    if not selected.target.replaces_existing:
        requested_name = st.text_input(
            "Nome da nova carteira",
            placeholder="Ex.: João",
            help="Informe apenas o nome. A carteira aparecerá na lista com o prefixo 'Carteira:'.",
            key=(
                f"{WIDGET_PORTFOLIO_RESTORE_NEW_NAME_PREFIX}"
                f"{preview.package_sha256}:{selected.portfolio_id}"
            ),
        )
        if not requested_name:
            destination_ready = False
        else:
            try:
                selected = local_restore.choose_new_destination(selected, requested_name)
            except BackupRestoreError as error:
                st.error(str(error))
                destination_ready = False
    destination_description = _destination_description(selected.target, destination_labels)
    st.info(f"**Destino:** {destination_description}")
    if selected.backup_is_older_than_local:
        st.warning(
            "Este backup foi criado antes da última alteração detectada na carteira local. "
            "A restauração pode descartar mudanças mais recentes. Os horários dependem do "
            "relógio de cada dispositivo. "
            "Última alteração local: "
            f"{_format_local_datetime(selected.target.last_modified_at_utc)}."
        )
    if selected.target.replaces_existing:
        st.warning("A carteira atual será preservada em backups/pre-restore antes da substituição.")
    confirmation_key = (
        f"{WIDGET_PORTFOLIO_RESTORE_CONFIRMATION_PREFIX}"
        f"{preview.package_sha256}:{selected.portfolio_id}:"
        f"{selected.target.state_token}:{selected.target.requested_name}"
    )
    confirmation_label = (
        "Confirmo a restauração desta carteira e entendo que ela pode substituir dados locais."
        if selected.target.replaces_existing
        else "Confirmo a adição desta carteira com o nome escolhido."
    )
    confirmed = st.checkbox(
        confirmation_label,
        key=confirmation_key,
    )
    if st.button(
        "Restaurar carteira",
        type="primary",
        disabled=(
            not confirmed or credential is None or package_content is None or not destination_ready
        ),
        use_container_width=True,
    ):
        try:
            with st.spinner("Restaurando a carteira com proteção de rollback..."):
                return local_restore.restore_package(package_content, credential, selected)
        except BackupRestoreError as error:
            st.error(str(error))
    return None


def _format_local_datetime(value: str, local_timezone: tzinfo | None = None) -> str:
    local = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(local_timezone)
    offset = local.strftime("%z")
    return f"{local:%d/%m/%Y às %H:%M:%S} (UTC{offset[:3]}:{offset[3:]})"


def _destination_description(
    target: PortfolioRestoreTarget, destination_labels: Mapping[str, str]
) -> str:
    if not target.replaces_existing:
        if target.requested_name is not None:
            return f"Será adicionada como Carteira: {target.requested_name.title()}."
        return "Será adicionada como nova carteira."
    label = destination_labels.get(target.filename)
    if label is None:
        return "Substituirá a carteira local correspondente."
    return f"Substituirá a {label}."


def _render_credential(kind: str) -> RestoreCredential | None:
    if kind == "Senha":
        password = st.text_input(
            "Senha do pacote",
            type="password",
            key=WIDGET_PORTFOLIO_RESTORE_PASSWORD,
        )
        if password and len(password) < 4:
            st.error("A senha do backup deve ter pelo menos 4 caracteres.")
        return RestoreCredential.with_password(password) if len(password) >= 4 else None

    recovery_key = st.file_uploader(
        "Chave de recuperação (.key)",
        type=["key"],
        key=WIDGET_PORTFOLIO_RESTORE_RECOVERY_KEY,
    )
    if recovery_key is None:
        return None
    return RestoreCredential.with_recovery_key(recovery_key.getvalue())

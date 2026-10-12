"""Automatic, user-selected backups with one remote copy per installation."""

import threading
import time
from collections.abc import Callable

from core.application_paths import ApplicationPaths
from core.cloud_backup.models import CloudAuthorizationError, CloudBackupError, CloudBackupStatus
from core.cloud_backup.state import CloudBackupStateStore
from core.ports import CloudBackupProviderPort
from services.local_backup_service import (
    BackupCreationError,
    LocalBackupService,
    PortfolioBackupSelection,
)

BACKUP_INTERVAL_SECONDS = 600


class CloudBackupService:
    def __init__(
        self,
        provider: CloudBackupProviderPort,
        state_store: CloudBackupStateStore,
        backup_service: LocalBackupService,
        paths: ApplicationPaths,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.provider = provider
        self._store = state_store
        self._backups = backup_service
        self._paths = paths
        self._clock = clock
        self._lock = threading.RLock()
        self._account = None
        self._resume_pending = False
        self._credential_removal_pending = self._store.load().get(
            "credential_removal_pending", False
        )
        self._discovery_retry_pending = False
        self._last_discovery_attempt = clock()
        self._remote = ()
        self._discovery_complete = False
        self._message = ""
        self._error = ""
        self._busy = False
        self._initial_check = clock()

    def _preferences(self, state: dict) -> dict:
        accounts = state.setdefault("accounts", {})
        return accounts.setdefault(
            self._account,
            {
                "enabled": False,
                "selected": [],
                "machine_name": "Computador",
                "sent": {},
            },
        )

    def status(self) -> CloudBackupStatus:
        # Atomic state-file publication keeps status reads independent of slow uploads.
        account = self._account
        state = self._store.load()
        preferences = state.get("accounts", {}).get(account, {}) if account else {}
        removal_pending = self._credential_removal_pending or state.get(
            "credential_removal_pending", False
        )
        return CloudBackupStatus(
            bool(account) and not removal_pending,
            preferences.get("enabled", False),
            tuple(preferences.get("selected", ())),
            preferences.get("machine_name", "Computador"),
            self._discovery_complete,
            self._remote,
            self._busy,
            self._message,
            self._error,
            removal_pending,
        )

    def connect(self) -> None:
        with self._lock:
            self._require_completed_credential_removal()
            self._resume_pending = False
            self._account = self.provider.connect()
            self._initial_check = self._clock()
            self._discover()

    def resume(self) -> None:
        with self._lock:
            if self._credential_removal_pending or self._store.load().get(
                "credential_removal_pending", False
            ):
                return
            try:
                self._account = self.provider.resume()
                self._resume_pending = False
            except CloudBackupError as error:
                self._resume_pending = not isinstance(error, CloudAuthorizationError)
                raise
            if self._account:
                self._initial_check = self._clock()
                self._discover()

    def _discover(self) -> None:
        self._discovery_complete = False
        self._remote = ()
        self._discovery_retry_pending = True
        self._last_discovery_attempt = self._clock()
        try:
            self._remote = tuple(
                sorted(
                    self.provider.list_backups(), key=lambda item: item.modified_at, reverse=True
                )
            )
        except CloudAuthorizationError:
            self._account = None
            self._discovery_retry_pending = False
            raise
        self._discovery_complete = True
        self._discovery_retry_pending = False
        self._error = ""

    def discover(self) -> None:
        with self._lock:
            self._require_connection()
            self._discover()

    def disconnect(self) -> None:
        with self._lock:
            self._resume_pending = False
            self._account = None
            self._remote = ()
            self._discovery_complete = False
            self._discovery_retry_pending = False
            self._credential_removal_pending = True
            with self._store.transaction() as state:
                state["credential_removal_pending"] = True
            self.provider.disconnect()
            with self._store.transaction() as state:
                state["credential_removal_pending"] = False
            self._credential_removal_pending = False
            self._message = "Conexão local removida. Os backups no Drive foram mantidos."

    def configure(self, filenames: tuple[str, ...], machine_name: str, *, enabled: bool) -> None:
        with self._lock:
            self._require_connection()
            valid = {path.name for path in self._paths.inspect_portfolios().valid}
            if (
                len(set(filenames)) != len(filenames)
                or any(filename not in valid for filename in filenames)
                or not isinstance(machine_name, str)
                or not machine_name.strip()
                or len(machine_name) > 60
            ):
                raise CloudBackupError(
                    "Revise as carteiras e informe um nome de computador válido."
                )
            selected_ids = {
                filename: self._paths.portfolio_identity(filename) for filename in filenames
            }
            if any(identity is None for identity in selected_ids.values()):
                raise CloudBackupError("Uma carteira mudou. Revise a seleção do backup automático.")
            if len(set(selected_ids.values())) != len(selected_ids):
                raise CloudBackupError(
                    "Há carteiras com a mesma identidade. Selecione apenas uma cópia para backup."
                )
            with self._store.transaction() as state:
                preferences = self._preferences(state)
                preferences.update(
                    selected=list(filenames),
                    selected_ids=selected_ids,
                    machine_name=machine_name.strip(),
                    enabled=bool(enabled),
                )
                preferences["last_check"] = self._clock()
            self._error = ""

    def check_due(self) -> None:
        with self._lock:
            if self._credential_removal_pending or self._store.load().get(
                "credential_removal_pending", False
            ):
                return
            if self._account and self._discovery_retry_pending:
                if self._clock() - self._last_discovery_attempt >= BACKUP_INTERVAL_SECONDS:
                    try:
                        self._discover()
                    except CloudBackupError as error:
                        self._error = str(error)
                if self._discovery_retry_pending or not self._account:
                    return
            if not self._account and self._resume_pending:
                try:
                    self.resume()
                except CloudBackupError as error:
                    self._error = str(error)
                return
            if not self._account:
                return
            try:
                with self._store.transaction() as state:
                    preferences = self._preferences(state)
                    if not preferences["enabled"] or not preferences["selected"]:
                        return
                    now = self._clock()
                    previous_check = preferences.get("last_check", self._initial_check)
                    if now < previous_check:
                        preferences["last_check"] = now
                        return
                    previous_check = max(previous_check, self._initial_check)
                    if now - previous_check < BACKUP_INTERVAL_SECONDS:
                        return
                    preferences["last_check"] = now
                    self._busy = True
                    self._error = ""
                    identities = [
                        preferences.get("selected_ids", {}).get(filename)
                        for filename in preferences["selected"]
                    ]
                    if len(set(identities)) != len(identities):
                        self._busy = False
                        self._error = "Há carteiras com a mesma identidade. Revise e salve a seleção do backup automático."
                        return
                    try:
                        self._remote = tuple(
                            sorted(
                                self.provider.list_backups(),
                                key=lambda item: item.modified_at,
                                reverse=True,
                            )
                        )
                        self._discovery_complete = True
                    except CloudBackupError as error:
                        self._error = str(error)
                        if isinstance(error, CloudAuthorizationError):
                            self._account = None
                            self._discovery_complete = False
                        return
                    inventory = {path.name: path for path in self._paths.inspect_portfolios().valid}
                    sent_count = 0
                    for filename in preferences["selected"]:
                        database = inventory.get(filename)
                        if database is None:
                            self._error = "Uma carteira selecionada não está mais disponível. Revise a seleção."
                            continue
                        selected_id = preferences.get("selected_ids", {}).get(filename)
                        if (
                            selected_id is None
                            or self._paths.portfolio_identity(filename) != selected_id
                        ):
                            self._error = "A identidade de uma carteira mudou. Revise e salve a seleção do backup automático."
                            continue
                        selection = PortfolioBackupSelection(
                            filename,
                            self._paths.database_generation(database),
                            self._display_name(filename),
                        )
                        try:
                            artifact = self._backups.create_cloud_backup(
                                selection, preferences["machine_name"]
                            )
                            if artifact.portfolio_id != selected_id:
                                raise CloudBackupError(
                                    "A carteira mudou durante o backup. Revise a seleção."
                                )
                            remote_exists = any(
                                item.portfolio_id == artifact.portfolio_id
                                and item.installation_id == artifact.installation_id
                                for item in self._remote
                            )
                            if (
                                remote_exists
                                and preferences["sent"].get(artifact.portfolio_id)
                                == artifact.fingerprint
                            ):
                                continue
                            if (
                                self._paths.database_generation(database)
                                != selection.expected_generation
                            ):
                                raise CloudBackupError(
                                    "A carteira mudou durante o backup. Tente novamente."
                                )
                            remote = self.provider.upload(artifact)
                            self._remote = tuple(
                                sorted(
                                    [
                                        item
                                        for item in self._remote
                                        if item.file_id != remote.file_id
                                    ]
                                    + [remote],
                                    key=lambda item: item.modified_at,
                                    reverse=True,
                                )
                            )
                            preferences["sent"][artifact.portfolio_id] = artifact.fingerprint
                            sent_count += 1
                        except (CloudBackupError, BackupCreationError) as error:
                            self._error = str(error)
                            if isinstance(error, CloudAuthorizationError):
                                self._account = None
                                self._discovery_complete = False
                                break
                    self._message = (
                        f"Verificação concluída. Backups enviados: {sent_count}."
                        if sent_count
                        else "Verificação concluída. Nenhum novo backup enviado."
                    )
            except CloudBackupError as error:
                self._error = str(error)
                if isinstance(error, CloudAuthorizationError):
                    self._account = None
                    self._discovery_complete = False
            finally:
                self._busy = False

    def download(self, remote) -> bytes:
        with self._lock:
            self._require_connection()
            return self.provider.download(remote)

    @staticmethod
    def _display_name(filename: str) -> str:
        name = filename.removesuffix(".db").removeprefix("portfolio_")
        return "Principal" if name == "portfolio" else name.replace("_", " ")

    def _require_connection(self):
        self._require_completed_credential_removal()
        if not self._account:
            raise CloudAuthorizationError("Conecte sua conta Google para continuar.")

    def _require_completed_credential_removal(self):
        if self._credential_removal_pending or self._store.load().get(
            "credential_removal_pending", False
        ):
            raise CloudBackupError(
                "Conclua a remoção das credenciais locais antes de conectar novamente."
            )

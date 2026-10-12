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
            {"enabled": False, "selected": [], "machine_name": "Computador", "sent": {}},
        )

    def status(self) -> CloudBackupStatus:
        # Atomic state-file publication keeps status reads independent of slow uploads.
        account = self._account
        preferences = self._store.load().get("accounts", {}).get(account, {}) if account else {}
        return CloudBackupStatus(
            bool(account),
            preferences.get("enabled", False),
            tuple(preferences.get("selected", ())),
            preferences.get("machine_name", "Computador"),
            self._discovery_complete,
            self._remote,
            self._busy,
            self._message,
            self._error,
        )

    def connect(self) -> None:
        with self._lock:
            self._resume_pending = False
            self._account = self.provider.connect()
            self._initial_check = self._clock()
            self._discover()

    def resume(self) -> None:
        with self._lock:
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
        self._remote = tuple(
            sorted(self.provider.list_backups(), key=lambda item: item.modified_at, reverse=True)
        )
        self._discovery_complete = not self._remote
        self._error = ""

    def discover(self) -> None:
        with self._lock:
            self._require_connection()
            self._discover()

    def dismiss_discovery(self) -> None:
        with self._lock:
            self._require_connection()
            self._discovery_complete = True

    def disconnect(self) -> None:
        with self._lock:
            self._resume_pending = False
            self._account = None
            self._remote = ()
            self._discovery_complete = False
            self.provider.disconnect()
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
            with self._store.transaction() as state:
                preferences = self._preferences(state)
                preferences.update(
                    selected=list(filenames),
                    machine_name=machine_name.strip(),
                    enabled=bool(enabled),
                )
                preferences["last_check"] = self._clock()
            self._error = ""

    def check_due(self) -> None:
        with self._lock:
            if not self._account and self._resume_pending:
                try:
                    self.resume()
                except CloudBackupError as error:
                    self._error = str(error)
                return
            if not self._account or not self._discovery_complete:
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
                    try:
                        self._remote = tuple(
                            sorted(
                                self.provider.list_backups(),
                                key=lambda item: item.modified_at,
                                reverse=True,
                            )
                        )
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
                        selection = PortfolioBackupSelection(
                            filename,
                            self._paths.database_generation(database),
                            self._display_name(filename),
                        )
                        try:
                            artifact = self._backups.create_cloud_backup(
                                selection, preferences["machine_name"]
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

    def mark_restored(self) -> None:
        """Resume automatic backup only after the user completes recovery."""
        with self._lock:
            self._discovery_complete = True

    @staticmethod
    def _display_name(filename: str) -> str:
        name = filename.removesuffix(".db").removeprefix("portfolio_")
        return "Principal" if name == "portfolio" else name.replace("_", " ")

    def _require_connection(self):
        if not self._account:
            raise CloudAuthorizationError("Conecte sua conta Google para continuar.")

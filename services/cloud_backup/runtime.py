"""Single-flight background operations; worker threads never access Streamlit state."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.cloud_backup.models import CloudBackupError, CloudBackupOperationResult
from core.ports import BrowserAuthorizationPort
from services.cloud_backup.service import CloudBackupService
from services.local_restore_service import BackupRestoreError, LocalRestoreService

logger = logging.getLogger(__name__)


class CloudBackupRuntime:
    def __init__(
        self,
        service: CloudBackupService,
        restore_service: LocalRestoreService,
        *,
        authorization_browser: BrowserAuthorizationPort | None = None,
    ):
        self.service = service
        self._restores = restore_service
        self.authorization_browser = authorization_browser
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloud-backup")
        self._lock = threading.Lock()
        self._future = None
        self._operation = None
        self._result_owner = None
        self._pending_results = {}
        self.error = ""
        self.result = None
        self.completed_operation = None
        self.revision = 0
        self._last_dispatch = time.monotonic()

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._future is not None

    def submit(
        self,
        operation: str,
        *args,
        authorization_owner: str | None = None,
        result_owner: str | None = None,
        **kwargs,
    ) -> bool:
        methods = {
            "connect": self.service.connect,
            "resume": self.service.resume,
            "discover": self.service.discover,
            "disconnect": self.service.disconnect,
            "configure": self.service.configure,
            "check_due": self.service.check_due,
            "inspect": self._inspect,
            "restore": self._restore,
        }
        with self._lock:
            if self._future is not None:
                return False
            if operation in {"inspect", "restore"}:
                if not isinstance(result_owner, str) or not result_owner:
                    raise CloudBackupError("Inicie a recuperação pela sessão atual do RendaPerene.")
                if result_owner in self._pending_results:
                    return False
            if operation == "connect" and self.authorization_browser is not None:
                if not authorization_owner:
                    raise CloudBackupError(
                        "Inicie a conexão pelo botão desta sessão do RendaPerene."
                    )
                self.authorization_browser.begin(authorization_owner)
            self.error = ""
            self._operation = operation
            self._result_owner = result_owner
            logger.info("cloud_backup.operation.started operation=%s", operation)
            self._future = self._executor.submit(methods[operation], *args, **kwargs)
            return True

    def schedule_due(self) -> None:
        from services.cloud_backup.service import BACKUP_INTERVAL_SECONDS

        now = time.monotonic()
        if now - self._last_dispatch >= BACKUP_INTERVAL_SECONDS and self.submit("check_due"):
            self._last_dispatch = now

    def poll(self) -> None:
        with self._lock:
            if self._future is None or not self._future.done():
                return
            self.result = None
            try:
                self.result = self._future.result()
                logger.info("cloud_backup.operation.completed operation=%s", self._operation)
            except (CloudBackupError, BackupRestoreError) as error:
                self.error = str(error)
                logger.warning(
                    "cloud_backup.operation.failed operation=%s error_type=%s",
                    self._operation,
                    type(error).__name__,
                )
            except Exception as error:
                logger.warning("cloud_backup.operation.failed error_type=%s", type(error).__name__)
                self.error = "Não foi possível concluir a operação do backup. Tente novamente."
            self.completed_operation = self._operation
            if self._operation in {"inspect", "restore"}:
                self._pending_results[self._result_owner] = CloudBackupOperationResult(
                    self._operation, self.result, self.error
                )
            if self._operation == "connect" and self.authorization_browser is not None:
                self.authorization_browser.finish()
            if self._operation in {"configure", "connect", "resume", "check_due"}:
                self._last_dispatch = time.monotonic()
            self._future = None
            self.revision += 1

    def consume_result(self, owner: str) -> CloudBackupOperationResult | None:
        """Deliver interactive results once, exclusively to their submitting session."""
        with self._lock:
            return self._pending_results.pop(owner, None)

    def _inspect(self, remote):
        content = self.service.download(remote)
        preview = self._restores.inspect_cloud_package(content)
        if (
            preview.installation_id != remote.installation_id
            or preview.portfolios[0].portfolio_id != remote.portfolio_id
        ):
            raise CloudBackupError("O conteúdo do backup não corresponde à identificação no Drive.")
        return remote, preview

    def _restore(self, remote, selected):
        content = self.service.download(remote)
        result = self._restores.restore_cloud_package(content, selected)
        return result

    def choose_new_destination(self, selected, name):
        return self._restores.choose_new_destination(selected, name)

    def choose_existing_destination(self, selected, filename):
        return self._restores.choose_existing_destination(selected, filename)

    def close(self) -> None:
        if self.authorization_browser is not None:
            self.authorization_browser.finish()
        self._executor.shutdown(wait=True, cancel_futures=True)

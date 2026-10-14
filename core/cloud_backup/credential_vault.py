"""Explicit Windows and Secret Service credential storage, without fallback files."""

import sys
import uuid
from collections.abc import Callable

from core.cloud_backup.models import CloudBackupError


class SystemCredentialVault:
    def __init__(
        self, service_name: str, account_key: str, *, backend_loader: Callable | None = None
    ):
        self._service_name = service_name
        self._account_key = account_key
        self._backend_loader = backend_loader or self._load_supported_backend
        self._backend = None

    @staticmethod
    def _load_supported_backend():
        if sys.platform.startswith("win"):
            try:
                from keyring.backends.Windows import WinVaultKeyring

                # The module can import with its native dependencies missing.
                _ = WinVaultKeyring.priority
                return WinVaultKeyring()
            except (ImportError, RuntimeError):
                raise CloudBackupError(
                    "Os componentes de acesso ao cofre do Windows não estão disponíveis. "
                    "Atualize a instalação do RendaPerene e reinicie a aplicação."
                ) from None
        if sys.platform.startswith("linux"):
            try:
                from keyring.backends.SecretService import Keyring

                return Keyring()
            except ImportError:
                raise CloudBackupError(
                    "Os componentes de acesso ao cofre do Linux não estão disponíveis. "
                    "Atualize a instalação do RendaPerene e reinicie a aplicação."
                ) from None
        raise CloudBackupError("Este sistema não possui um cofre de credenciais suportado.")

    def _get_backend(self):
        if self._backend is None:
            self._backend = self._backend_loader()
        return self._backend

    @staticmethod
    def _unavailable():
        return CloudBackupError(
            "O cofre seguro do sistema está indisponível ou bloqueado. "
            "Desbloqueie o cofre para usar o Google Drive; o uso local continua disponível."
        )

    def ensure_available(self) -> None:
        probe = f"probe-{uuid.uuid4().hex}"
        try:
            backend = self._get_backend()
            backend.set_password(self._service_name, probe, probe)
            if backend.get_password(self._service_name, probe) != probe:
                raise self._unavailable()
            backend.delete_password(self._service_name, probe)
        except CloudBackupError:
            raise
        except Exception:
            raise self._unavailable() from None

    def read(self) -> str | None:
        try:
            return self._get_backend().get_password(self._service_name, self._account_key)
        except CloudBackupError:
            raise
        except Exception:
            raise self._unavailable() from None

    def write(self, credential: str) -> None:
        try:
            backend = self._get_backend()
            backend.set_password(self._service_name, self._account_key, credential)
            if backend.get_password(self._service_name, self._account_key) != credential:
                raise self._unavailable()
        except CloudBackupError:
            raise
        except Exception:
            raise self._unavailable() from None

    def delete(self) -> None:
        try:
            backend = self._get_backend()
            if backend.get_password(self._service_name, self._account_key) is not None:
                backend.delete_password(self._service_name, self._account_key)
            if backend.get_password(self._service_name, self._account_key) is not None:
                raise self._unavailable()
        except CloudBackupError:
            raise
        except Exception:
            raise self._unavailable() from None

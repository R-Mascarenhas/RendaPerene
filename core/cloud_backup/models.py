"""Values shared by automatic backup services and storage adapters."""

from dataclasses import dataclass, field
from datetime import datetime


class CloudBackupError(RuntimeError):
    """A sanitized, recoverable cloud backup failure."""


class CloudAuthorizationError(CloudBackupError):
    """The user must authorize the provider again."""


@dataclass(frozen=True)
class CloudBackupArtifact:
    content: bytes = field(repr=False)
    portfolio_id: str
    installation_id: str
    display_name: str
    machine_name: str
    fingerprint: str


@dataclass(frozen=True)
class RemoteBackup:
    file_id: str
    portfolio_id: str
    installation_id: str
    display_name: str
    machine_name: str
    modified_at_utc: str
    version: str

    @property
    def modified_at(self) -> datetime:
        return datetime.fromisoformat(self.modified_at_utc.replace("Z", "+00:00"))


@dataclass(frozen=True)
class CloudBackupStatus:
    connected: bool
    enabled: bool
    selected_filenames: tuple[str, ...]
    machine_name: str
    discovery_complete: bool
    remote_backups: tuple[RemoteBackup, ...] = ()
    busy: bool = False
    message: str = ""
    error: str = ""


@dataclass(frozen=True)
class OAuthClientConfiguration:
    client_id: str
    client_secret: str = field(default="", repr=False)

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.application_paths import ApplicationPaths
from core.database import DatabaseManager

SNAPSHOT_FORMAT_VERSION = 1


@dataclass(frozen=True)
class SnapshotResult:
    """Describes one completely published local SQLite snapshot."""

    directory: Path
    database_file: Path
    metadata_file: Path
    metadata: dict


class SnapshotCreationError(RuntimeError):
    """Reports a safe user-facing failure to create a local snapshot."""


class LocalSnapshotService:
    """Create validated local portfolio snapshots behind one small interface."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        application_paths: ApplicationPaths,
        app_version: str,
    ):
        self._database_manager = database_manager
        self._paths = application_paths
        self._app_version = app_version

    def create_snapshot(self) -> SnapshotResult:
        """Create and atomically publish a validated backup of the active portfolio."""
        snapshot_id = str(uuid.uuid4())
        backups_dir = self._paths.local_backups_dir
        temporary_dir = backups_dir / f".{snapshot_id}.tmp"
        published_dir = backups_dir / snapshot_id
        database_file = temporary_dir / "backup.sqlite3"
        metadata_file = temporary_dir / "metadata.json"

        try:
            database_path = self._database_manager.get_personal_database_path()
            if not database_path.is_file():
                raise SnapshotCreationError(
                    "A carteira ativa não está disponível para a criação do backup."
                )
            backups_dir.mkdir(parents=True, exist_ok=True)
            temporary_dir.mkdir(parents=False, exist_ok=False)
            installation_id = self._paths.get_or_create_installation_id()
            self._backup_database(database_file)
            portfolio_id, schema_version = self._validate_and_read_identity(database_file)
            checksum = self._sha256(database_file)
            metadata = {
                "format_version": SNAPSHOT_FORMAT_VERSION,
                "backup_id": snapshot_id,
                "portfolio_id": portfolio_id,
                "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "app_version": self._app_version,
                "schema_version": schema_version,
                "installation_id": installation_id,
                "sha256": checksum,
                "encryption_state": "unencrypted",
            }
            self._write_metadata(metadata_file, metadata)
            os.replace(temporary_dir, published_dir)
            return SnapshotResult(
                directory=published_dir,
                database_file=published_dir / database_file.name,
                metadata_file=published_dir / metadata_file.name,
                metadata=metadata,
            )
        except SnapshotCreationError:
            raise
        except TimeoutError:
            raise SnapshotCreationError(
                "A carteira está em uso por outra operação. Tente criar o backup novamente."
            ) from None
        except sqlite3.DatabaseError:
            raise SnapshotCreationError(
                "Não foi possível criar um backup SQLite consistente da carteira ativa."
            ) from None
        except (OSError, UnicodeError, ValueError):
            raise SnapshotCreationError(
                "Não foi possível salvar o backup no armazenamento local."
            ) from None
        finally:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)

    def _backup_database(self, destination: Path) -> None:
        source_connection = self._database_manager.get_personal_connection()
        try:
            destination_connection = sqlite3.connect(destination)
            try:
                source_connection.backup(destination_connection)
                destination_connection.commit()
            finally:
                destination_connection.close()
        finally:
            source_connection.close()

    @staticmethod
    def _validate_and_read_identity(database_file: Path) -> tuple[str, int]:
        connection = sqlite3.connect(f"{database_file.resolve().as_uri()}?mode=ro", uri=True)
        try:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            if integrity_rows != [("ok",)]:
                raise SnapshotCreationError(
                    "O backup criado não passou na verificação de integridade."
                )
            portfolio_row = connection.execute(
                "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
            ).fetchone()
            if portfolio_row is None:
                raise SnapshotCreationError("O backup criado não possui identificação da carteira.")
            portfolio_id = portfolio_row[0]
            try:
                parsed_portfolio_id = uuid.UUID(portfolio_id)
            except (AttributeError, TypeError, ValueError):
                raise SnapshotCreationError(
                    "O backup criado possui identificação da carteira inválida."
                ) from None
            if str(parsed_portfolio_id) != portfolio_id:
                raise SnapshotCreationError(
                    "O backup criado possui identificação da carteira inválida."
                )
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            return portfolio_id, schema_version
        finally:
            connection.close()

    @staticmethod
    def _sha256(path: Path) -> str:
        checksum = hashlib.sha256()
        with path.open("rb") as snapshot:
            for chunk in iter(lambda: snapshot.read(1024 * 1024), b""):
                checksum.update(chunk)
        return checksum.hexdigest()

    @staticmethod
    def _write_metadata(path: Path, metadata: dict) -> None:
        with path.open("x", encoding="utf-8") as destination:
            json.dump(metadata, destination, ensure_ascii=False, indent=2, sort_keys=True)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())

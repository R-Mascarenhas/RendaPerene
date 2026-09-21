import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.application_paths import ApplicationPaths
from core.ports import (
    PortfolioBackupIdentityError,
    PortfolioBackupIntegrityError,
    PortfolioBackupReaderPort,
    PortfolioBackupSelectionError,
    PortfolioBackupSourceError,
    PortfolioBackupSourceFactoryPort,
    PortfolioBackupUnavailableError,
)

BACKUP_FORMAT_VERSION = 2
OWNER_ONLY_DIRECTORY_MODE = 0o700
OWNER_ONLY_FILE_MODE = 0o600


@dataclass(frozen=True)
class PortfolioBackupSelection:
    """Pins one user-selected portfolio to its current local generation."""

    filename: str
    expected_generation: str | None
    display_name: str


@dataclass(frozen=True)
class BackupResult:
    """Describes one completely published local backup set."""

    directory: Path
    manifest_file: Path
    manifest: dict
    portfolio_count: int


class BackupCreationError(RuntimeError):
    """Reports a safe user-facing failure to create a local backup set."""


@dataclass(frozen=True)
class _BackupSetContext:
    backup_id: str
    created_at_utc: str
    installation_id: str
    portfolios_directory: Path


class LocalBackupService:
    """Create one validated local backup set for selected portfolios."""

    def __init__(
        self,
        source_factory: PortfolioBackupSourceFactoryPort,
        application_paths: ApplicationPaths,
        app_version: str,
    ):
        self._source_factory = source_factory
        self._paths = application_paths
        self._app_version = app_version

    def create_backup(
        self,
        selections: Sequence[PortfolioBackupSelection],
    ) -> BackupResult:
        """Create and atomically publish a backup of every selected portfolio."""
        pinned_selections = tuple(selections)
        self._validate_selections(pinned_selections)

        backup_id = str(uuid.uuid4())
        created_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        backups_dir = self._paths.local_backups_dir
        temporary_dir = backups_dir / f".{backup_id}.tmp"
        published_dir = backups_dir / backup_id
        portfolios_dir = temporary_dir / "carteiras"
        manifest_file = temporary_dir / "manifest.json"

        try:
            sources = [
                self._source_factory.create(
                    selection.filename,
                    selection.expected_generation,
                )
                for selection in pinned_selections
            ]
            self._create_owner_only_directory(self._paths.backups_dir, parents=True)
            self._create_owner_only_directory(backups_dir, parents=True)
            self._create_owner_only_directory(temporary_dir, parents=False, exist_ok=False)
            self._create_owner_only_directory(portfolios_dir, parents=False, exist_ok=False)
            installation_id = self._paths.get_or_create_installation_id()
            context = _BackupSetContext(
                backup_id=backup_id,
                created_at_utc=created_at_utc,
                installation_id=installation_id,
                portfolios_directory=portfolios_dir,
            )
            portfolio_entries = []

            for source in sources:
                source.prepare()

            with ExitStack() as source_stack:
                readers = [source_stack.enter_context(source.open_reader()) for source in sources]
                for index, (selection, reader) in enumerate(
                    zip(pinned_selections, readers, strict=True)
                ):
                    entry = self._create_portfolio_snapshot(
                        reader=reader,
                        staging_directory=portfolios_dir / f".{index}.tmp",
                        context=context,
                        display_name=selection.display_name,
                    )
                    portfolio_entries.append(entry)

                manifest = {
                    "format_version": BACKUP_FORMAT_VERSION,
                    "backup_id": backup_id,
                    "created_at_utc": created_at_utc,
                    "app_version": self._app_version,
                    "installation_id": installation_id,
                    "encryption_state": "unencrypted",
                    "portfolio_count": len(portfolio_entries),
                    "portfolios": portfolio_entries,
                }
                self._write_json(manifest_file, manifest)
                os.replace(temporary_dir, published_dir)
                return BackupResult(
                    directory=published_dir,
                    manifest_file=published_dir / manifest_file.name,
                    manifest=manifest,
                    portfolio_count=len(portfolio_entries),
                )
        except BackupCreationError:
            raise
        except PortfolioBackupSelectionError:
            raise BackupCreationError(
                "A seleção contém uma carteira local inválida. Revise a seleção e tente novamente."
            ) from None
        except PortfolioBackupUnavailableError:
            raise BackupCreationError(
                "Uma carteira selecionada foi removida ou substituída. "
                "Revise a seleção e tente novamente."
            ) from None
        except PortfolioBackupIntegrityError:
            raise BackupCreationError(
                "Uma carteira selecionada não passou na verificação de integridade. "
                "O backup não foi criado."
            ) from None
        except PortfolioBackupIdentityError:
            raise BackupCreationError(
                "Uma carteira copiada possui identificação inválida."
            ) from None
        except TimeoutError:
            raise BackupCreationError(
                "Uma das carteiras está em uso por outra operação. Tente criar o backup novamente."
            ) from None
        except PortfolioBackupSourceError:
            raise BackupCreationError(
                "Não foi possível criar um backup SQLite consistente das carteiras selecionadas."
            ) from None
        except (OSError, UnicodeError, ValueError):
            raise BackupCreationError(
                "Não foi possível salvar o backup no armazenamento local."
            ) from None
        finally:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)

    def _create_portfolio_snapshot(
        self,
        reader: PortfolioBackupReaderPort,
        staging_directory: Path,
        context: _BackupSetContext,
        display_name: str,
    ) -> dict:
        self._create_owner_only_directory(staging_directory, parents=False, exist_ok=False)
        database_file = staging_directory / "backup.sqlite3"
        metadata_file = staging_directory / "metadata.json"
        snapshot_identity = reader.backup_to(database_file)
        portfolio_id = snapshot_identity.portfolio_id
        schema_version = snapshot_identity.schema_version
        checksum = self._sha256(database_file)
        metadata = {
            "format_version": BACKUP_FORMAT_VERSION,
            "backup_id": context.backup_id,
            "portfolio_id": portfolio_id,
            "display_name": display_name,
            "created_at_utc": context.created_at_utc,
            "app_version": self._app_version,
            "schema_version": schema_version,
            "installation_id": context.installation_id,
            "sha256": checksum,
            "encryption_state": "unencrypted",
        }
        self._write_json(metadata_file, metadata)

        published_directory = context.portfolios_directory / portfolio_id
        if published_directory.exists():
            raise BackupCreationError(
                "Duas carteiras selecionadas possuem a mesma identificação. "
                "O backup não foi criado."
            )
        os.replace(staging_directory, published_directory)
        return {
            "portfolio_id": portfolio_id,
            "display_name": display_name,
            "relative_path": f"carteiras/{portfolio_id}",
            "schema_version": schema_version,
            "sha256": checksum,
        }

    def _validate_selections(
        self,
        selections: tuple[PortfolioBackupSelection, ...],
    ) -> None:
        if not selections:
            raise BackupCreationError("Selecione pelo menos uma carteira para criar o backup.")
        filenames = [selection.filename for selection in selections]
        if len(set(filenames)) != len(filenames):
            raise BackupCreationError("Cada carteira deve ser selecionada apenas uma vez.")
        if any(
            not isinstance(selection.display_name, str) or not selection.display_name.strip()
            for selection in selections
        ):
            raise BackupCreationError(
                "Cada carteira selecionada deve possuir um nome exibido válido."
            )

    @staticmethod
    def _sha256(path: Path) -> str:
        checksum = hashlib.sha256()
        with path.open("rb") as snapshot:
            for chunk in iter(lambda: snapshot.read(1024 * 1024), b""):
                checksum.update(chunk)
        return checksum.hexdigest()

    @staticmethod
    def _create_owner_only_directory(
        path: Path,
        *,
        parents: bool,
        exist_ok: bool = True,
    ) -> None:
        path.mkdir(
            parents=parents,
            exist_ok=exist_ok,
            mode=OWNER_ONLY_DIRECTORY_MODE,
        )
        if os.name == "posix":
            path.chmod(OWNER_ONLY_DIRECTORY_MODE)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            OWNER_ONLY_FILE_MODE,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                descriptor = None
                if os.name == "posix":
                    os.chmod(path, OWNER_ONLY_FILE_MODE)
                json.dump(payload, destination, ensure_ascii=False, indent=2, sort_keys=True)
                destination.write("\n")
                destination.flush()
                os.fsync(destination.fileno())
        finally:
            if descriptor is not None:
                os.close(descriptor)

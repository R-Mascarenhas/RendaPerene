import hashlib
import json
import logging
import os
import shutil
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from core.application_paths import (
    ApplicationPaths,
    PortfolioRestoreBusyError,
    PortfolioRestoreConflictError,
    PortfolioRestoreManualRecoveryError,
    PortfolioRestoreNameTooLongError,
    PortfolioRestorePublicationError,
    PortfolioRestorePublicationResult,
    PortfolioRestoreTarget,
)
from core.database import CURRENT_SCHEMA_VERSION, DatabaseManager
from core.encrypted_backup_package import (
    BackupPackageCorruptedError,
    BackupPackageCredentialError,
    BackupPackageIncompatibleError,
    EncryptedBackupPackageService,
)
from core.ports import PortfolioBackupIdentityError, PortfolioBackupIntegrityError
from core.sqlite_backup import validate_portfolio_snapshot
from services.local_backup_service import BACKUP_FORMAT_VERSION

OWNER_ONLY_DIRECTORY_MODE = 0o700
OWNER_ONLY_FILE_MODE = 0o600
logger = logging.getLogger(__name__)


class BackupRestoreError(RuntimeError):
    """Safe user-facing failure raised by the local restore workflow."""


class BackupRestoreCredentialError(BackupRestoreError):
    """The password or recovery key does not open the selected package."""


class BackupRestoreCorruptedError(BackupRestoreError):
    """The package or one of its authenticated artifacts is invalid."""


class BackupRestoreIncompatibleError(BackupRestoreError):
    """The package or portfolio schema is not supported by this app."""


class BackupRestoreConflictError(BackupRestoreError):
    """The confirmed package or local destination changed after preview."""


@dataclass(frozen=True)
class RestoreCredential:
    """One non-persistent credential used to open an encrypted backup package."""

    kind: str
    secret: str | bytes = field(repr=False)

    @classmethod
    def with_password(cls, password: str) -> "RestoreCredential":
        return cls("password", password)

    @classmethod
    def with_recovery_key(cls, content: bytes) -> "RestoreCredential":
        return cls("recovery_key", content)


@dataclass(frozen=True)
class RestorePortfolioPreview:
    package_sha256: str
    backup_id: str
    portfolio_id: str
    display_name: str
    schema_version: int
    target: PortfolioRestoreTarget
    backup_is_older_than_local: bool


@dataclass(frozen=True)
class RestorePreview:
    package_sha256: str
    backup_id: str
    created_at_utc: str
    app_version: str
    installation_id: str
    portfolios: tuple[RestorePortfolioPreview, ...]
    cleanup_warning_path: Path | None = None


@dataclass(frozen=True)
class _ValidatedPortfolio:
    portfolio_id: str
    display_name: str
    schema_version: int
    database: Path


@dataclass(frozen=True)
class _ValidatedPackage:
    package_sha256: str
    backup_id: str
    created_at_utc: str
    created_at: datetime
    app_version: str
    installation_id: str
    portfolios: tuple[_ValidatedPortfolio, ...]


class LocalRestoreService:
    """Inspect and safely restore authenticated local backup packages."""

    def __init__(self, application_paths: ApplicationPaths):
        self._paths = application_paths
        self._packages = EncryptedBackupPackageService()

    def list_local_packages(self) -> tuple[str, ...]:
        """List local encrypted packages without opening or trusting their contents."""
        try:
            packages = []
            for path in self._paths.local_backups_dir.iterdir():
                if path.name.startswith(".") or path.suffix.lower() != ".rpb":
                    continue
                if path.is_symlink() or not path.is_file():
                    continue
                packages.append((path.stat().st_mtime_ns, path.name))
        except FileNotFoundError:
            return ()
        except OSError as error:
            raise BackupRestoreError(
                "Não foi possível listar os backups locais. Verifique a pasta de backups."
            ) from error
        return tuple(name for _modified, name in sorted(packages, reverse=True))

    def read_local_package(self, filename: str) -> bytes:
        """Read only a regular package file directly inside the local backup directory."""
        if (
            not isinstance(filename, str)
            or not filename.lower().endswith(".rpb")
            or filename.startswith(".")
            or "/" in filename
            or "\\" in filename
        ):
            raise BackupRestoreError("Selecione um pacote local válido.")
        package_file = self._paths.local_backups_dir / filename
        try:
            descriptor = os.open(
                package_file,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
            )
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode) or package_file.is_symlink():
                    raise BackupRestoreError("Selecione um pacote local válido.")
                return source.read()
        except OSError as error:
            raise BackupRestoreError(
                "Não foi possível ler o backup local selecionado. Verifique se ele ainda existe."
            ) from error

    def inspect_package(
        self,
        package_content: bytes,
        credential: RestoreCredential,
    ) -> RestorePreview:
        """Validate an encrypted package and return only safe authenticated metadata."""
        logger.info("restore.inspect.started")
        cleanup_failures: list[Path] = []
        try:
            with self._open_validated_package(
                package_content, credential, cleanup_failures=cleanup_failures
            ) as package:
                preview = self._build_preview(package)
            if cleanup_failures:
                preview = replace(preview, cleanup_warning_path=cleanup_failures[0])
            logger.info("restore.inspect.completed portfolios=%s", len(preview.portfolios))
            return preview
        except BackupRestoreError as error:
            logger.warning("restore.inspect.failed error_type=%s", type(error).__name__)
            if cleanup_failures:
                raise type(error)(
                    self._with_cleanup_warning(str(error), cleanup_failures)
                ) from error
            raise

    def choose_new_destination(
        self, selected: RestorePortfolioPreview, requested_name: str
    ) -> RestorePortfolioPreview:
        """Pin a user-chosen local name for a portfolio identity not yet installed."""
        if selected.target.replaces_existing:
            raise BackupRestoreError("Esta carteira já existe e será restaurada no destino atual.")
        try:
            target = self._paths.plan_portfolio_restore(selected.portfolio_id, requested_name)
        except PortfolioRestoreNameTooLongError as error:
            raise BackupRestoreError(
                "O nome gera arquivos longos demais para este sistema. Escolha um nome mais curto."
            ) from error
        except ValueError as error:
            raise BackupRestoreError(
                "Informe um nome de carteira de até 60 caracteres, usando letras, números, "
                "espaços, hífen ou sublinhado."
            ) from error
        except PortfolioRestoreConflictError as error:
            raise BackupRestoreError(
                "Esse nome já está em uso ou a carteira local mudou. Escolha outro nome."
            ) from error
        return replace(selected, target=target)

    def restore_package(
        self,
        package_content: bytes,
        credential: RestoreCredential,
        selected: RestorePortfolioPreview,
    ) -> PortfolioRestorePublicationResult:
        """Revalidate and publish exactly the portfolio confirmed in a prior preview."""
        logger.info("restore.publish.started")
        cleanup_failures: list[Path] = []
        try:
            with self._open_validated_package(
                package_content, credential, cleanup_failures=cleanup_failures
            ) as package:
                preview = self._build_preview(package)
                current = next(
                    (
                        portfolio
                        for portfolio in preview.portfolios
                        if portfolio.portfolio_id == selected.portfolio_id
                    ),
                    None,
                )
                if current is not None and selected.target.requested_name is not None:
                    try:
                        current = self.choose_new_destination(
                            current, selected.target.requested_name
                        )
                    except BackupRestoreError as error:
                        raise BackupRestoreConflictError(
                            "O destino da carteira mudou desde a confirmação. "
                            "Revise o nome e confirme novamente."
                        ) from error
                if current is None or not self._matches_confirmed_portfolio(current, selected):
                    raise BackupRestoreConflictError(
                        "O pacote ou a carteira local mudou desde a confirmação. "
                        "Valide o backup novamente."
                    )
                artifact = next(
                    item
                    for item in package.portfolios
                    if item.portfolio_id == selected.portfolio_id
                )
                self._migrate_compatible_snapshot(artifact)
                result = self._paths.publish_portfolio_restore(
                    artifact.database,
                    current.target,
                )
            if cleanup_failures:
                result = replace(result, cleanup_warning_path=cleanup_failures[0])
            logger.info("restore.publish.completed")
            return result
        except BackupRestoreError as error:
            logger.warning("restore.publish.failed error_type=%s", type(error).__name__)
            if cleanup_failures:
                raise type(error)(
                    self._with_cleanup_warning(str(error), cleanup_failures)
                ) from error
            raise
        except PortfolioRestoreConflictError as error:
            raise BackupRestoreConflictError(
                self._with_cleanup_warning(
                    "A carteira local mudou desde a confirmação. Valide o backup novamente.",
                    cleanup_failures,
                )
            ) from error
        except PortfolioRestoreBusyError as error:
            raise BackupRestoreError(
                self._with_cleanup_warning(
                    "A carteira está em uso por outra sessão. "
                    "Feche as operações ativas e tente novamente.",
                    cleanup_failures,
                )
            ) from error
        except PortfolioRestoreManualRecoveryError as error:
            raise BackupRestoreError(
                self._with_cleanup_warning(
                    f"A restauração falhou e exige recuperação manual a partir de {error.backup_dir}.",
                    cleanup_failures,
                )
            ) from error
        except PortfolioRestorePublicationError as error:
            raise BackupRestoreError(
                self._with_cleanup_warning(
                    "Não foi possível publicar a restauração; a carteira anterior foi preservada.",
                    cleanup_failures,
                )
            ) from error

    @staticmethod
    def _with_cleanup_warning(message: str, cleanup_failures: list[Path]) -> str:
        if not cleanup_failures:
            return message
        return (
            f"{message} A limpeza dos arquivos temporários falhou. "
            f"Feche o aplicativo e remova manualmente {cleanup_failures[0]}."
        )

    @staticmethod
    def _matches_confirmed_portfolio(
        current: RestorePortfolioPreview, selected: RestorePortfolioPreview
    ) -> bool:
        """Ignore informational timestamps while preserving destination and content checks."""
        return (
            current.package_sha256 == selected.package_sha256
            and current.backup_id == selected.backup_id
            and current.portfolio_id == selected.portfolio_id
            and current.display_name == selected.display_name
            and current.schema_version == selected.schema_version
            and current.target.filename == selected.target.filename
            and current.target.expected_generation == selected.target.expected_generation
            and current.target.replaces_existing == selected.target.replaces_existing
            and current.target.state_token == selected.target.state_token
            and current.target.requested_name == selected.target.requested_name
        )

    def _build_preview(self, package: _ValidatedPackage) -> RestorePreview:
        portfolios = []
        for artifact in package.portfolios:
            try:
                target = self._paths.plan_portfolio_restore(artifact.portfolio_id)
            except PortfolioRestoreConflictError as error:
                raise BackupRestoreConflictError(
                    "A identidade da carteira é ambígua na instalação local."
                ) from error
            local_modified = self._parse_utc(target.last_modified_at_utc)
            portfolios.append(
                RestorePortfolioPreview(
                    package_sha256=package.package_sha256,
                    backup_id=package.backup_id,
                    portfolio_id=artifact.portfolio_id,
                    display_name=artifact.display_name,
                    schema_version=artifact.schema_version,
                    target=target,
                    backup_is_older_than_local=(
                        local_modified is not None and package.created_at < local_modified
                    ),
                )
            )
        return RestorePreview(
            package_sha256=package.package_sha256,
            backup_id=package.backup_id,
            created_at_utc=package.created_at_utc,
            app_version=package.app_version,
            installation_id=package.installation_id,
            portfolios=tuple(portfolios),
        )

    @contextmanager
    def _open_validated_package(
        self,
        package_content: bytes,
        credential: RestoreCredential,
        cleanup_failures: list[Path] | None = None,
    ):
        if not isinstance(package_content, bytes) or not package_content:
            raise BackupRestoreCorruptedError("Selecione um pacote de backup válido.")
        restore_root = self._paths.backups_dir / f".restore-{uuid.uuid4().hex}"
        package_file = restore_root / "backup.rpb"
        extracted = restore_root / "extracted"
        try:
            restore_root.mkdir(parents=True, exist_ok=False, mode=OWNER_ONLY_DIRECTORY_MODE)
            if os.name == "posix":
                restore_root.chmod(OWNER_ONLY_DIRECTORY_MODE)
            descriptor = os.open(
                package_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                OWNER_ONLY_FILE_MODE,
            )
            try:
                with os.fdopen(descriptor, "wb") as destination:
                    descriptor = None
                    destination.write(package_content)
                    destination.flush()
                    os.fsync(destination.fileno())
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            opened = self._extract(package_file, extracted, credential)
            yield self._validate_extracted_package(
                extracted,
                hashlib.sha256(package_content).hexdigest(),
                opened.backup_id,
            )
        except BackupRestoreError:
            raise
        except BackupPackageCredentialError as error:
            raise BackupRestoreCredentialError(
                "A senha ou a chave de recuperação não abre este backup."
            ) from error
        except BackupPackageIncompatibleError as error:
            raise BackupRestoreIncompatibleError(
                "A versão ou a criptografia deste backup não é compatível."
            ) from error
        except BackupPackageCorruptedError as error:
            raise BackupRestoreCorruptedError(
                "O pacote de backup está corrompido ou incompleto."
            ) from error
        except (OSError, sqlite3.DatabaseError, UnicodeError, ValueError) as error:
            raise BackupRestoreCorruptedError(
                "Não foi possível validar o conteúdo do backup."
            ) from error
        finally:
            if restore_root.exists():
                try:
                    shutil.rmtree(restore_root)
                except OSError:
                    logger.warning(
                        "restore.cleanup.failed directory=%s", restore_root, exc_info=True
                    )
                    if cleanup_failures is not None:
                        cleanup_failures.append(restore_root)

    def _extract(
        self,
        package_file: Path,
        extracted: Path,
        credential: RestoreCredential,
    ):
        if credential.kind == "password" and isinstance(credential.secret, str):
            if len(credential.secret) < 4:
                raise BackupRestoreCredentialError(
                    "A senha do backup deve ter pelo menos 4 caracteres."
                )
            return self._packages.extract_with_password(
                package_file,
                extracted,
                credential.secret,
            )
        if credential.kind == "recovery_key" and isinstance(credential.secret, bytes):
            return self._packages.extract_with_recovery_key_file(
                package_file,
                extracted,
                credential.secret,
            )
        raise BackupRestoreCredentialError("Informe uma senha ou chave de recuperação válida.")

    def _validate_extracted_package(
        self,
        extracted: Path,
        package_sha256: str,
        authenticated_backup_id: str,
    ) -> _ValidatedPackage:
        manifest = self._read_json(extracted / "manifest.json")
        backup_id = self._canonical_uuid(manifest.get("backup_id"))
        if backup_id != authenticated_backup_id:
            raise BackupRestoreCorruptedError("A identidade autenticada do backup não confere.")
        if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
            raise BackupRestoreIncompatibleError(
                "A versão interna deste conjunto de backup não é compatível."
            )
        if manifest.get("encryption_state") != "encrypted":
            raise BackupRestoreCorruptedError("O estado de criptografia do backup é inválido.")
        created_at_utc = manifest.get("created_at_utc")
        created_at = self._require_utc(created_at_utc)
        app_version = self._non_empty_string(manifest.get("app_version"))
        installation_id = self._canonical_uuid(manifest.get("installation_id"))
        entries = manifest.get("portfolios")
        portfolio_count = manifest.get("portfolio_count")
        if (
            not isinstance(entries, list)
            or not entries
            or isinstance(portfolio_count, bool)
            or not isinstance(portfolio_count, int)
            or portfolio_count != len(entries)
        ):
            raise BackupRestoreCorruptedError("A lista de carteiras do backup é inválida.")

        portfolios = []
        seen_ids = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise BackupRestoreCorruptedError("Uma entrada de carteira é inválida.")
            portfolio_id = self._canonical_uuid(entry.get("portfolio_id"))
            if portfolio_id in seen_ids:
                raise BackupRestoreCorruptedError(
                    "O backup contém identidades de carteira duplicadas."
                )
            seen_ids.add(portfolio_id)
            expected_relative_path = f"carteiras/{portfolio_id}"
            if entry.get("relative_path") != expected_relative_path:
                raise BackupRestoreCorruptedError("O caminho interno de uma carteira é inválido.")
            portfolio_directory = extracted / "carteiras" / portfolio_id
            database = portfolio_directory / "backup.sqlite3"
            metadata = self._read_json(portfolio_directory / "metadata.json")
            checksum = self._sha256(database)
            schema_version = entry.get("schema_version")
            display_name = self._non_empty_string(entry.get("display_name"))
            if (
                isinstance(schema_version, bool)
                or not isinstance(schema_version, int)
                or schema_version < 0
                or entry.get("sha256") != checksum
                or metadata.get("sha256") != checksum
                or metadata.get("format_version") != BACKUP_FORMAT_VERSION
                or metadata.get("backup_id") != backup_id
                or metadata.get("portfolio_id") != portfolio_id
                or metadata.get("display_name") != display_name
                or metadata.get("created_at_utc") != created_at_utc
                or metadata.get("app_version") != app_version
                or metadata.get("schema_version") != schema_version
                or metadata.get("installation_id") != installation_id
                or metadata.get("encryption_state") != "encrypted"
            ):
                raise BackupRestoreCorruptedError(
                    "Os metadados ou o hash de uma carteira não conferem."
                )
            try:
                identity = validate_portfolio_snapshot(database)
            except (PortfolioBackupIdentityError, PortfolioBackupIntegrityError) as error:
                raise BackupRestoreCorruptedError(
                    "Uma carteira do backup não é um SQLite íntegro e identificado."
                ) from error
            if identity.portfolio_id != portfolio_id or identity.schema_version != schema_version:
                raise BackupRestoreCorruptedError(
                    "A identidade ou o schema da carteira não confere com os metadados."
                )
            if schema_version > CURRENT_SCHEMA_VERSION:
                raise BackupRestoreIncompatibleError(
                    "O backup usa um schema mais novo que esta versão do aplicativo."
                )
            portfolios.append(
                _ValidatedPortfolio(
                    portfolio_id=portfolio_id,
                    display_name=display_name,
                    schema_version=schema_version,
                    database=database,
                )
            )
        return _ValidatedPackage(
            package_sha256=package_sha256,
            backup_id=backup_id,
            created_at_utc=created_at_utc,
            created_at=created_at,
            app_version=app_version,
            installation_id=installation_id,
            portfolios=tuple(portfolios),
        )

    def _migrate_compatible_snapshot(self, artifact: _ValidatedPortfolio) -> None:
        try:
            if artifact.schema_version < CURRENT_SCHEMA_VERSION:
                DatabaseManager(artifact.database).init_personal_db()
            identity = validate_portfolio_snapshot(artifact.database)
        except (
            OSError,
            sqlite3.DatabaseError,
            PortfolioBackupIdentityError,
            PortfolioBackupIntegrityError,
        ) as error:
            raise BackupRestoreCorruptedError(
                "A carteira deixou de ser íntegra durante a preparação."
            ) from error
        if (
            identity.portfolio_id != artifact.portfolio_id
            or identity.schema_version != CURRENT_SCHEMA_VERSION
        ):
            raise BackupRestoreIncompatibleError(
                "Não foi possível atualizar o schema antigo antes da restauração."
            )

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupRestoreCorruptedError("Um metadado do backup não pode ser lido.") from error
        if not isinstance(payload, dict):
            raise BackupRestoreCorruptedError("Um metadado do backup possui formato inválido.")
        return payload

    @staticmethod
    def _sha256(path: Path) -> str:
        checksum = hashlib.sha256()
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    checksum.update(chunk)
        except OSError as error:
            raise BackupRestoreCorruptedError(
                "Um arquivo da carteira não pode ser lido."
            ) from error
        return checksum.hexdigest()

    @staticmethod
    def _canonical_uuid(value) -> str:
        try:
            parsed = uuid.UUID(value)
        except (AttributeError, TypeError, ValueError) as error:
            raise BackupRestoreCorruptedError("Um identificador do backup é inválido.") from error
        if str(parsed) != value:
            raise BackupRestoreCorruptedError("Um identificador do backup é inválido.")
        return value

    @staticmethod
    def _non_empty_string(value) -> str:
        if not isinstance(value, str) or not value.strip():
            raise BackupRestoreCorruptedError("Um texto obrigatório do backup é inválido.")
        return value

    @staticmethod
    def _require_utc(value) -> datetime:
        parsed = LocalRestoreService._parse_utc(value)
        if parsed is None or not isinstance(value, str) or not value.endswith("Z"):
            raise BackupRestoreCorruptedError("A data UTC do backup é inválida.")
        return parsed

    @staticmethod
    def _parse_utc(value) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            return None
        return parsed

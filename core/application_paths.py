import csv
import hashlib
import io
import os
import re
import shutil
import socket
import sqlite3
import sys
import tempfile
import time
import uuid
from collections.abc import Iterable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from platformdirs.unix import Unix
from platformdirs.windows import Windows

APP_NAME = "RendaPerene"
DEFAULT_PORTFOLIO = "portfolio.db"
DEMO_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60
FILE_LOCK_TIMEOUT_SECONDS = 5
FILE_LOCK_STALE_SECONDS = 300


@contextmanager
def _exclusive_file_lock(lock: Path):
    lock = Path(lock)
    descriptor = None
    owner_token = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
    deadline = time.monotonic() + FILE_LOCK_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, owner_token.encode("ascii"))
                while True:
                    readers = tuple(lock.parent.glob(f"{lock.name}.reader.*"))
                    if not readers:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for {lock.name} readers.")
                    for reader in readers:
                        try:
                            if (
                                time.time() - reader.stat().st_mtime > FILE_LOCK_STALE_SECONDS
                                and not _lock_owner_is_alive(reader)
                            ):
                                reader.unlink()
                        except FileNotFoundError:
                            continue
                    time.sleep(0.01)
                break
            except FileExistsError:
                try:
                    lock_age = time.time() - lock.stat().st_mtime
                    observed_owner = lock.read_text(encoding="ascii")
                    if (
                        lock_age > FILE_LOCK_STALE_SECONDS
                        and not _lock_owner_is_alive(lock)
                        and lock.exists()
                        and lock.read_text(encoding="ascii") == observed_owner
                    ):
                        lock.unlink()
                        continue
                except FileNotFoundError:
                    continue
                time.sleep(0.01)
        if descriptor is None:
            raise TimeoutError(f"Timed out waiting for {lock.name}.")
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
            try:
                if lock.read_text(encoding="ascii") == owner_token:
                    lock.unlink()
            except (FileNotFoundError, UnicodeError):
                pass


def _lock_owner_is_alive(lock: Path) -> bool:
    """Return whether a lock's recorded local-process owner is still running."""
    try:
        host, pid_text, _token = lock.read_text(encoding="ascii").split(":", 2)
        if host != socket.gethostname():
            return True
        pid = int(pid_text)
        if sys.platform.startswith("win"):
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(pid, 0)
    except (OSError, UnicodeError, ValueError):
        return False
    return True


@contextmanager
def portfolio_database_lock(database: Path):
    """Serialize database connections and migration publication for one portfolio."""
    database = Path(database)
    lock = database.with_name(f".{database.name}.lock")
    with _exclusive_file_lock(lock):
        yield


@contextmanager
def portfolio_database_reader_lock(database: Path):
    """Register a reader so migration publication waits for open SQLite handles."""
    database = Path(database)
    lock = database.with_name(f".{database.name}.lock")
    reader = database.with_name(f"{lock.name}.reader.{uuid.uuid4().hex}")
    deadline = time.monotonic() + FILE_LOCK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if lock.exists():
            try:
                if (
                    time.time() - lock.stat().st_mtime > FILE_LOCK_STALE_SECONDS
                    and not _lock_owner_is_alive(lock)
                ):
                    observed_owner = lock.read_text(encoding="ascii")
                    if lock.exists() and lock.read_text(encoding="ascii") == observed_owner:
                        lock.unlink()
                        continue
            except FileNotFoundError:
                continue
            time.sleep(0.01)
            continue
        try:
            descriptor = os.open(reader, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            owner_token = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"
            os.write(descriptor, owner_token.encode("ascii"))
            os.close(descriptor)
            if lock.exists():
                reader.unlink(missing_ok=True)
                continue
            break
        except FileExistsError:
            continue
    else:
        raise TimeoutError(f"Timed out waiting for {lock.name}.")
    try:
        yield
    finally:
        with suppress(FileNotFoundError):
            reader.unlink()


@dataclass(frozen=True)
class PortfolioInventory:
    """Classifies portfolio files before the application offers them for selection."""

    valid: tuple[Path, ...]
    invalid: tuple[Path, ...]


@dataclass(frozen=True)
class MigrationResult:
    """Describes the observable outcome of one legacy database migration."""

    source: Path
    destination: Path
    backup: Path | None
    migrated: bool
    message: str


@dataclass(frozen=True)
class ApplicationPaths:
    """Resolves application resources and owns writable-data preparation and migration."""

    resource_root: Path
    data_root: Path
    legacy_root: Path

    @classmethod
    def discover(cls, system: str | None = None) -> "ApplicationPaths":
        """Build runtime paths for the current packaged or source execution."""
        platform_name = system or sys.platform
        directory_type = Windows if platform_name.lower().startswith("win") else Unix
        platform_directory = directory_type(APP_NAME, appauthor=False)

        bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        legacy_root = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else bundled_root
        )
        return cls(
            resource_root=bundled_root,
            data_root=Path(platform_directory.user_data_path),
            legacy_root=legacy_root,
        )

    @property
    def database_dir(self) -> Path:
        return self.data_root / "database"

    @property
    def catalog_file(self) -> Path:
        return self.data_root / "catalog" / "assets.csv"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_root / "backups"

    def bundled_resource(self, relative_path: str | Path) -> Path:
        """Resolve a resource while refusing paths that escape the application bundle."""
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Bundled resource paths must be relative and cannot contain '..'.")
        return self.resource_root / relative

    def for_demo_session(self, session_id: str) -> "ApplicationPaths":
        """Return isolated, disposable writable paths for one shared-host demo session."""
        safe_session_id = "".join(char for char in session_id if char.isalnum() or char in "-_")
        if not safe_session_id:
            raise ValueError("A demo session identifier is required.")
        demo_root = Path(tempfile.gettempdir()) / APP_NAME / "demo" / safe_session_id
        return ApplicationPaths(self.resource_root, demo_root, self.legacy_root)

    def cleanup_demo_sessions(
        self,
        active_session_id: str,
        max_age_seconds: int = DEMO_SESSION_MAX_AGE_SECONDS,
    ) -> None:
        """Refresh the active demo session and remove abandoned session directories."""
        active_paths = self.for_demo_session(active_session_id)
        sessions_root = active_paths.data_root.parent
        now = time.time()
        if active_paths.data_root.exists():
            with suppress(OSError):
                os.utime(active_paths.data_root, (now, now))
        if not sessions_root.is_dir():
            return

        try:
            session_roots = tuple(sessions_root.iterdir())
        except OSError:
            return
        for session_root in session_roots:
            if not session_root.is_dir() or session_root == active_paths.data_root:
                continue
            try:
                if now - session_root.stat().st_mtime > max_age_seconds:
                    shutil.rmtree(session_root)
            except OSError:
                continue

    def prepare(self, default_database_source: Path | None = None) -> bool:
        """Create writable directories and seed catalog or demo data when absent."""
        recovered_database = False
        for directory in (
            self.database_dir,
            self.catalog_file.parent,
            self.logs_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        bundled_catalog = self.bundled_resource("assets.csv")
        current_catalog_paths = {bundled_catalog.resolve(), self.catalog_file.resolve()}
        catalog_sources = []
        for legacy_root in reversed(self._legacy_roots()):
            legacy_catalog = legacy_root / "assets.csv"
            if legacy_catalog.resolve() not in current_catalog_paths and self._is_valid_catalog(
                legacy_catalog
            ):
                catalog_sources.append(legacy_catalog)

        if self._is_valid_catalog(bundled_catalog):
            catalog_sources.append(bundled_catalog)
        if catalog_sources:
            self._merge_catalogs(catalog_sources, self.catalog_file)

        if default_database_source is not None:
            destination = self.portfolio_database(DEFAULT_PORTFOLIO)
            if not self.is_valid_sqlite(default_database_source):
                raise ValueError("The default portfolio database is not a valid SQLite file.")
            if destination.exists() and not self.is_valid_sqlite(destination):
                self._replace_with_validated_copy(default_database_source, destination)
                self._remove_sqlite_sidecars(destination)
                recovered_database = True
            elif not destination.exists():
                self._safe_copy(default_database_source, destination, validate_sqlite=True)
                recovered_database = True
        return recovered_database

    def portfolio_database(self, filename: str) -> Path:
        """Resolve a portfolio filename without allowing directory traversal or unrelated files."""
        if (
            Path(filename).name != filename
            or not filename.startswith("portfolio")
            or not filename.endswith(".db")
        ):
            raise ValueError("Portfolio databases must use a 'portfolio*.db' filename.")
        return self.database_dir / filename

    @staticmethod
    def choose_portfolio(preferred: str, available: list[str]) -> str:
        """Choose the preferred, principal, or first available valid portfolio."""
        if not available:
            raise ValueError("At least one valid portfolio must be available.")
        if preferred in available:
            return preferred
        if DEFAULT_PORTFOLIO in available:
            return DEFAULT_PORTFOLIO
        return available[0]

    def inspect_portfolios(self) -> PortfolioInventory:
        """Return valid and invalid portfolio databases from the writable data directory."""
        candidates = sorted(self.database_dir.glob("portfolio*.db"))
        valid = tuple(path for path in candidates if self.is_valid_sqlite(path))
        invalid = tuple(path for path in candidates if path not in valid)
        return PortfolioInventory(valid=valid, invalid=invalid)

    def portfolio_options(self, inventory: PortfolioInventory) -> tuple[str, ...]:
        """Return valid portfolio names or a safe new database name for startup recovery."""
        available = [path.name for path in inventory.valid]
        if available:
            return tuple(sorted(set(available)))

        default_database = self.portfolio_database(DEFAULT_PORTFOLIO)
        if not default_database.exists():
            return (DEFAULT_PORTFOLIO,)

        recovery_index = 1
        while True:
            suffix = "" if recovery_index == 1 else f"_{recovery_index}"
            recovery_name = f"portfolio_recovery{suffix}.db"
            if not self.portfolio_database(recovery_name).exists():
                return (recovery_name,)
            recovery_index += 1

    def legacy_databases(self) -> tuple[Path, ...]:
        """Discover legacy databases beside this executable or in an earlier release."""
        databases_by_name: dict[str, list[Path]] = {}
        for legacy_root in self._legacy_roots():
            legacy_database_dir = legacy_root / "database"
            if legacy_database_dir.resolve() == self.database_dir.resolve():
                continue
            for path in sorted(legacy_database_dir.glob("portfolio*.db")):
                if "demo" not in path.name:
                    databases_by_name.setdefault(path.name, []).append(path)

        selected_databases = []
        for name in sorted(databases_by_name):
            sources = databases_by_name[name]
            selected_databases.append(
                next((source for source in sources if self.is_valid_sqlite(source)), sources[0])
            )
        return tuple(selected_databases)

    def _legacy_roots(self) -> tuple[Path, ...]:
        """Return the current install and versioned sibling installs, newest first."""
        current_root = self.legacy_root.resolve()
        release_prefix = f"{APP_NAME}-v".casefold()
        if not current_root.name.casefold().startswith(release_prefix):
            return (current_root,)

        try:
            siblings = [
                path.resolve()
                for path in current_root.parent.iterdir()
                if path.is_dir()
                and path.resolve() != current_root
                and path.name.casefold().startswith(release_prefix)
                and self._release_version(path)
            ]
        except OSError:
            return (current_root,)

        current_version = self._release_version(current_root)
        if current_version:
            siblings = [path for path in siblings if self._release_version(path) < current_version]
        siblings.sort(key=self._release_version, reverse=True)
        return (current_root, *siblings)

    @staticmethod
    def _release_version(path: Path) -> tuple[int, ...]:
        """Extract numeric version components from a packaged release directory."""
        return tuple(int(component) for component in re.findall(r"\d+", path.name))

    def migration_candidates(self) -> tuple[Path, ...]:
        """Return legacy databases that can be imported without replacing user data."""
        candidates = []
        for source in self.legacy_databases():
            destination = self.portfolio_database(source.name)
            backup = self.backups_dir / "legacy-import" / source.name
            marker = backup.with_suffix(backup.suffix + ".done")
            if (
                destination.exists()
                and backup.exists()
                and marker.exists()
                and self._completion_marker_matches(marker, source, backup)
            ):
                continue
            candidates.append(source)
        return tuple(candidates)

    def migrate_legacy_database(self, source: Path) -> MigrationResult:
        """Copy one legacy database into writable storage with validation and a backup."""
        source = Path(source)
        allowed_sources = {path.resolve() for path in self.legacy_databases()}
        if source.resolve() not in allowed_sources:
            raise ValueError("The migration source is not a discovered legacy portfolio database.")

        destination = self.portfolio_database(source.name)
        backup = self.backups_dir / "legacy-import" / source.name
        completion_marker = backup.with_suffix(backup.suffix + ".done")

        if not self.is_valid_sqlite(source):
            return MigrationResult(
                source,
                destination,
                None,
                False,
                "O arquivo de origem não é um banco SQLite válido.",
            )

        if (
            destination.exists()
            and backup.exists()
            and completion_marker.exists()
            and self._completion_marker_matches(completion_marker, source, backup)
        ):
            return MigrationResult(
                source,
                destination,
                backup,
                False,
                "A carteira já foi importada anteriormente.",
            )

        if destination.exists():
            if self.is_valid_sqlite(destination) and self._same_sqlite_contents(
                source, destination
            ):
                if not backup.exists():
                    try:
                        self._safe_copy(source, backup, validate_sqlite=True)
                    except (OSError, sqlite3.DatabaseError, ValueError):
                        return MigrationResult(
                            source,
                            destination,
                            None,
                            False,
                            "A carteira já existe, mas não foi possível criar o backup.",
                        )
                try:
                    completion_marker.parent.mkdir(parents=True, exist_ok=True)
                    completion_marker.write_text(
                        f"{self._sqlite_content_digest(source)}\n", encoding="ascii"
                    )
                except (OSError, sqlite3.DatabaseError):
                    return MigrationResult(
                        source,
                        destination,
                        backup,
                        False,
                        "A carteira já existe, mas não foi possível registrar a importação.",
                    )
                return MigrationResult(
                    source,
                    destination,
                    backup,
                    False,
                    "A carteira já foi importada anteriormente.",
                )
            if not self._is_pristine_database(destination):
                return MigrationResult(
                    source,
                    destination,
                    backup if backup.exists() else None,
                    False,
                    "Já existe uma carteira diferente com esse nome; nenhum arquivo foi sobrescrito.",
                )

        try:
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists() and not self._same_sqlite_contents(source, backup):
                return MigrationResult(
                    source,
                    destination,
                    backup,
                    False,
                    "Já existe um backup diferente com esse nome; a importação foi cancelada.",
                )
            if not backup.exists():
                self._safe_copy(source, backup, validate_sqlite=True)

            with portfolio_database_lock(destination):
                if destination.exists():
                    if not self._is_pristine_database(destination):
                        return MigrationResult(
                            source,
                            destination,
                            backup,
                            False,
                            "A carteira de destino mudou durante a importação; nenhum dado foi substituído.",
                        )
                    self._remove_sqlite_sidecars(destination)
                    self._replace_with_validated_copy(backup, destination)
                else:
                    self._remove_sqlite_sidecars(destination)
                    self._safe_copy(backup, destination, validate_sqlite=True)
                completion_marker.write_text(
                    f"{self._sqlite_content_digest(backup)}\n", encoding="ascii"
                )
        except (OSError, sqlite3.DatabaseError, ValueError):
            return MigrationResult(
                source,
                destination,
                backup,
                False,
                "Não foi possível copiar a carteira. Verifique as permissões de armazenamento e tente novamente.",
            )

        return MigrationResult(
            source,
            destination,
            backup,
            True,
            "Carteira importada com sucesso e backup preservado.",
        )

    @classmethod
    def _completion_marker_matches(cls, marker: Path, source: Path, backup: Path) -> bool:
        try:
            marker_value = marker.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return False
        if marker_value == "completed":
            return cls._same_sqlite_contents(source, backup)
        try:
            source_digest = cls._sqlite_content_digest(source)
            return (
                marker_value == source_digest
                and cls._sqlite_content_digest(backup) == source_digest
            )
        except (OSError, sqlite3.DatabaseError):
            return False

    @staticmethod
    def is_valid_sqlite(path: Path) -> bool:
        """Check SQLite integrity without creating or modifying the supplied file."""
        path = Path(path)
        try:
            metadata = path.stat()
        except OSError:
            return False
        if not path.is_file() or metadata.st_size == 0:
            return False
        return ApplicationPaths._is_valid_sqlite_snapshot(
            str(path.resolve()),
            metadata.st_size,
            metadata.st_mtime_ns,
            ApplicationPaths._sqlite_sidecar_signature(path),
        )

    @staticmethod
    def _sqlite_sidecar_signature(path: Path) -> tuple[tuple[int, int] | None, ...]:
        signature = []
        for suffix in ("-wal", "-shm"):
            try:
                metadata = Path(f"{path}{suffix}").stat()
                signature.append((metadata.st_size, metadata.st_mtime_ns))
            except OSError:
                signature.append(None)
        return tuple(signature)

    @staticmethod
    @lru_cache(maxsize=256)
    def _is_valid_sqlite_snapshot(
        path: str,
        _size: int,
        _mtime_ns: int,
        _sidecar_signature: tuple[tuple[int, int] | None, ...],
    ) -> bool:
        """Cache SQLite integrity for one immutable file metadata snapshot."""
        try:
            connection = sqlite3.connect(f"{Path(path).as_uri()}?mode=ro", uri=True)
            try:
                return connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError):
            return False

    @classmethod
    def _same_sqlite_contents(cls, first: Path, second: Path) -> bool:
        """Compare SQLite databases by committed logical content, not file layout."""
        try:
            return cls._sqlite_content_digest(first) == cls._sqlite_content_digest(second)
        except (OSError, sqlite3.DatabaseError):
            return False

    @staticmethod
    def _sqlite_content_digest(path: Path) -> str:
        path = Path(path)
        metadata = path.stat()
        return ApplicationPaths._sqlite_content_digest_snapshot(
            str(path.resolve()),
            metadata.st_size,
            metadata.st_mtime_ns,
            ApplicationPaths._sqlite_sidecar_signature(path),
        )

    @staticmethod
    @lru_cache(maxsize=256)
    def _sqlite_content_digest_snapshot(
        path: str,
        _size: int,
        _mtime_ns: int,
        _sidecar_signature: tuple[tuple[int, int] | None, ...],
    ) -> str:
        database_path = Path(path)
        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        try:
            connection.execute("BEGIN")
            checksum = hashlib.sha256()
            for pragma in ("application_id", "user_version"):
                value = connection.execute(f"PRAGMA {pragma}").fetchone()[0]
                checksum.update(f"{pragma}={value}\0".encode())
            for statement in connection.iterdump():
                checksum.update(statement.encode("utf-8"))
                checksum.update(b"\0")
            return checksum.hexdigest()
        finally:
            connection.close()

    @staticmethod
    def _remove_sqlite_sidecars(path: Path) -> None:
        for suffix in ("-wal", "-shm"):
            with suppress(FileNotFoundError):
                Path(f"{path}{suffix}").unlink()

    @staticmethod
    def _merge_catalog(bundled_catalog: Path, writable_catalog: Path) -> None:
        """Apply bundled metadata updates while retaining user-only fallback rows."""
        ApplicationPaths._merge_catalogs((bundled_catalog,), writable_catalog)

    @staticmethod
    def _merge_catalogs(catalog_sources: Iterable[Path], writable_catalog: Path) -> None:
        """Build all catalog layers in memory and publish the final result once."""
        with ApplicationPaths._catalog_lock(writable_catalog):
            ApplicationPaths._merge_catalogs_locked(catalog_sources, writable_catalog)

    @staticmethod
    def _merge_catalogs_locked(catalog_sources: Iterable[Path], writable_catalog: Path) -> None:
        if ApplicationPaths._is_valid_catalog(writable_catalog):
            fieldnames, rows = ApplicationPaths._read_catalog(writable_catalog)
        else:
            fieldnames, rows = [], []

        merged_source = False
        for catalog_source in catalog_sources:
            try:
                source_fields, source_rows = ApplicationPaths._read_catalog(catalog_source)
            except (OSError, UnicodeError, csv.Error, ValueError):
                continue
            merged_source = True
            combined_fields = source_fields + [
                field for field in fieldnames if field not in source_fields
            ]
            source_codes = {row["CÓDIGO"] for row in source_rows}
            retained_rows = [
                row for row in rows if row.get("CÓDIGO") and row["CÓDIGO"] not in source_codes
            ]
            fieldnames = combined_fields
            rows = [*source_rows, *retained_rows]

        if not merged_source:
            return

        text_buffer = io.StringIO(newline="")
        writer = csv.DictWriter(text_buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        merged_contents = text_buffer.getvalue().encode("utf-8-sig")
        if writable_catalog.exists() and writable_catalog.read_bytes() == merged_contents:
            return

        temporary = writable_catalog.with_name(f".{writable_catalog.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(merged_contents)
            os.replace(temporary, writable_catalog)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()

    @staticmethod
    @contextmanager
    def _catalog_lock(catalog: Path):
        catalog = Path(catalog)
        lock = catalog.with_name(f".{catalog.name}.lock")
        with _exclusive_file_lock(lock):
            yield

    @staticmethod
    def _read_catalog(path: Path) -> tuple[list[str], list[dict[str, str]]]:
        with path.open(encoding="utf-8-sig", newline="") as catalog_file:
            reader = csv.DictReader(catalog_file)
            fieldnames = list(reader.fieldnames or [])
            if "CÓDIGO" not in fieldnames:
                raise ValueError("The assets catalog must contain a CÓDIGO column.")
            rows = list(reader)
            if any(None in row for row in rows):
                raise ValueError("The assets catalog contains rows with extra columns.")
            return fieldnames, rows

    @classmethod
    def _is_valid_catalog(cls, path: Path) -> bool:
        try:
            cls._read_catalog(path)
            return True
        except (OSError, UnicodeError, csv.Error, ValueError):
            return False

    @staticmethod
    def _snapshot_sqlite(source: Path, destination: Path) -> None:
        """Create a consistent SQLite snapshot, including committed WAL pages."""
        source_connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(destination)
        try:
            source_connection.backup(destination_connection)
            destination_connection.commit()
        finally:
            destination_connection.close()
            source_connection.close()

    @classmethod
    def _is_pristine_database(cls, path: Path) -> bool:
        """Return whether a database contains only the application's seeded defaults."""
        if not cls.is_valid_sqlite(path):
            return False
        try:
            connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                }
                expected_tables = {
                    "transactions",
                    "dividends",
                    "tracked_market_assets",
                    "dividend_corrections",
                    "planning_configuration",
                    "asset_accumulation_goals",
                    "goal_settings",
                }
                if tables != expected_tables:
                    return False

                user_data_tables = (
                    "transactions",
                    "dividends",
                    "tracked_market_assets",
                    "planning_configuration",
                    "asset_accumulation_goals",
                )
                for table_name in user_data_tables:
                    if connection.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone():
                        return False

                goal_settings = connection.execute(
                    "SELECT id, reinvest_dividends_enabled, share_quantity_enabled "
                    "FROM goal_settings"
                ).fetchall()
                seeded_corrections = connection.execute(
                    "SELECT ticker, year, total_value FROM dividend_corrections "
                    "ORDER BY ticker, year"
                ).fetchall()
                return goal_settings == [(1, 1, 0)] and seeded_corrections == [
                    ("BBAS3", 2023, 2.29),
                    ("BBAS3", 2024, 2.61),
                    ("BBDC3", 2023, 1.54),
                    ("BBDC3", 2024, 1.01),
                ]
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError):
            return False

    @classmethod
    def _safe_copy(cls, source: Path, destination: Path, validate_sqlite: bool) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            if validate_sqlite:
                cls._snapshot_sqlite(source, temporary)
            else:
                shutil.copy2(source, temporary)
            if validate_sqlite and not cls.is_valid_sqlite(temporary):
                raise ValueError("The copied file failed SQLite validation.")
            if destination.exists():
                raise FileExistsError(f"Refusing to overwrite {destination.name}.")
            os.replace(temporary, destination)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()

    @classmethod
    def _replace_with_validated_copy(cls, source: Path, destination: Path) -> None:
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            if not cls.is_valid_sqlite(temporary):
                raise ValueError("The copied file failed SQLite validation.")
            os.replace(temporary, destination)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()

import csv
import hashlib
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from platformdirs.unix import Unix
from platformdirs.windows import Windows

APP_NAME = "RendaPerene"
DEFAULT_PORTFOLIO = "portfolio.db"


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

    def prepare(self, default_database_source: Path | None = None) -> None:
        """Create writable directories and seed catalog or demo data when absent."""
        for directory in (
            self.database_dir,
            self.catalog_file.parent,
            self.logs_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        bundled_catalog = self.bundled_resource("assets.csv")
        if (
            self.catalog_file.exists()
            and not self._is_valid_catalog(self.catalog_file)
            and self._is_valid_catalog(bundled_catalog)
        ):
            self._replace_with_validated_catalog(bundled_catalog, self.catalog_file)

        current_catalog_paths = {bundled_catalog.resolve(), self.catalog_file.resolve()}
        for legacy_root in reversed(self._legacy_roots()):
            legacy_catalog = legacy_root / "assets.csv"
            if legacy_catalog.resolve() not in current_catalog_paths and self._is_valid_catalog(
                legacy_catalog
            ):
                if self.catalog_file.exists():
                    self._merge_catalog(legacy_catalog, self.catalog_file)
                else:
                    self._safe_copy(legacy_catalog, self.catalog_file, validate_sqlite=False)

        if bundled_catalog.is_file():
            if self.catalog_file.exists():
                self._merge_catalog(bundled_catalog, self.catalog_file)
            else:
                self._safe_copy(bundled_catalog, self.catalog_file, validate_sqlite=False)

        if default_database_source is not None:
            destination = self.portfolio_database(DEFAULT_PORTFOLIO)
            if not destination.exists():
                if not self.is_valid_sqlite(default_database_source):
                    raise ValueError("The default portfolio database is not a valid SQLite file.")
                self._safe_copy(default_database_source, destination, validate_sqlite=True)

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
            if destination.exists() and backup.with_suffix(backup.suffix + ".done").exists():
                continue
            destination_is_replaceable = (
                destination.exists()
                and self._is_pristine_database(destination)
                and not self._same_file_contents(source, destination)
            )
            if not destination.exists() or destination_is_replaceable:
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

        if destination.exists() and completion_marker.exists():
            return MigrationResult(
                source,
                destination,
                backup,
                False,
                "A carteira já foi importada anteriormente.",
            )

        if destination.exists():
            if self.is_valid_sqlite(destination) and self._same_file_contents(source, destination):
                if not backup.exists():
                    try:
                        self._safe_copy(source, backup, validate_sqlite=True)
                    except (OSError, sqlite3.DatabaseError, ValueError) as error:
                        return MigrationResult(
                            source,
                            destination,
                            None,
                            False,
                            f"A carteira já existe, mas o backup falhou: {error}",
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
            if backup.exists() and not self._same_file_contents(source, backup):
                return MigrationResult(
                    source,
                    destination,
                    backup,
                    False,
                    "Já existe um backup diferente com esse nome; a importação foi cancelada.",
                )
            if not backup.exists():
                self._safe_copy(source, backup, validate_sqlite=True)

            if destination.exists():
                if not self._is_pristine_database(destination):
                    return MigrationResult(
                        source,
                        destination,
                        backup,
                        False,
                        "A carteira de destino mudou durante a importação; nenhum dado foi substituído.",
                    )
                if not self._is_pristine_database(destination):
                    return MigrationResult(
                        source,
                        destination,
                        backup,
                        False,
                        "A carteira de destino mudou durante a importação; nenhum dado foi substituído.",
                    )
                self._replace_with_validated_copy(backup, destination)
            else:
                self._safe_copy(backup, destination, validate_sqlite=True)
            completion_marker.write_text("completed\n", encoding="ascii")
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            return MigrationResult(
                source,
                destination,
                backup,
                False,
                f"Falha ao copiar a carteira: {error}",
            )

        return MigrationResult(
            source,
            destination,
            backup,
            True,
            "Carteira importada com sucesso e backup preservado.",
        )

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
            str(path.resolve()), metadata.st_size, metadata.st_mtime_ns
        )

    @staticmethod
    @lru_cache(maxsize=256)
    def _is_valid_sqlite_snapshot(path: str, _size: int, _mtime_ns: int) -> bool:
        """Cache SQLite integrity for one immutable file metadata snapshot."""
        try:
            connection = sqlite3.connect(f"{Path(path).as_uri()}?mode=ro", uri=True)
            try:
                return connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            finally:
                connection.close()
        except (OSError, sqlite3.DatabaseError):
            return False

    @staticmethod
    def _same_file_contents(first: Path, second: Path) -> bool:
        if first.stat().st_size != second.stat().st_size:
            return False

        def digest(path: Path) -> str:
            checksum = hashlib.sha256()
            with path.open("rb") as file:
                for chunk in iter(lambda: file.read(1024 * 1024), b""):
                    checksum.update(chunk)
            return checksum.hexdigest()

        return digest(first) == digest(second)

    @staticmethod
    def _merge_catalog(bundled_catalog: Path, writable_catalog: Path) -> None:
        """Apply bundled metadata updates while retaining user-only fallback rows."""
        with ApplicationPaths._catalog_lock(writable_catalog):
            ApplicationPaths._merge_catalog_locked(bundled_catalog, writable_catalog)

    @staticmethod
    def _merge_catalog_locked(bundled_catalog: Path, writable_catalog: Path) -> None:
        bundled_fields, bundled_rows = ApplicationPaths._read_catalog(bundled_catalog)
        writable_fields, writable_rows = ApplicationPaths._read_catalog(writable_catalog)
        fieldnames = bundled_fields + [
            field for field in writable_fields if field not in bundled_fields
        ]
        bundled_codes = {row["CÓDIGO"] for row in bundled_rows}
        user_only_rows = [
            row for row in writable_rows if row.get("CÓDIGO") and row["CÓDIGO"] not in bundled_codes
        ]

        text_buffer = io.StringIO(newline="")
        writer = csv.DictWriter(text_buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows([*bundled_rows, *user_only_rows])
        merged_contents = text_buffer.getvalue().encode("utf-8-sig")
        if writable_catalog.read_bytes() == merged_contents:
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
        descriptor = None
        try:
            for _ in range(500):
                try:
                    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    try:
                        if time.time() - lock.stat().st_mtime > 300:
                            lock.unlink()
                            continue
                    except FileNotFoundError:
                        continue
                    time.sleep(0.01)
            if descriptor is None:
                raise TimeoutError("Timed out waiting for assets catalog lock.")
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
                with suppress(FileNotFoundError):
                    lock.unlink()

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

    @classmethod
    def _replace_with_validated_catalog(cls, source: Path, destination: Path) -> None:
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            if not cls._is_valid_catalog(temporary):
                raise ValueError("The copied file failed assets catalog validation.")
            os.replace(temporary, destination)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()

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

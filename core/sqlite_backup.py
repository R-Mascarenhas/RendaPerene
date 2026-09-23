import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.application_paths import ApplicationPaths
from core.database import CURRENT_SCHEMA_VERSION, DatabaseManager
from core.ports import (
    PortfolioBackupIdentityError,
    PortfolioBackupIntegrityError,
    PortfolioBackupSelectionError,
    PortfolioBackupSourceError,
    PortfolioBackupSourcePort,
    PortfolioBackupUnavailableError,
    PortfolioSnapshotIdentity,
)

DEFAULT_BACKUP_TIMEOUT_SECONDS = 60.0
# Bound each busy backup step so the progress callback can enforce the total deadline.
BACKUP_BUSY_TIMEOUT_MILLISECONDS = 100
BACKUP_PAGES_PER_STEP = 128
BACKUP_RETRY_SLEEP_SECONDS = 0.01
OWNER_ONLY_FILE_MODE = 0o600


def validate_portfolio_snapshot(database_file: Path) -> PortfolioSnapshotIdentity:
    """Validate one immutable SQLite snapshot and return its stable identity."""
    connection = sqlite3.connect(
        f"{database_file.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    )
    try:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise PortfolioBackupIntegrityError
        portfolio_row = connection.execute(
            "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
        ).fetchone()
        if portfolio_row is None:
            raise PortfolioBackupIdentityError
        portfolio_id = portfolio_row[0]
        try:
            parsed_portfolio_id = uuid.UUID(portfolio_id)
        except (AttributeError, TypeError, ValueError):
            raise PortfolioBackupIdentityError from None
        if str(parsed_portfolio_id) != portfolio_id:
            raise PortfolioBackupIdentityError
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        return PortfolioSnapshotIdentity(portfolio_id, schema_version)
    finally:
        connection.close()


class SQLitePortfolioBackupReader:
    """Copy and validate one SQLite portfolio while its reader lock remains held."""

    def __init__(
        self,
        connection,
        backup_timeout_seconds: float = DEFAULT_BACKUP_TIMEOUT_SECONDS,
    ):
        if backup_timeout_seconds <= 0:
            raise ValueError("The SQLite backup timeout must be positive.")
        self._connection = connection
        self._backup_timeout_seconds = backup_timeout_seconds

    def backup_to(self, destination: Path) -> PortfolioSnapshotIdentity:
        try:
            deadline = time.monotonic() + self._backup_timeout_seconds

            def enforce_deadline(_status, _remaining, _total):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out while waiting for the SQLite backup.")

            self._connection.execute(f"PRAGMA busy_timeout = {BACKUP_BUSY_TIMEOUT_MILLISECONDS}")
            destination_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                OWNER_ONLY_FILE_MODE,
            )
            os.close(destination_descriptor)
            if os.name == "posix":
                os.chmod(destination, OWNER_ONLY_FILE_MODE)
            destination_connection = sqlite3.connect(destination)
            try:
                self._connection.backup(
                    destination_connection,
                    pages=BACKUP_PAGES_PER_STEP,
                    progress=enforce_deadline,
                    sleep=BACKUP_RETRY_SLEEP_SECONDS,
                )
                destination_connection.commit()
            finally:
                destination_connection.close()
            return self._validate_and_read_identity(destination)
        except (
            PortfolioBackupIdentityError,
            PortfolioBackupIntegrityError,
        ):
            raise
        except sqlite3.DatabaseError as error:
            raise PortfolioBackupSourceError from error

    @staticmethod
    def _validate_and_read_identity(database_file: Path) -> PortfolioSnapshotIdentity:
        return validate_portfolio_snapshot(database_file)


class SQLitePortfolioBackupSource:
    """Prepare and lock one concrete SQLite portfolio selected for backup."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        backup_timeout_seconds: float = DEFAULT_BACKUP_TIMEOUT_SECONDS,
    ):
        self._database_manager = database_manager
        self._backup_timeout_seconds = backup_timeout_seconds

    def prepare(self) -> None:
        try:
            connection = self._database_manager.get_personal_connection()
            try:
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                try:
                    portfolio_row = connection.execute(
                        "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
                    ).fetchone()
                except sqlite3.OperationalError as error:
                    if "no such table" not in str(error):
                        raise
                    portfolio_row = None
            finally:
                connection.close()

            if schema_version < CURRENT_SCHEMA_VERSION or portfolio_row is None:
                self._database_manager.init_personal_db()
        except (
            PortfolioBackupIntegrityError,
            PortfolioBackupUnavailableError,
            TimeoutError,
        ):
            raise
        except sqlite3.DatabaseError as error:
            raise PortfolioBackupSourceError from error

    @contextmanager
    def open_reader(self):
        try:
            connection = self._database_manager.get_personal_connection()
        except (
            PortfolioBackupIntegrityError,
            PortfolioBackupUnavailableError,
            TimeoutError,
        ):
            raise
        except sqlite3.DatabaseError as error:
            raise PortfolioBackupSourceError from error
        try:
            yield SQLitePortfolioBackupReader(
                connection,
                backup_timeout_seconds=self._backup_timeout_seconds,
            )
        finally:
            connection.close()


class SQLitePortfolioBackupSourceFactory:
    """Build lifecycle-aware SQLite sources for local portfolio selections."""

    def __init__(
        self,
        application_paths: ApplicationPaths,
        backup_timeout_seconds: float = DEFAULT_BACKUP_TIMEOUT_SECONDS,
    ):
        self._paths = application_paths
        self._backup_timeout_seconds = backup_timeout_seconds

    def create(
        self,
        filename: str,
        expected_generation: str | None,
    ) -> PortfolioBackupSourcePort:
        try:
            database = self._paths.portfolio_database(filename)
            if database.resolve().parent != self._paths.database_dir.resolve():
                raise ValueError("Portfolio path escapes the local database directory.")
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as error:
            raise PortfolioBackupSelectionError from error

        def guard_selected_generation(guarded_path: Path) -> None:
            if (
                not guarded_path.is_file()
                or self._paths.database_generation(guarded_path) != expected_generation
            ):
                raise PortfolioBackupUnavailableError
            if not self._is_valid_selected_database(guarded_path):
                raise PortfolioBackupIntegrityError

        return SQLitePortfolioBackupSource(
            DatabaseManager(database, connection_guard=guard_selected_generation),
            backup_timeout_seconds=self._backup_timeout_seconds,
        )

    @staticmethod
    def _is_valid_selected_database(database: Path) -> bool:
        try:
            connection = sqlite3.connect(
                f"{database.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=0,
            )
            try:
                connection.execute("PRAGMA busy_timeout = 0")
                return connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            finally:
                connection.close()
        except sqlite3.OperationalError as error:
            error_code = getattr(error, "sqlite_errorcode", None)
            is_contention_error = (
                error_code is not None
                and error_code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
            ) or any(token in str(error).lower() for token in ("locked", "busy"))
            if is_contention_error:
                raise TimeoutError("The selected SQLite database is in use.") from error
            return False
        except (OSError, sqlite3.DatabaseError):
            return False

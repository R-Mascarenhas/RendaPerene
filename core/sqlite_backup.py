import sqlite3
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


class SQLitePortfolioBackupReader:
    """Copy and validate one SQLite portfolio while its reader lock remains held."""

    def __init__(self, connection):
        self._connection = connection

    def backup_to(self, destination: Path) -> PortfolioSnapshotIdentity:
        try:
            destination_connection = sqlite3.connect(destination)
            try:
                self._connection.backup(destination_connection)
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


class SQLitePortfolioBackupSource:
    """Prepare and lock one concrete SQLite portfolio selected for backup."""

    def __init__(self, database_manager: DatabaseManager):
        self._database_manager = database_manager

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
            yield SQLitePortfolioBackupReader(connection)
        finally:
            connection.close()


class SQLitePortfolioBackupSourceFactory:
    """Build lifecycle-aware SQLite sources for local portfolio selections."""

    def __init__(self, application_paths: ApplicationPaths):
        self._paths = application_paths

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
            if not self._paths.is_valid_sqlite(guarded_path):
                raise PortfolioBackupIntegrityError

        return SQLitePortfolioBackupSource(
            DatabaseManager(database, connection_guard=guard_selected_generation)
        )

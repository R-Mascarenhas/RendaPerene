import sqlite3
import sys
from contextlib import suppress

from core.application_paths import portfolio_database_lock


class _LockedConnection(sqlite3.Connection):
    """Release a portfolio file lock when its SQLite connection closes."""

    _lock_context = None

    def attach_lock(self, lock_context):
        self._lock_context = lock_context

    def close(self):
        lock_context = self._lock_context
        self._lock_context = None
        try:
            super().close()
        finally:
            if lock_context is not None:
                lock_context.__exit__(None, None, None)


class DatabaseManager:
    """Manages SQLite connection and initialization for the personal portfolio transactions domain."""

    _registry = []

    def __init__(self, personal_db="database/portfolio.db"):
        self.personal_db = personal_db

    @classmethod
    def register_schema(cls, schema_provider):
        """Registers a schema provider implementing TableSchemaPort."""
        if schema_provider not in cls._registry:
            cls._registry.append(schema_provider)

    def init_personal_db(self):
        """Creates the user data tables in the personal SQLite database by iterating over registered schemas."""
        import glob
        import importlib
        import os

        # Dynamically discover and load all schema providers in core/daos/
        daos_dir = os.path.dirname(__file__)
        daos_path = os.path.join(daos_dir, "daos")
        modules = glob.glob(os.path.join(daos_path, "*.py"))
        for f in modules:
            basename = os.path.basename(f)
            if basename != "__init__.py":
                module_name = basename[:-3]
                with suppress(Exception):
                    importlib.import_module(f"core.daos.{module_name}")

        conn = self.get_personal_connection()
        try:
            for schema_provider in self._registry:
                schema_provider.initialize_tables(conn)
            conn.commit()
        finally:
            conn.close()

    def get_personal_connection(self):
        """Returns a new connection to the configured personal transactional database."""
        from pathlib import Path

        configured_database = self.personal_db() if callable(self.personal_db) else self.personal_db
        db_file = Path(configured_database)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        lock_context = portfolio_database_lock(db_file)
        lock_context.__enter__()
        try:
            connection = sqlite3.connect(db_file, factory=_LockedConnection)
        except BaseException:
            lock_context.__exit__(*sys.exc_info())
            raise
        connection.attach_lock(lock_context)
        return connection


# Global Singleton instance for the app
db = DatabaseManager()

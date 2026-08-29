from contextlib import suppress


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
        import sqlite3
        from pathlib import Path

        db_file = Path(self.personal_db)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(db_file)


# Global Singleton instance for the app
db = DatabaseManager()

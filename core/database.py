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
        import os
        import glob
        import importlib

        # Dynamically discover and load all schema providers in core/daos/
        daos_dir = os.path.dirname(__file__)
        daos_path = os.path.join(daos_dir, "daos")
        modules = glob.glob(os.path.join(daos_path, "*.py"))
        for f in modules:
            basename = os.path.basename(f)
            if basename != "__init__.py":
                module_name = basename[:-3]
                try:
                    importlib.import_module(f"core.daos.{module_name}")
                except Exception:
                    pass

        conn = self.get_personal_connection()
        try:
            for schema_provider in self._registry:
                schema_provider.initialize_tables(conn)
            conn.commit()
        finally:
            conn.close()

    def get_personal_connection(self):
        """Returns a new connection to the personal transactional database, isolating sessions in cloud demo mode."""
        import os
        import sqlite3
        import shutil

        db_file = self.personal_db
        try:
            import streamlit as st
            # Detect if running in public shared cloud environments (Streamlit Cloud uses '/mount/src/...')
            is_cloud = (
                "STREAMLIT_SHARING_MODE" in os.environ or
                os.path.abspath(".").startswith("/mount") or
                "/mount/" in os.path.abspath(".")
            )
            if st.runtime.exists() and is_cloud:
                if "session_id" not in st.session_state:
                    import uuid
                    st.session_state["session_id"] = str(uuid.uuid4())
                db_file = f"database/portfolio_{st.session_state['session_id']}.db"

                # If the guest DB does not exist yet, clone the demo db
                if not os.path.exists(db_file):
                    os.makedirs(os.path.dirname(db_file), exist_ok=True)
                    demo_template = "database/portfolio_demo.db"
                    if os.path.exists(demo_template):
                        shutil.copy(demo_template, db_file)
        except Exception:
            pass

        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        return sqlite3.connect(db_file)

# Global Singleton instance for the app
db = DatabaseManager()

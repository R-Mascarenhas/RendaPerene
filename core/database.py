import sqlite3
from core.constants import (
    BIRTH_DATE, RETIREMENT_AGE, DESIRED_INCOME_MW, ANNUAL_INTEREST_RATE,
    MW_VALUE, INITIAL_EQUITY_INPUT, DESIRED_INCOME_TYPE, DESIRED_INCOME_FIXED,
    CEILING_MODEL_SELECTION, BAZIN_TARGET_YIELD, BAZIN_TARGET_SPREAD, INCOME_TYPE_MULTIPLIER,
    PLANNING_START_DATE
)

from core.strings import MODEL_CLASSIC

class DatabaseManager:
    """Manages SQLite connection and initialization for the personal portfolio transactions domain."""

    def __init__(self, personal_db="database/portfolio.db"):
        self.personal_db = personal_db

    def init_personal_db(self):
        """Creates the user data tables in the personal SQLite database."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                fees REAL DEFAULT 0.0
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dividends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                dividend_type TEXT NOT NULL,
                total_value REAL NOT NULL
            )
        ''')

        # Generate planning_configuration table schema dynamically using core constants
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS planning_configuration (
                id INTEGER PRIMARY KEY DEFAULT 1,
                {BIRTH_DATE} TEXT NOT NULL,
                {RETIREMENT_AGE} INTEGER NOT NULL,
                {DESIRED_INCOME_MW} REAL NOT NULL,
                {ANNUAL_INTEREST_RATE} REAL NOT NULL,
                {MW_VALUE} REAL NOT NULL,
                {INITIAL_EQUITY_INPUT} REAL NOT NULL,
                {DESIRED_INCOME_TYPE} TEXT DEFAULT 'MULTIPLIER',
                {DESIRED_INCOME_FIXED} REAL DEFAULT 10000.0,
                {CEILING_MODEL_SELECTION} TEXT DEFAULT '{MODEL_CLASSIC}',
                {BAZIN_TARGET_YIELD} REAL DEFAULT 6.0,
                {BAZIN_TARGET_SPREAD} REAL DEFAULT 3.0,
                {PLANNING_START_DATE} TEXT DEFAULT NULL
            )
        ''')

        # Run retrocompatibility schema migrations
        try:
            cursor.execute(f"ALTER TABLE planning_configuration ADD COLUMN {PLANNING_START_DATE} TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

        # Create other transactional and market reference tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracked_market_assets (
                ticker TEXT PRIMARY KEY
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dividend_corrections (
                ticker TEXT NOT NULL,
                year INTEGER NOT NULL,
                total_value REAL NOT NULL,
                PRIMARY KEY (ticker, year)
            )
        ''')

        # Pre-seed BBAS3 and BBDC3 values if empty to keep out-of-the-box accuracy without Python hardcoding
        cursor.execute("SELECT COUNT(*) FROM dividend_corrections")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2023, 2.29)")
            cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2024, 2.61)")
            cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBDC3', 2023, 1.54)")
            cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBDC3', 2024, 1.01)")

        conn.commit()
        conn.close()

    def get_personal_connection(self):
        """Returns a new connection to the personal transactional database, isolating sessions in cloud demo mode."""
        import os
        import sqlite3

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
        except Exception:
            pass

        os.makedirs(os.path.dirname(db_file), exist_ok=True)
        return sqlite3.connect(db_file)

# Global Singleton instance for the app
db = DatabaseManager()

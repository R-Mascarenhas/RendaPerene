import sqlite3

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

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS planning_configuration (
                id INTEGER PRIMARY KEY DEFAULT 1,
                birth_date TEXT NOT NULL,
                retirement_age INTEGER NOT NULL,
                desired_income_mw REAL NOT NULL,
                annual_interest_rate REAL NOT NULL,
                mw_value REAL NOT NULL,
                initial_equity_input REAL NOT NULL
            )
        ''')

        # Backward compatibility migrations: safely add English planning fields if missing
        try:
            cursor.execute("ALTER TABLE planning_configuration ADD COLUMN desired_income_type TEXT DEFAULT 'MULTIPLIER'")
            conn.commit()
        except Exception:
            pass # Column already exists, safe to ignore

        try:
            cursor.execute("ALTER TABLE planning_configuration ADD COLUMN desired_income_fixed REAL DEFAULT 10000.0")
            conn.commit()
        except Exception:
            pass # Column already exists, safe to ignore

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

        # Pre-seed BBAS3 values if empty to keep out-of-the-box accuracy without Python hardcoding
        cursor.execute("SELECT COUNT(*) FROM dividend_corrections")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2023, 2.29)")
            cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2024, 2.61)")

        conn.commit()
        conn.close()

    def get_personal_connection(self):
        """Returns a new connection to the personal transactional database."""
        return sqlite3.connect(self.personal_db)

# Global Singleton instance for the app
db = DatabaseManager()

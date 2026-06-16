import sqlite3

class DatabaseManager:
    """Manages SQLite connection and initialization for the personal transactions domain."""

    def __init__(self, personal_db="database/carteira.db"):
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

        conn.commit()
        conn.close()

    def get_personal_connection(self):
        """Returns a new connection to the personal transactional database."""
        return sqlite3.connect(self.personal_db)

# Global Singleton instance for the app
db = DatabaseManager()

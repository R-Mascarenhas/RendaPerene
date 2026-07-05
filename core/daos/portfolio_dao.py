import sqlite3
import pandas as pd
from core.database import db

class PortfolioDAO:
    """Data Access Object (DAO) for managing SQLite database access on database/portfolio.db."""

    @staticmethod
    def get_personal_connection():
        """Delegates and returns an active SQLite database connection."""
        return db.get_personal_connection()

    @staticmethod
    def find_transaction(date: str, ticker: str, transaction_type: str, quantity: int, unit_price: float, fees: float) -> bool:
        """Returns True if a matching transaction exists in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id FROM transactions
                WHERE date = ? AND ticker = ? AND transaction_type = ? AND quantity = ? AND unit_price = ? AND fees = ?
            ''', (date, ticker, transaction_type, quantity, unit_price, fees))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    @staticmethod
    def insert_transaction(date: str, ticker: str, transaction_type: str, quantity: int, unit_price: float, fees: float) -> bool:
        """Inserts a new transaction into the transactions table."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (date, ticker, transaction_type, quantity, unit_price, fees))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def find_dividend(date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        """Returns True if a matching dividend receipt exists in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id FROM dividends
                WHERE date = ? AND ticker = ? AND dividend_type = ? AND total_value = ?
            ''', (date, ticker, dividend_type, total_value))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    @staticmethod
    def insert_dividend(date: str, ticker: str, dividend_type: str, total_value: float) -> bool:
        """Inserts a new dividend into the dividends table."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO dividends (date, ticker, dividend_type, total_value)
                VALUES (?, ?, ?, ?)
            ''', (date, ticker, dividend_type, total_value))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def get_quantity_on_date(ticker: str, date_str: str, conn=None) -> int:
        """Returns the sum of quantities owned of a specific ticker on or before a given date."""
        ticker = ticker.upper().strip()
        local_conn = conn if conn is not None else db.get_personal_connection()
        cursor = local_conn.cursor()
        try:
            cursor.execute("""
                SELECT SUM(CASE WHEN transaction_type='BUY' THEN quantity ELSE -quantity END)
                FROM transactions
                WHERE ticker = ? AND date <= ?
            """, (ticker, date_str))
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0
        finally:
            if conn is None:
                local_conn.close()

    @staticmethod
    def get_transactions_by_ticker(ticker: str) -> pd.DataFrame:
        """Returns all transactions for a ticker as a DataFrame."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date, transaction_type, quantity, unit_price, fees FROM transactions WHERE ticker = ? ORDER BY date ASC",
                conn, params=(ticker,)
            )
        finally:
            conn.close()

    @staticmethod
    def get_transactions_by_ticker_desc(ticker: str) -> pd.DataFrame:
        """Returns all transactions for a specific asset ordered by date descending."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date as Data, CASE WHEN transaction_type='BUY' THEN 'Compra' ELSE 'Venda' END as Operação, quantity as Quantidade, unit_price as [Valor Unitário], (quantity * unit_price + fees) as [Valor Total] FROM transactions WHERE ticker = ? ORDER BY date DESC",
                conn, params=(ticker,)
            )
        finally:
            conn.close()

    @staticmethod
    def get_dividends_by_ticker(ticker: str) -> pd.DataFrame:
        """Returns all dividends for a ticker as a DataFrame."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date as Data, CASE WHEN dividend_type='DIVIDEND' THEN 'Dividendo' WHEN dividend_type='JCP' THEN 'JCP' ELSE 'Rendimento' END as Tipo, total_value as Total FROM dividends WHERE ticker = ? ORDER BY date DESC",
                conn, params=(ticker,)
            )
        finally:
            conn.close()

    @staticmethod
    def get_years_with_dividends() -> list:
        """Returns a sorted list of unique years in dividends table."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT strftime('%Y', date) as yr FROM dividends WHERE date IS NOT NULL ORDER BY yr DESC")
            return [row[0] for row in cursor.fetchall() if row[0] is not None]
        finally:
            conn.close()

    @staticmethod
    def get_asset_years_with_dividends(ticker: str) -> list:
        """Returns unique dividend years for a specific ticker."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT strftime('%Y', date) as yr FROM dividends WHERE ticker = ? AND date IS NOT NULL ORDER BY yr DESC", (ticker,))
            return [row[0] for row in cursor.fetchall() if row[0] is not None]
        finally:
            conn.close()

    @staticmethod
    def get_annual_dividend_types_sum(year: str) -> list:
        """Returns aggregated SUM of dividend types for a specific year."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT dividend_type, SUM(total_value)
                FROM dividends
                WHERE strftime('%Y', date) = ?
                GROUP BY dividend_type
            ''', (year,))
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_asset_annual_dividend_types_sum(ticker: str, year: str) -> list:
        """Returns aggregated SUM of dividend types for a specific ticker and year."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT dividend_type, SUM(total_value)
                FROM dividends
                WHERE ticker = ? AND strftime('%Y', date) = ?
                GROUP BY dividend_type
            ''', (ticker, year))
            return cursor.fetchall()
        finally:
            conn.close()

    @staticmethod
    def get_tracked_assets() -> list:
        """Returns watchlist tickers from tracked_market_assets."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT ticker FROM tracked_market_assets ORDER BY ticker ASC")
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def insert_tracked_asset(ticker: str) -> bool:
        """Inserts or replaces a tracked asset in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR REPLACE INTO tracked_market_assets (ticker) VALUES (?)", (ticker.upper().strip(),))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def delete_tracked_asset(ticker: str) -> bool:
        """Removes a tracked asset from tracked_market_assets."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM tracked_market_assets WHERE ticker = ?", (ticker.upper().strip(),))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def insert_dividend_correction(ticker: str, year: int, total_value: float) -> bool:
        """Inserts or replaces a manual dividend correction."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES (?, ?, ?)",
                (ticker.upper().strip(), int(year), float(total_value))
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def get_dividend_corrections(ticker: str) -> dict:
        """Returns registered dividend corrections for a specific ticker."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT year, total_value FROM dividend_corrections WHERE ticker = ? ORDER BY year DESC", (ticker.upper().strip(),))
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception:
            return {}
        finally:
            conn.close()

    @staticmethod
    def get_all_transactions() -> pd.DataFrame:
        """Returns all transactions in the database."""
        conn = db.get_personal_connection()
        try:
            return pd.read_sql_query(
                "SELECT date, ticker, transaction_type, quantity, unit_price, fees FROM transactions ORDER BY date ASC, id ASC",
                conn
            )
        finally:
            conn.close()

    @staticmethod
    def get_total_dividends_by_ticker(ticker: str) -> float:
        """Returns total dividends sum for a specific ticker."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT SUM(total_value) FROM dividends WHERE ticker = ?", (ticker,))
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0.0
        finally:
            conn.close()

    @staticmethod
    def get_dividends_by_ticker_since_date(ticker: str, limit_date: str) -> float:
        """Returns dividends sum since a specific date for a ticker."""
        ticker = ticker.upper().strip()
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT SUM(total_value) FROM dividends WHERE ticker = ? AND date >= ?", (ticker, limit_date))
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0.0
        finally:
            conn.close()

    @staticmethod
    def get_all_dividends() -> pd.DataFrame:
        """Returns all dividends in the database."""
        conn = db.get_personal_connection()
        try:
            return pd.read_sql_query("SELECT date, dividend_type, total_value FROM dividends", conn)
        finally:
            conn.close()

    @staticmethod
    def get_ytd_contributions_sum(limit_date: str) -> float:
        """Returns sum of net buy transactions on or after a given date."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT SUM(quantity * unit_price + fees) FROM transactions WHERE transaction_type = 'BUY' AND date >= ?",
                (limit_date,)
            )
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0.0
        finally:
            conn.close()

    @staticmethod
    def get_all_buy_transactions() -> pd.DataFrame:
        """Returns all buy transactions in the database."""
        conn = db.get_personal_connection()
        try:
            return pd.read_sql_query("SELECT date, quantity, unit_price, fees FROM transactions WHERE transaction_type = 'BUY'", conn)
        finally:
            conn.close()

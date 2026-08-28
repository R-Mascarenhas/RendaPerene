import sqlite3
from contextlib import suppress

from core.constants import (
    ANNUAL_INTEREST_RATE,
    BAZIN_TARGET_SPREAD,
    BAZIN_TARGET_YIELD,
    BIRTH_DATE,
    CEILING_MODEL_SELECTION,
    DESIRED_INCOME_FIXED,
    DESIRED_INCOME_MW,
    DESIRED_INCOME_TYPE,
    GOAL_REINVEST_DIVIDENDS,
    GOAL_SHARE_QUANTITY,
    INITIAL_EQUITY_INPUT,
    MW_VALUE,
    PLANNING_START_DATE,
    RETIREMENT_AGE,
)
from core.database import db


class PlanningDAO:
    """Data Access Object (DAO) for managing SQLite database access for retirement planning configurations."""

    def __init__(self, db_manager=None):
        self.db = db_manager or db

    def get_personal_connection(self):
        """Delegates and returns an active SQLite database connection."""
        return self.db.get_personal_connection()

    def get_configuration(self) -> dict | None:
        """Fetches the planning configuration from the database."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"""
                SELECT {BIRTH_DATE}, {RETIREMENT_AGE}, {DESIRED_INCOME_MW}, {ANNUAL_INTEREST_RATE},
                       {MW_VALUE}, {INITIAL_EQUITY_INPUT}, {DESIRED_INCOME_TYPE}, {DESIRED_INCOME_FIXED},
                       {CEILING_MODEL_SELECTION}, {BAZIN_TARGET_YIELD}, {BAZIN_TARGET_SPREAD}, {PLANNING_START_DATE}
                FROM planning_configuration WHERE id = 1
            """)
            row = cursor.fetchone()
            if row:
                return {
                    BIRTH_DATE: row[0],
                    RETIREMENT_AGE: row[1],
                    DESIRED_INCOME_MW: row[2],
                    ANNUAL_INTEREST_RATE: row[3],
                    MW_VALUE: row[4],
                    INITIAL_EQUITY_INPUT: row[5],
                    DESIRED_INCOME_TYPE: row[6] if row[6] else "MULTIPLIER",
                    DESIRED_INCOME_FIXED: row[7] if row[7] is not None else 10000.0,
                    CEILING_MODEL_SELECTION: row[8] if row[8] else "Bazin Clássico",
                    BAZIN_TARGET_YIELD: row[9] if row[9] is not None else 6.0,
                    BAZIN_TARGET_SPREAD: row[10] if row[10] is not None else 3.0,
                    PLANNING_START_DATE: row[11] if len(row) > 11 else None,
                }
            return None
        except Exception:
            return None
        finally:
            conn.close()

    def save_configuration(
        self,
        birth_date: str,
        retirement_age: int,
        desired_income_mw: float,
        annual_interest_rate: float,
        mw_value: float,
        initial_equity_input: float,
        desired_income_type: str = "MULTIPLIER",
        desired_income_fixed: float = 10000.0,
        ceiling_model_selection: str = "Bazin Clássico",
        bazin_target_yield: float = 6.0,
        bazin_target_spread: float = 3.0,
        planning_start_date: str = None,
    ) -> None:
        """Saves or updates the planning configuration in the database."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM planning_configuration WHERE id = 1")
            if cursor.fetchone():
                cursor.execute(
                    f"""
                    UPDATE planning_configuration
                    SET {BIRTH_DATE} = ?, {RETIREMENT_AGE} = ?, {DESIRED_INCOME_MW} = ?, {ANNUAL_INTEREST_RATE} = ?,
                        {MW_VALUE} = ?, {INITIAL_EQUITY_INPUT} = ?, {DESIRED_INCOME_TYPE} = ?, {DESIRED_INCOME_FIXED} = ?,
                        {CEILING_MODEL_SELECTION} = ?, {BAZIN_TARGET_YIELD} = ?, {BAZIN_TARGET_SPREAD} = ?,
                        {PLANNING_START_DATE} = ?
                    WHERE id = 1
                """,
                    (
                        birth_date,
                        retirement_age,
                        desired_income_mw,
                        annual_interest_rate,
                        mw_value,
                        initial_equity_input,
                        desired_income_type,
                        desired_income_fixed,
                        ceiling_model_selection,
                        bazin_target_yield,
                        bazin_target_spread,
                        planning_start_date,
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    INSERT INTO planning_configuration
                    (id, {BIRTH_DATE}, {RETIREMENT_AGE}, {DESIRED_INCOME_MW}, {ANNUAL_INTEREST_RATE},
                     {MW_VALUE}, {INITIAL_EQUITY_INPUT}, {DESIRED_INCOME_TYPE}, {DESIRED_INCOME_FIXED},
                     {CEILING_MODEL_SELECTION}, {BAZIN_TARGET_YIELD}, {BAZIN_TARGET_SPREAD}, {PLANNING_START_DATE})
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        birth_date,
                        retirement_age,
                        desired_income_mw,
                        annual_interest_rate,
                        mw_value,
                        initial_equity_input,
                        desired_income_type,
                        desired_income_fixed,
                        ceiling_model_selection,
                        bazin_target_yield,
                        bazin_target_spread,
                        planning_start_date,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_min_transaction_date(self) -> str:
        """Returns the chronological minimum transaction date, or a default fallback date."""
        conn = self.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MIN(date) FROM transactions")
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else "2021-04-30"
        finally:
            conn.close()

    def list_accumulation_goals(self) -> list[dict]:
        """Returns all configured accumulation goals ordered by ticker."""
        conn = self.get_personal_connection()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT ticker, start_quantity, target_quantity, target_mode,
                       target_percentage, allocation_weight, average_dividend_5y,
                       is_active, created_at
                FROM asset_accumulation_goals
                ORDER BY ticker
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def upsert_accumulation_goal(
        self,
        ticker: str,
        start_quantity: float,
        target_quantity: float,
        target_mode: str,
        target_percentage: float | None,
        allocation_weight: float,
        average_dividend_5y: float,
        is_active: bool = True,
    ) -> None:
        """Creates a goal or replaces its baseline and target for the ticker."""
        conn = self.get_personal_connection()
        try:
            conn.execute(
                """
                INSERT INTO asset_accumulation_goals (
                    ticker, start_quantity, target_quantity, target_mode,
                    target_percentage, allocation_weight, average_dividend_5y, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    start_quantity = excluded.start_quantity,
                    target_quantity = excluded.target_quantity,
                    target_mode = excluded.target_mode,
                    target_percentage = excluded.target_percentage,
                    allocation_weight = excluded.allocation_weight,
                    average_dividend_5y = excluded.average_dividend_5y,
                    is_active = excluded.is_active,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    ticker,
                    start_quantity,
                    target_quantity,
                    target_mode,
                    target_percentage,
                    allocation_weight,
                    average_dividend_5y,
                    int(is_active),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_accumulation_goal(self, ticker: str) -> bool:
        """Deletes the accumulation goal for a ticker."""
        conn = self.get_personal_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM asset_accumulation_goals WHERE ticker = ?", (ticker,)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_goal_settings(self) -> dict[str, bool]:
        """Returns all portfolio-wide investment goal preferences."""
        conn = self.get_personal_connection()
        try:
            row = conn.execute(
                """
                SELECT reinvest_dividends_enabled, share_quantity_enabled
                FROM goal_settings WHERE id = 1
                """
            ).fetchone()
            if not row:
                return {GOAL_REINVEST_DIVIDENDS: True, GOAL_SHARE_QUANTITY: False}
            return {
                GOAL_REINVEST_DIVIDENDS: bool(row[0]),
                GOAL_SHARE_QUANTITY: bool(row[1]),
            }
        finally:
            conn.close()

    def set_goal_enabled(self, goal_type: str, enabled: bool) -> None:
        """Persists one supported portfolio-wide investment goal preference."""
        columns = {
            GOAL_REINVEST_DIVIDENDS: "reinvest_dividends_enabled",
            GOAL_SHARE_QUANTITY: "share_quantity_enabled",
        }
        if goal_type not in columns:
            raise ValueError("O tipo de meta informado não é suportado.")
        conn = self.get_personal_connection()
        try:
            conn.execute(
                f"UPDATE goal_settings SET {columns[goal_type]} = ? WHERE id = 1",
                (int(enabled),),
            )
            conn.commit()
        finally:
            conn.close()

    def initialize_tables(self, conn) -> None:
        """Creates tables, runs migrations, and seeds defaults for the Retirement Planning domain."""
        cursor = conn.cursor()

        # Generate planning_configuration table schema dynamically using core constants
        cursor.execute(f"""
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
                {CEILING_MODEL_SELECTION} TEXT DEFAULT 'Bazin Clássico',
                {BAZIN_TARGET_YIELD} REAL DEFAULT 6.0,
                {BAZIN_TARGET_SPREAD} REAL DEFAULT 3.0,
                {PLANNING_START_DATE} TEXT DEFAULT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asset_accumulation_goals (
                ticker TEXT PRIMARY KEY,
                start_quantity REAL NOT NULL CHECK (start_quantity >= 0),
                target_quantity REAL NOT NULL CHECK (target_quantity > start_quantity),
                target_mode TEXT NOT NULL CHECK (
                    target_mode IN ('DIVIDEND_INCOME', 'PERCENTAGE', 'QUANTITY')
                ),
                target_percentage REAL,
                allocation_weight REAL NOT NULL CHECK (
                    allocation_weight >= 0 AND allocation_weight <= 100
                ),
                average_dividend_5y REAL NOT NULL CHECK (average_dividend_5y >= 0),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        accumulation_schema = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'asset_accumulation_goals'"
        ).fetchone()[0]
        accumulation_columns = {
            row[1] for row in cursor.execute("PRAGMA table_info(asset_accumulation_goals)")
        }
        if (
            "is_active" not in accumulation_columns
            or "allocation_weight > 0" in accumulation_schema
        ):
            active_expression = "is_active" if "is_active" in accumulation_columns else "1"
            cursor.execute(
                "ALTER TABLE asset_accumulation_goals RENAME TO asset_accumulation_goals_legacy"
            )
            cursor.execute("""
                CREATE TABLE asset_accumulation_goals (
                    ticker TEXT PRIMARY KEY,
                    start_quantity REAL NOT NULL CHECK (start_quantity >= 0),
                    target_quantity REAL NOT NULL CHECK (target_quantity > start_quantity),
                    target_mode TEXT NOT NULL CHECK (
                        target_mode IN ('DIVIDEND_INCOME', 'PERCENTAGE', 'QUANTITY')
                    ),
                    target_percentage REAL,
                    allocation_weight REAL NOT NULL CHECK (
                        allocation_weight >= 0 AND allocation_weight <= 100
                    ),
                    average_dividend_5y REAL NOT NULL CHECK (average_dividend_5y >= 0),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(f"""
                INSERT INTO asset_accumulation_goals (
                    ticker, start_quantity, target_quantity, target_mode,
                    target_percentage, allocation_weight, average_dividend_5y,
                    is_active, created_at
                )
                SELECT ticker, start_quantity, target_quantity, target_mode,
                       target_percentage, allocation_weight, average_dividend_5y,
                       {active_expression}, created_at
                FROM asset_accumulation_goals_legacy
            """)
            cursor.execute("DROP TABLE asset_accumulation_goals_legacy")

        legacy_goal_settings_exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'accumulation_goal_settings'"
        ).fetchone()
        legacy_share_quantity_enabled = None
        if legacy_goal_settings_exists:
            legacy_row = cursor.execute(
                "SELECT enabled FROM accumulation_goal_settings WHERE id = 1"
            ).fetchone()
            legacy_share_quantity_enabled = legacy_row[0] if legacy_row else None

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS goal_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                reinvest_dividends_enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (reinvest_dividends_enabled IN (0, 1)),
                share_quantity_enabled INTEGER NOT NULL DEFAULT 0
                    CHECK (share_quantity_enabled IN (0, 1))
            )
        """)
        default_share_quantity_enabled = (
            int(legacy_share_quantity_enabled)
            if legacy_share_quantity_enabled is not None
            else int(
                cursor.execute("SELECT 1 FROM asset_accumulation_goals LIMIT 1").fetchone()
                is not None
            )
        )
        cursor.execute(
            """
            INSERT OR IGNORE INTO goal_settings (
                id, reinvest_dividends_enabled, share_quantity_enabled
            ) VALUES (1, 1, ?)
            """,
            (default_share_quantity_enabled,),
        )

        # Run retrocompatibility schema migrations
        with suppress(sqlite3.OperationalError):
            cursor.execute(
                f"ALTER TABLE planning_configuration ADD COLUMN {PLANNING_START_DATE} TEXT DEFAULT NULL"
            )


# Register schema self-registration provider
db.register_schema(PlanningDAO())

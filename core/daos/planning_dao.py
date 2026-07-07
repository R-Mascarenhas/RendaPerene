from core.database import db
from core.constants import (
    BIRTH_DATE, RETIREMENT_AGE, DESIRED_INCOME_MW, ANNUAL_INTEREST_RATE,
    MW_VALUE, INITIAL_EQUITY_INPUT, DESIRED_INCOME_TYPE, DESIRED_INCOME_FIXED,
    CEILING_MODEL_SELECTION, BAZIN_TARGET_YIELD, BAZIN_TARGET_SPREAD, PLANNING_START_DATE
)

class PlanningDAO:
    """Data Access Object (DAO) for managing SQLite database access for retirement planning configurations."""

    @staticmethod
    def get_configuration() -> dict | None:
        """Fetches the planning configuration from the database."""
        conn = db.get_personal_connection()
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
                    DESIRED_INCOME_TYPE: row[6] if row[6] else 'MULTIPLIER',
                    DESIRED_INCOME_FIXED: row[7] if row[7] is not None else 10000.0,
                    CEILING_MODEL_SELECTION: row[8] if row[8] else 'Bazin Clássico',
                    BAZIN_TARGET_YIELD: row[9] if row[9] is not None else 6.0,
                    BAZIN_TARGET_SPREAD: row[10] if row[10] is not None else 3.0,
                    PLANNING_START_DATE: row[11] if len(row) > 11 else None
                }
            return None
        except Exception:
            return None
        finally:
            conn.close()

    @staticmethod
    def save_configuration(birth_date: str, retirement_age: int, desired_income_mw: float,
                           annual_interest_rate: float, mw_value: float, initial_equity_input: float,
                           desired_income_type: str = "MULTIPLIER", desired_income_fixed: float = 10000.0,
                           ceiling_model_selection: str = "Bazin Clássico", bazin_target_yield: float = 6.0,
                           bazin_target_spread: float = 3.0, planning_start_date: str = None) -> None:
        """Saves or updates the planning configuration in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM planning_configuration WHERE id = 1")
            if cursor.fetchone():
                cursor.execute(f'''
                    UPDATE planning_configuration
                    SET {BIRTH_DATE} = ?, {RETIREMENT_AGE} = ?, {DESIRED_INCOME_MW} = ?, {ANNUAL_INTEREST_RATE} = ?,
                        {MW_VALUE} = ?, {INITIAL_EQUITY_INPUT} = ?, {DESIRED_INCOME_TYPE} = ?, {DESIRED_INCOME_FIXED} = ?,
                        {CEILING_MODEL_SELECTION} = ?, {BAZIN_TARGET_YIELD} = ?, {BAZIN_TARGET_SPREAD} = ?,
                        {PLANNING_START_DATE} = ?
                    WHERE id = 1
                ''', (birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input,
                      desired_income_type, desired_income_fixed, ceiling_model_selection, bazin_target_yield, bazin_target_spread,
                      planning_start_date))
            else:
                cursor.execute(f'''
                    INSERT INTO planning_configuration
                    (id, {BIRTH_DATE}, {RETIREMENT_AGE}, {DESIRED_INCOME_MW}, {ANNUAL_INTEREST_RATE},
                     {MW_VALUE}, {INITIAL_EQUITY_INPUT}, {DESIRED_INCOME_TYPE}, {DESIRED_INCOME_FIXED},
                     {CEILING_MODEL_SELECTION}, {BAZIN_TARGET_YIELD}, {BAZIN_TARGET_SPREAD}, {PLANNING_START_DATE})
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input,
                      desired_income_type, desired_income_fixed, ceiling_model_selection, bazin_target_yield, bazin_target_spread,
                      planning_start_date))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_min_transaction_date() -> str:
        """Returns the chronological minimum transaction date, or a default fallback date."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MIN(date) FROM transactions")
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else "2021-04-30"
        finally:
            conn.close()

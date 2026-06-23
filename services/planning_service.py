import datetime
import numpy as np
import pandas as pd
from core.database import db
from core.constants import (
    BIRTH_DATE, RETIREMENT_AGE, DESIRED_INCOME_MW, ANNUAL_INTEREST_RATE,
    MW_VALUE, INITIAL_EQUITY_INPUT, DESIRED_INCOME_TYPE, DESIRED_INCOME_FIXED,
    INCOME_TYPE_MULTIPLIER, BAZIN_TARGET_YIELD, BAZIN_TARGET_SPREAD, CEILING_MODEL_SELECTION
)
from core.strings import MODEL_CLASSIC

class SimulationService:
    """Domain Service for financial independence calculations and compound interest."""

    @staticmethod
    def get_configuration():
        """Fetches the planning configuration from the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT {BIRTH_DATE}, {RETIREMENT_AGE}, {DESIRED_INCOME_MW}, {ANNUAL_INTEREST_RATE}, {MW_VALUE}, {INITIAL_EQUITY_INPUT}, {DESIRED_INCOME_TYPE}, {DESIRED_INCOME_FIXED}, {CEILING_MODEL_SELECTION}, {BAZIN_TARGET_YIELD}, {BAZIN_TARGET_SPREAD} FROM planning_configuration WHERE id = 1")
            row = cursor.fetchone()
            if row:
                config = {
                    BIRTH_DATE: row[0],
                    RETIREMENT_AGE: row[1],
                    DESIRED_INCOME_MW: row[2],
                    ANNUAL_INTEREST_RATE: row[3],
                    MW_VALUE: row[4],
                    INITIAL_EQUITY_INPUT: row[5],
                    DESIRED_INCOME_TYPE: row[6] if row[6] else INCOME_TYPE_MULTIPLIER,
                    DESIRED_INCOME_FIXED: row[7] if row[7] is not None else 10000.0,
                    CEILING_MODEL_SELECTION: row[8] if row[8] else MODEL_CLASSIC,
                    BAZIN_TARGET_YIELD: row[9] if row[9] is not None else 6.0,
                    BAZIN_TARGET_SPREAD: row[10] if row[10] is not None else 3.0
                }
                return config
            return None
        except Exception:
            return None
        finally:
            conn.close()

    @staticmethod
    def save_configuration(birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input, desired_income_type="MULTIPLIER", desired_income_fixed=10000.0, ceiling_model_selection="Bazin Clássico", bazin_target_yield=6.0, bazin_target_spread=3.0):
        """Saves or updates the planning configuration in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM planning_configuration WHERE id = 1")
            if cursor.fetchone():
                cursor.execute(f'''
                    UPDATE planning_configuration
                    SET {BIRTH_DATE} = ?, {RETIREMENT_AGE} = ?, {DESIRED_INCOME_MW} = ?, {ANNUAL_INTEREST_RATE} = ?, {MW_VALUE} = ?, {INITIAL_EQUITY_INPUT} = ?, {DESIRED_INCOME_TYPE} = ?, {DESIRED_INCOME_FIXED} = ?, {CEILING_MODEL_SELECTION} = ?, {BAZIN_TARGET_YIELD} = ?, {BAZIN_TARGET_SPREAD} = ?
                    WHERE id = 1
                ''', (birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input, desired_income_type, desired_income_fixed, ceiling_model_selection, bazin_target_yield, bazin_target_spread))
            else:
                cursor.execute(f'''
                    INSERT INTO planning_configuration (id, {BIRTH_DATE}, {RETIREMENT_AGE}, {DESIRED_INCOME_MW}, {ANNUAL_INTEREST_RATE}, {MW_VALUE}, {INITIAL_EQUITY_INPUT}, {DESIRED_INCOME_TYPE}, {DESIRED_INCOME_FIXED}, {CEILING_MODEL_SELECTION}, {BAZIN_TARGET_YIELD}, {BAZIN_TARGET_SPREAD})
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input, desired_income_type, desired_income_fixed, ceiling_model_selection, bazin_target_yield, bazin_target_spread))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def get_initial_investment_age(birth_date):
        """Returns the exact age in months when the first investment was made."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(date) FROM transactions")
        min_date_res = cursor.fetchone()
        min_date_str = min_date_res[0] if min_date_res and min_date_res[0] is not None else "2021-04-30"
        conn.close()

        start_date = datetime.datetime.strptime(min_date_str, "%Y-%m-%d").date()
        
        start_months_age = (start_date.year - birth_date.year) * 12 + start_date.month - birth_date.month - (start_date.day < start_date.day)
        return start_months_age

    @staticmethod
    def get_current_simulation():
        """
        Runs the entire retirement simulation using DB parameters (Single Source of Truth).
        Calculates lifetime monthly contribution using total_time_months and PV=0.
        Calculates course-corrected monthly contribution using actual database invested capital as PV.
        Returns a dictionary containing all computed parameters (DRY-compliant).
        """
        config = SimulationService.get_configuration()
        if not config:
            return None
            
        today = datetime.date.today()
        birth_date = datetime.datetime.strptime(config[BIRTH_DATE], "%Y-%m-%d").date() if isinstance(config[BIRTH_DATE], str) else config[BIRTH_DATE]
        
        months_age = (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day)
        current_age = months_age / 12
        
        start_months_age = SimulationService.get_initial_investment_age(birth_date)
        start_age_years = start_months_age / 12
        
        total_time_months = max(0, config[RETIREMENT_AGE] * 12 - start_months_age)
        remaining_time_months = max(0, config[RETIREMENT_AGE] * 12 - months_age)
        
        # Calculate target income dynamically based on selection (Multiplier or Fixed Amount)
        income_type = config.get(DESIRED_INCOME_TYPE, INCOME_TYPE_MULTIPLIER)
        if income_type == INCOME_TYPE_MULTIPLIER:
            target_monthly_income = config[DESIRED_INCOME_MW] * config[MW_VALUE]
        else: # FIXED
            target_monthly_income = config[DESIRED_INCOME_FIXED]
            
        monthly_interest_rate = (1 + config[ANNUAL_INTEREST_RATE] / 100) ** (1 / 12) - 1
        target_equity = target_monthly_income / monthly_interest_rate if monthly_interest_rate > 0 else 0.0
        
        from services.assets_service import AssetService
        df_pos = AssetService.calculate_positions()
        total_invested = float(df_pos['invested_amount'].sum()) if not df_pos.empty else 0.0

        def pmt_annuity_due(rate, nper, pv, fv):
            """Helper function to calculate PMT Annuity Due (Excel type=1) with correct financial signs."""
            if nper <= 0 or rate <= 0:
                return 0.0
            interest_factor = (1 + rate) ** nper
            denominator = ((interest_factor - 1) / rate) * (1 + rate)
            val = (fv - pv * interest_factor) / denominator if denominator > 0 else 0.0
            return max(0.0, val)

        required_monthly_contribution = pmt_annuity_due(
            monthly_interest_rate, 
            total_time_months, 
            0.0, 
            target_equity
        )

        updated_monthly_contribution = pmt_annuity_due(
            monthly_interest_rate, 
            remaining_time_months, 
            total_invested, 
            target_equity
        )
            
        return {
            "current_age": current_age,
            "start_age_years": start_age_years,
            "total_time_months": total_time_months,
            "remaining_time_months": remaining_time_months,
            "target_monthly_income": target_monthly_income,
            "monthly_interest_rate": monthly_interest_rate,
            "target_equity": target_equity,
            "required_monthly_contribution": required_monthly_contribution,
            "updated_monthly_contribution": updated_monthly_contribution,
            "mw_value": config[MW_VALUE],
            "total_invested": total_invested,
            "retirement_age": config[RETIREMENT_AGE],
            "desired_income_mw": config[DESIRED_INCOME_MW],
            "desired_income_fixed": config[DESIRED_INCOME_FIXED],
            "desired_income_type": config[DESIRED_INCOME_TYPE],
            "annual_interest_rate": config[ANNUAL_INTEREST_RATE]
        }

    @staticmethod
    def get_updated_required_contribution():
        """Returns the updated monthly contribution dynamically for the dashboard's planning metrics."""
        sim = SimulationService.get_current_simulation()
        return sim["updated_monthly_contribution"] if sim else 0.0

    @staticmethod
    def get_required_contribution():
        """Returns the lifetime required monthly contribution dynamically."""
        sim = SimulationService.get_current_simulation()
        return sim["required_monthly_contribution"] if sim else 0.0

    @staticmethod
    def build_projection_dataframe(current_age, simulation_months, initial_equity, required_monthly_contribution, monthly_interest_rate, target_equity):
        """
        Projects current actual equity + future contributions growing over the remaining months.
        Starts from today (current_age) until retirement.
        """
        if simulation_months <= 0:
            return pd.DataFrame()
            
        months_array = np.arange(1, simulation_months + 1)
        ages_array = current_age + (months_array / 12)
        
        cumulative_invested = initial_equity + months_array * required_monthly_contribution
        
        interest_factors = (1 + monthly_interest_rate)**months_array
        projected_equity = initial_equity * interest_factors + \
                           required_monthly_contribution * (1 + monthly_interest_rate) * ((interest_factors - 1) / monthly_interest_rate)
                           
        cumulative_interest = projected_equity - cumulative_invested
        
        return pd.DataFrame({
            "Idade": ages_array,
            "Patrimônio Projetado": projected_equity,
            "Valor Aportado Acumulado": cumulative_invested,
            "Juros Acumulado (Rendimento)": cumulative_interest,
            "Meta": target_equity
        })

    @staticmethod
    def build_monthly_cashflow_dataframe(current_age, simulation_months, initial_equity, required_monthly_contribution, monthly_interest_rate):
        """
        Calculates monthly cashflow values: a constant monthly contribution
        and a growing monthly interest generated by the compounded equity.
        """
        if simulation_months <= 0:
            return pd.DataFrame()
            
        ages = []
        contributions = []
        interests = []
        
        last_equity = initial_equity
        for m in range(1, simulation_months + 1):
            age = current_age + (m / 12)
            period_interest = last_equity * monthly_interest_rate
            
            ages.append(age)
            contributions.append(required_monthly_contribution)
            interests.append(period_interest)
            
            last_equity = (last_equity + required_monthly_contribution) * (1 + monthly_interest_rate)
            
        return pd.DataFrame({
            "Idade": ages,
            "Aporte Mensal": contributions,
            "Juros Mensal": interests
        })

    @staticmethod
    def calculate_planned_historical_evolution(df_evolution: pd.DataFrame, monthly_contribution: float, monthly_interest_rate: float) -> pd.DataFrame:
        """
        Centralized, DRY-compliant mathematical projection for historical planned curves.
        Generates linear accumulation of planned investments and compound interest.
        """
        planned_invested = []
        planned_dividends = []
        
        last_equity = 0.0
        last_dividends = 0.0
        
        for idx, row in df_evolution.iterrows():
            period_interest = last_equity * monthly_interest_rate
            next_equity = last_equity + monthly_contribution
            next_dividends = last_dividends + period_interest
            
            planned_invested.append(next_equity)
            planned_dividends.append(next_dividends)
            
            last_equity = next_equity
            last_dividends = next_dividends
            
        df_evolution['planned_invested'] = planned_invested
        df_evolution['planned_dividends'] = planned_dividends
        return df_evolution

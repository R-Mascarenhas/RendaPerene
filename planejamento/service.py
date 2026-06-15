import datetime
import numpy as np
import pandas as pd
from core.database import db

class SimulationService:
    """Domain Service for financial independence calculations and compound interest."""

    @staticmethod
    def get_configuration():
        """Fetches the planning configuration from the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input FROM planning_configuration WHERE id = 1")
            row = cursor.fetchone()
            if row:
                config = {
                    "birth_date": row[0],
                    "retirement_age": row[1],
                    "desired_income_mw": row[2],
                    "annual_interest_rate": row[3],
                    "mw_value": row[4],
                    "initial_equity_input": row[5]
                }
                return config
            return None
        except Exception:
            return None
        finally:
            conn.close()

    @staticmethod
    def save_configuration(birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input):
        """Saves or updates the planning configuration in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM planning_configuration WHERE id = 1")
            if cursor.fetchone():
                cursor.execute('''
                    UPDATE planning_configuration
                    SET birth_date = ?, retirement_age = ?, desired_income_mw = ?, annual_interest_rate = ?, mw_value = ?, initial_equity_input = ?
                    WHERE id = 1
                ''', (birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input))
            else:
                cursor.execute('''
                    INSERT INTO planning_configuration (id, birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input)
                    VALUES (1, ?, ?, ?, ?, ?, ?)
                ''', (birth_date, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def calculate_simulation_params(months_age, retirement_age, desired_income_mw, annual_interest_rate, mw_value, initial_equity_input):
        """
        Calculates simulation parameters using PMT Annuity Due (Type = 1) matching Excel's `=PMT(rate, nper, pv, -fv, 1)`.
        Uses internal months_age to find the exact target simulation period.
        """
        simulation_months = max(0, retirement_age * 12 - months_age)
        target_monthly_income = desired_income_mw * mw_value
        monthly_interest_rate = (1 + annual_interest_rate / 100) ** (1 / 12) - 1
        target_equity = target_monthly_income / monthly_interest_rate if monthly_interest_rate > 0 else 0.0

        if simulation_months > 0 and monthly_interest_rate > 0:
            interest_factor = (1 + monthly_interest_rate) ** simulation_months
            
            # PMT Annuity Due formula: payments at start of month (Excel type = 1)
            # Math: PMT = [FV - PV * (1+r)^n] * r / [((1+r)^n - 1) * (1+r)]
            numerator = target_equity - initial_equity_input * interest_factor
            denominator = ((interest_factor - 1) / monthly_interest_rate) * (1 + monthly_interest_rate)
            required_monthly_contribution = numerator / denominator if denominator > 0 else 0.0
            required_monthly_contribution = max(0.0, required_monthly_contribution)
        else:
            required_monthly_contribution = 0.0

        return simulation_months, target_monthly_income, monthly_interest_rate, target_equity, required_monthly_contribution

    @staticmethod
    def get_initial_investment_age(birth_date):
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(date) FROM transactions")
        min_date_res = cursor.fetchone()
        min_date_str = min_date_res[0] if min_date_res and min_date_res[0] is not None else "2021-04-30"
        conn.close()

        start_date = datetime.datetime.strptime(min_date_str, "%Y-%m-%d").date()
        
        # Calculate start age in complete years
        start_age = start_date.year - birth_date.year - ((start_date.month, start_date.day) < (birth_date.month, birth_date.day))
        return start_age

    @staticmethod
    def build_projection_dataframe(current_age, simulation_months, initial_equity, required_monthly_contribution, monthly_interest_rate, target_equity):
        if simulation_months <= 0:
            return pd.DataFrame()
            
        months_array = np.arange(1, simulation_months + 1)
        ages_array = current_age + (months_array / 12)
        
        cumulative_invested = initial_equity + months_array * required_monthly_contribution
        
        # Balance projection using Annuity Due compound interest (payment at start of month)
        # Math: FV_n = PV * (1+r)^n + PMT * (1+r) * [((1+r)^n - 1) / r]
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

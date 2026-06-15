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
    def get_initial_investment_age(birth_date):
        """Returns the exact age in months when the first investment was made."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(date) FROM transactions")
        min_date_res = cursor.fetchone()
        min_date_str = min_date_res[0] if min_date_res and min_date_res[0] is not None else "2021-04-30"
        conn.close()

        start_date = datetime.datetime.strptime(min_date_str, "%Y-%m-%d").date()
        
        # Calculate exact age in months when investment started
        start_months_age = (start_date.year - birth_date.year) * 12 + start_date.month - birth_date.month - (start_date.day < birth_date.day)
        return start_months_age

    @staticmethod
    def get_current_simulation():
        """
        Runs the entire retirement simulation using DB parameters (Single Source of Truth).
        Calculates lifetime monthly contribution using total_time_months and PV=0.
        Returns a dictionary containing all computed parameters (DRY-compliant).
        """
        config = SimulationService.get_configuration()
        if not config:
            return None
            
        today = datetime.date.today()
        birth_date = datetime.datetime.strptime(config['birth_date'], "%Y-%m-%d").date() if isinstance(config['birth_date'], str) else config['birth_date']
        
        # Exact current age in months and years (for UI display)
        months_age = (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day)
        current_age = months_age / 12
        
        # Exact age in months when the investment journey started (first transaction)
        start_months_age = SimulationService.get_initial_investment_age(birth_date)
        start_age_years = start_months_age / 12
        
        # Total Time: months from first investment to retirement age (Lifetime Timeline)
        total_time_months = max(0, config['retirement_age'] * 12 - start_months_age)
        
        # Remaining Time: months from today to retirement age (Current Timeline)
        remaining_time_months = max(0, config['retirement_age'] * 12 - months_age)
        
        target_monthly_income = config['desired_income_mw'] * config['mw_value']
        monthly_interest_rate = (1 + config['annual_interest_rate'] / 100) ** (1 / 12) - 1
        target_equity = target_monthly_income / monthly_interest_rate if monthly_interest_rate > 0 else 0.0
        
        # Lifetime Required Contribution (Excel PMT Annuity Due, type=1, pv=0)
        # Formula: =PMT(monthly_interest_rate, total_time_months, 0, -target_equity, 1)
        if total_time_months > 0 and monthly_interest_rate > 0:
            interest_factor = (1 + monthly_interest_rate) ** total_time_months
            denominator = ((interest_factor - 1) / monthly_interest_rate) * (1 + monthly_interest_rate)
            required_monthly_contribution = target_equity / denominator if denominator > 0 else 0.0
            required_monthly_contribution = max(0.0, required_monthly_contribution)
        else:
            required_monthly_contribution = 0.0
            
        # Updated Monthly Contribution (Course-corrected starting today, using current equity as PV)
        # Formula: =PMT(monthly_interest_rate, remaining_time_months, -initial_equity_input, target_equity, 1)
        if remaining_time_months > 0 and monthly_interest_rate > 0:
            interest_factor_rem = (1 + monthly_interest_rate) ** remaining_time_months
            numerator_rem = target_equity - config['initial_equity_input'] * interest_factor_rem
            denominator_rem = ((interest_factor_rem - 1) / monthly_interest_rate) * (1 + monthly_interest_rate)
            updated_monthly_contribution = numerator_rem / denominator_rem if denominator_rem > 0 else 0.0
            updated_monthly_contribution = max(0.0, updated_monthly_contribution)
        else:
            updated_monthly_contribution = 0.0
            
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
            "mw_value": config['mw_value'],
            "initial_equity_input": config['initial_equity_input'],
            "retirement_age": config['retirement_age'],
            "desired_income_mw": config['desired_income_mw'],
            "annual_interest_rate": config['annual_interest_rate']
        }

    @staticmethod
    def get_current_required_contribution():
        """Returns the updated monthly contribution dynamically for the dashboard's planning metrics."""
        sim = SimulationService.get_current_simulation()
        return sim["updated_monthly_contribution"] if sim else 0.0

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

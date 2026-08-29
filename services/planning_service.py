import datetime

import numpy as np
import pandas as pd

from core.constants import (
    ANNUAL_INTEREST_RATE,
    BIRTH_DATE,
    DESIRED_INCOME_FIXED,
    DESIRED_INCOME_MW,
    DESIRED_INCOME_TYPE,
    INCOME_TYPE_MULTIPLIER,
    INITIAL_EQUITY_INPUT,
    MW_VALUE,
    PLANNING_START_DATE,
    RETIREMENT_AGE,
)
from core.daos.planning_dao import PlanningDAO
from core.ports import PlanningConfigPort, PortfolioProviderPort, hybridmethod


class SimulationService:
    """Domain Service for financial independence calculations and compound interest."""

    def __init__(
        self,
        planning_repo: PlanningConfigPort = None,
        portfolio_provider: PortfolioProviderPort = None,
    ):
        if isinstance(planning_repo, type):
            planning_repo = planning_repo()
        self._planning_repo = planning_repo or PlanningDAO()
        self._portfolio_provider = portfolio_provider

    # Default instance for backwards compatibility in presentation layers
    _default_instance = None

    @classmethod
    def get_default(cls):
        if cls._default_instance is None:
            cls._default_instance = cls()
        return cls._default_instance

    @classmethod
    def set_adapters(
        cls,
        planning_repo: PlanningConfigPort = None,
        portfolio_provider: PortfolioProviderPort = None,
    ):
        """Dynamic dependency injection mechanism for testing and custom environment mocks."""
        inst = cls.get_default()
        if planning_repo is not None:
            if isinstance(planning_repo, type):
                planning_repo = planning_repo()
            inst._planning_repo = planning_repo
        if portfolio_provider is not None:
            inst._portfolio_provider = portfolio_provider

    @hybridmethod
    def get_configuration(self):
        """Fetches the planning configuration from the database."""
        return self._planning_repo.get_configuration()

    @hybridmethod
    def save_configuration(
        self,
        birth_date,
        retirement_age,
        desired_income_mw,
        annual_interest_rate,
        mw_value,
        initial_equity_input,
        desired_income_type="MULTIPLIER",
        desired_income_fixed=10000.0,
        ceiling_model_selection="Bazin Clássico",
        bazin_target_yield=6.0,
        bazin_target_spread=3.0,
        planning_start_date=None,
    ):
        """Saves or updates the planning configuration in the database."""
        self._planning_repo.save_configuration(
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
        )

    @hybridmethod
    def get_initial_investment_age(self, birth_date, config=None):
        """Returns the exact age in months when the first investment was made."""
        if config is not None and config.get(PLANNING_START_DATE) is not None:
            min_date_str = config[PLANNING_START_DATE]
        else:
            min_date_str = self._planning_repo.get_min_transaction_date()

        start_date = datetime.datetime.strptime(min_date_str, "%Y-%m-%d").date()

        start_months_age = (
            (start_date.year - birth_date.year) * 12
            + start_date.month
            - birth_date.month
            - (start_date.day < birth_date.day)
        )
        return start_months_age

    @staticmethod
    def pmt_annuity_due(rate, nper, pv, fv):
        """Helper function to calculate PMT Annuity Due (Excel type=1) with correct financial signs."""
        if nper <= 0 or rate <= 0:
            return 0.0
        interest_factor = (1 + rate) ** nper
        denominator = ((interest_factor - 1) / rate) * (1 + rate)
        val = (fv - pv * interest_factor) / denominator if denominator > 0 else 0.0
        return max(0.0, val)

    @hybridmethod
    def get_current_simulation(self):
        """
        Runs the entire retirement simulation using DB parameters (Single Source of Truth).
        Calculates lifetime monthly contribution using total_time_months and PV=0.
        Calculates course-corrected monthly contribution using actual database invested capital as PV.
        Returns a dictionary containing all computed parameters (DRY-compliant).
        """
        config = self.get_configuration()
        if not config:
            return None

        today = datetime.date.today()
        birth_date = (
            datetime.datetime.strptime(config[BIRTH_DATE], "%Y-%m-%d").date()
            if isinstance(config[BIRTH_DATE], str)
            else config[BIRTH_DATE]
        )

        months_age = (
            (today.year - birth_date.year) * 12
            + today.month
            - birth_date.month
            - (today.day < birth_date.day)
        )
        current_age = months_age / 12

        start_months_age = self.get_initial_investment_age(birth_date, config)
        start_age_years = start_months_age / 12

        total_time_months = max(0, config[RETIREMENT_AGE] * 12 - start_months_age)
        remaining_time_months = max(0, config[RETIREMENT_AGE] * 12 - months_age)

        # Calculate target income dynamically based on selection (Multiplier or Fixed Amount)
        income_type = config.get(DESIRED_INCOME_TYPE, INCOME_TYPE_MULTIPLIER)
        if income_type == INCOME_TYPE_MULTIPLIER:
            target_monthly_income = config[DESIRED_INCOME_MW] * config[MW_VALUE]
        else:  # FIXED
            target_monthly_income = config[DESIRED_INCOME_FIXED]

        monthly_interest_rate = (1 + config[ANNUAL_INTEREST_RATE] / 100) ** (1 / 12) - 1
        target_equity = (
            target_monthly_income / monthly_interest_rate if monthly_interest_rate > 0 else 0.0
        )

        if self._portfolio_provider is None:
            raise RuntimeError("Portfolio provider port is not configured on SimulationService.")

        df_pos = self._portfolio_provider.calculate_positions(
            start_date=config.get(PLANNING_START_DATE)
        )
        total_invested = float(df_pos["invested_amount"].sum()) if not df_pos.empty else 0.0

        # Get initial equity input from database configuration (only used if planning start date is specified)
        initial_equity_input = (
            float(config[INITIAL_EQUITY_INPUT])
            if config.get(PLANNING_START_DATE) is not None
            else 0.0
        )

        required_monthly_contribution = self.pmt_annuity_due(
            monthly_interest_rate, total_time_months, initial_equity_input, target_equity
        )

        updated_monthly_contribution = self.pmt_annuity_due(
            monthly_interest_rate,
            remaining_time_months,
            total_invested + initial_equity_input,
            target_equity,
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
            "total_invested": total_invested + initial_equity_input,
            "initial_equity_input": initial_equity_input,
            "retirement_age": config[RETIREMENT_AGE],
            "desired_income_mw": config[DESIRED_INCOME_MW],
            "desired_income_fixed": config[DESIRED_INCOME_FIXED],
            "desired_income_type": config[DESIRED_INCOME_TYPE],
            "annual_interest_rate": config[ANNUAL_INTEREST_RATE],
            "planning_start_date": config.get(PLANNING_START_DATE),
        }

    @hybridmethod
    def get_updated_required_contribution(self):
        """Returns the updated monthly contribution dynamically for the dashboard's planning metrics."""
        sim = self.get_current_simulation()
        return sim["updated_monthly_contribution"] if sim else 0.0

    @hybridmethod
    def get_required_contribution(self):
        """Returns the lifetime required monthly contribution dynamically."""
        sim = self.get_current_simulation()
        return sim["required_monthly_contribution"] if sim else 0.0

    @staticmethod
    def calculate_planned_dividends_for_year(projection: pd.DataFrame, year: int) -> float:
        """Extracts one calendar year's planned dividends from a cumulative projection."""
        from core.constants import MONTH_STR, PLANNED_DIVIDENDS

        if projection.empty or MONTH_STR not in projection or PLANNED_DIVIDENDS not in projection:
            return 0.0

        ordered = projection.sort_values(MONTH_STR)
        year_prefix = f"{year}-"
        year_rows = ordered[ordered[MONTH_STR].str.startswith(year_prefix)]
        if year_rows.empty:
            return 0.0

        prior_rows = ordered[ordered[MONTH_STR] < f"{year}-01"]
        starting_value = (
            float(prior_rows.iloc[-1][PLANNED_DIVIDENDS]) if not prior_rows.empty else 0.0
        )
        ending_value = float(year_rows.iloc[-1][PLANNED_DIVIDENDS])
        return max(0.0, ending_value - starting_value)

    @hybridmethod
    def get_planned_annual_dividends(self, year: int | None = None) -> float:
        """Returns planned dividends generated during one calendar year."""
        selected_year = year or datetime.date.today().year
        projection = self.get_projection_chart_dataset()
        return self.calculate_planned_dividends_for_year(projection, selected_year)

    @staticmethod
    def build_projection_dataframe(
        current_age,
        simulation_months,
        initial_equity,
        required_monthly_contribution,
        monthly_interest_rate,
        target_equity,
    ):
        """
        Projects current actual equity + future contributions growing over the remaining months.
        Starts from today (current_age) until retirement.
        """
        if simulation_months <= 0:
            return pd.DataFrame()

        months_array = np.arange(1, simulation_months + 1)
        ages_array = current_age + (months_array / 12)

        cumulative_invested = initial_equity + months_array * required_monthly_contribution

        interest_factors = (1 + monthly_interest_rate) ** months_array
        projected_equity = initial_equity * interest_factors + required_monthly_contribution * (
            1 + monthly_interest_rate
        ) * ((interest_factors - 1) / monthly_interest_rate)

        cumulative_interest = projected_equity - cumulative_invested

        return pd.DataFrame(
            {
                "Idade": ages_array,
                "Patrimônio Projetado": projected_equity,
                "Valor Aportado Acumulado": cumulative_invested,
                "Juros Acumulado (Rendimento)": cumulative_interest,
                "Meta": target_equity,
            }
        )

    @staticmethod
    def build_monthly_cashflow_dataframe(
        current_age,
        simulation_months,
        initial_equity,
        required_monthly_contribution,
        monthly_interest_rate,
    ):
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

            last_equity = (last_equity + required_monthly_contribution) * (
                1 + monthly_interest_rate
            )

        return pd.DataFrame(
            {"Idade": ages, "Aporte Mensal": contributions, "Juros Mensal": interests}
        )

    @staticmethod
    def calculate_planned_historical_evolution(
        df_evolution: pd.DataFrame,
        monthly_contribution: float,
        monthly_interest_rate: float,
        initial_equity: float = 0.0,
    ) -> pd.DataFrame:
        """
        Centralized, DRY-compliant mathematical projection for historical planned curves.
        Generates linear accumulation of planned investments and compound interest.
        """
        planned_invested = []
        planned_dividends = []

        last_equity = initial_equity
        last_dividends = 0.0

        for _ in range(len(df_evolution)):
            period_interest = last_equity * monthly_interest_rate
            next_equity = last_equity + monthly_contribution
            next_dividends = last_dividends + period_interest

            planned_invested.append(next_equity)
            planned_dividends.append(next_dividends)

            last_equity = next_equity
            last_dividends = next_dividends

        df_evolution["planned_invested"] = planned_invested
        df_evolution["planned_dividends"] = planned_dividends
        return df_evolution

    @hybridmethod
    def get_projection_chart_dataset(self, extrapolation_months: int = 12) -> pd.DataFrame:
        """
        Fetches historical portfolio portfolio evolution and prepares future extrapolation (trendlines,
        planned curves, etc.) for the comparative charts, returning a single display DataFrame.
        """
        from core.constants import (
            CUMULATIVE_DIVIDENDS,
            CUMULATIVE_INVESTED,
            MONTH_DISPLAY,
            MONTH_STR,
        )
        from core.utils.formatter import Formatter
        from core.utils.trendlines import (
            LinearMomentumTrendlineStrategy,
            PolynomialTrendlineStrategy,
            TrendlineCalculator,
        )

        if self._portfolio_provider is None:
            raise RuntimeError("Portfolio provider port is not configured on SimulationService.")

        config = self.get_configuration()
        start_date_val = config.get(PLANNING_START_DATE) if config else None
        df_evolution = self._portfolio_provider.calculate_historical_evolution(
            start_date=start_date_val
        )
        if df_evolution.empty:
            return pd.DataFrame()

        df_evolution = df_evolution.sort_values(by=MONTH_STR).reset_index(drop=True)
        start_date_str = df_evolution.loc[0, MONTH_STR] + "-01"
        start_date = pd.to_datetime(start_date_str).replace(day=1)

        end_date = datetime.date.today() + datetime.timedelta(days=365)

        date_range_extrap = pd.date_range(start=start_date, end=end_date, freq="MS")
        all_months_extrap = date_range_extrap.strftime("%Y-%m").tolist()
        df_extrap = pd.DataFrame({MONTH_STR: all_months_extrap})

        df_extrap = df_extrap.merge(
            df_evolution[[MONTH_STR, CUMULATIVE_INVESTED, CUMULATIVE_DIVIDENDS]],
            on=MONTH_STR,
            how="left",
        )

        df_extrap[MONTH_DISPLAY] = df_extrap[MONTH_STR].apply(Formatter.format_month_year)

        # 2. GENERATE CONTINUOUS PLANNED CURVES
        config = self.get_configuration()
        from core.constants import ANNUAL_INTEREST_RATE

        if config:
            annual_interest_rate_val = float(config[ANNUAL_INTEREST_RATE])
            monthly_interest_rate = (1 + annual_interest_rate_val / 100) ** (1 / 12) - 1
            initial_equity = (
                float(config[INITIAL_EQUITY_INPUT])
                if config.get(PLANNING_START_DATE) is not None
                else 0.0
            )
        else:
            monthly_interest_rate = (1 + 6.0 / 100) ** (1 / 12) - 1
            initial_equity = 0.0

        monthly_contribution = self.get_required_contribution()

        df_extrap = self.calculate_planned_historical_evolution(
            df_extrap, monthly_contribution, monthly_interest_rate, initial_equity=initial_equity
        )

        # 3. COMPUTE EXTRAPOLATION TRENDLINES
        df_extrap["trend_dividends"] = TrendlineCalculator.calculate_trend(
            df_extrap,
            CUMULATIVE_DIVIDENDS,
            PolynomialTrendlineStrategy(deg=2),
            extrapolate_periods=extrapolation_months,
        )
        df_extrap["trend_invested"] = TrendlineCalculator.calculate_trend(
            df_extrap,
            CUMULATIVE_INVESTED,
            LinearMomentumTrendlineStrategy(window_months=extrapolation_months),
            extrapolate_periods=extrapolation_months,
        )

        return df_extrap

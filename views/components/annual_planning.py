import streamlit as st

from core.strings import (
    MSG_ALL_GOALS_MET,
    MSG_ANNUAL_PLANNING_TITLE,
    MSG_REMAINING_TO_BUY,
    MSG_YTD_CONTRIBUTIONS,
)
from core.utils.formatter import Formatter
from services.assets_service import AssetService
from services.planning_service import SimulationService


class AnnualPlanningWidget:
    """Displays the progress towards your annual out-of-pocket contribution target."""

    def render(self, current_year, ytd_dividends):
        ytd_contributions = AssetService.get_ytd_contributions(current_year)

        # Pull planned contribution dynamically from Simulation Service (clean DRY pattern)
        required_monthly_contribution = SimulationService.get_updated_required_contribution()
        annual_salary_goal = required_monthly_contribution * 12
        total_annual_goal = annual_salary_goal + ytd_dividends

        st.subheader(MSG_ANNUAL_PLANNING_TITLE.format(year=current_year))
        plan_col1, plan_col2, plan_col3 = st.columns(3)
        plan_col1.metric(
            "Meta de Aporte do Salário (Ano)",
            Formatter.format_currency(annual_salary_goal),
            "Baseado no seu Planejamento",
        )
        plan_col2.metric(
            "Proventos a Reinvestir (YTD)",
            Formatter.format_currency(ytd_dividends),
            "Soma dos dividendos recebidos",
        )
        plan_col3.metric(
            "Meta Total Corrente (Aporte + Reinvestimento)",
            Formatter.format_currency(total_annual_goal),
            "Meta de Compras na B3",
        )

        percent_achieved = (ytd_contributions / total_annual_goal) if total_annual_goal > 0 else 0.0
        remaining_to_buy = max(0.0, total_annual_goal - ytd_contributions)

        st.markdown(
            MSG_YTD_CONTRIBUTIONS.format(
                value=Formatter.format_currency(ytd_contributions), pct=percent_achieved * 100
            )
        )
        if remaining_to_buy > 0:
            st.markdown(
                MSG_REMAINING_TO_BUY.format(value=Formatter.format_currency(remaining_to_buy))
            )
        else:
            st.markdown(MSG_ALL_GOALS_MET)

        st.progress(min(1.0, percent_achieved))

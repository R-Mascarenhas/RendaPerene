import streamlit as st

from core.strings import (
    MSG_ALL_GOALS_MET,
    MSG_ANNUAL_PLANNING_TITLE,
    MSG_REMAINING_TO_BUY,
    MSG_YTD_CONTRIBUTIONS,
)
from core.utils.formatter import Formatter
from services.goals_service import GoalService
from views.components.goal_progress import GoalProgressBar


class AnnualPlanningWidget:
    """Displays the progress towards your annual out-of-pocket contribution target."""

    def render(self, current_year, ytd_dividends):
        goal = GoalService.get_annual_investment_goal(current_year, ytd_dividends)

        st.subheader(MSG_ANNUAL_PLANNING_TITLE.format(year=current_year))
        metric_columns = st.columns(3 if goal["reinvestment_enabled"] else 2)
        plan_col1 = metric_columns[0]
        plan_col1.metric(
            "Meta de Aporte do Salário (Ano)",
            Formatter.format_currency(goal["annual_salary_goal"]),
            "Baseado no seu Planejamento",
        )
        if goal["reinvestment_enabled"]:
            metric_columns[1].metric(
                "Proventos a Reinvestir (YTD)",
                Formatter.format_currency(goal["reinvestment_goal"]),
                "Soma dos dividendos recebidos",
            )
        metric_columns[-1].metric(
            "Meta Total Corrente (Aporte + Reinvestimento)"
            if goal["reinvestment_enabled"]
            else "Meta Anual de Aportes",
            Formatter.format_currency(goal["total_goal"]),
            "Meta de Compras na B3",
        )

        st.markdown(
            MSG_YTD_CONTRIBUTIONS.format(
                value=Formatter.format_currency(goal["ytd_contributions"]),
                pct=goal["progress_percentage"],
            )
        )
        if goal["remaining_to_invest"] > 0:
            st.markdown(
                MSG_REMAINING_TO_BUY.format(
                    value=Formatter.format_currency(goal["remaining_to_invest"])
                )
            )
        else:
            st.markdown(MSG_ALL_GOALS_MET)

        GoalProgressBar.render(goal["progress_percentage"])

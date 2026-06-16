import streamlit as st
from core.utils import Formatter
from dashboard.dashboard_service import DashboardService
from planning.planning_service import SimulationService

class AnnualPlanningWidget:
    """Displays the progress towards your annual out-of-pocket contribution target."""

    def render(self, current_year, ytd_dividends):
        ytd_contributions = DashboardService.get_ytd_contributions(current_year)

        # Pull planned contribution dynamically from Simulation Service (clean DRY pattern)
        required_monthly_contribution = SimulationService.get_updated_required_contribution()
        annual_salary_goal = required_monthly_contribution * 12
        total_annual_goal = annual_salary_goal + ytd_dividends

        st.subheader(f"📅 Planejamento Anual de Investimentos ({current_year})")
        plan_col1, plan_col2, plan_col3 = st.columns(3)
        plan_col1.metric("Meta de Aporte do Salário (Ano)", Formatter.format_currency(annual_salary_goal), "Baseado no seu Planejamento")
        plan_col2.metric("Proventos a Reinvestir (YTD)", Formatter.format_currency(ytd_dividends), "Soma dos dividendos recebidos")
        plan_col3.metric("Meta Total Corrente (Aporte + Reinvestimento)", Formatter.format_currency(total_annual_goal), "Meta de Compras na B3")

        percent_achieved = (ytd_contributions / total_annual_goal) if total_annual_goal > 0 else 0.0
        remaining_to_buy = max(0.0, total_annual_goal - ytd_contributions)

        st.markdown(f"**Total Comprado (Aportado) este ano na B3:** {Formatter.format_currency(ytd_contributions)} ({percent_achieved*100:.1f}%)")
        if remaining_to_buy > 0:
            st.markdown(f"🔴 **Falta comprar/reinvestir na B3 para bater a meta:** {Formatter.format_currency(remaining_to_buy)}")
        else:
            st.markdown("🎉 **Excelente! Todos os aportes mínimos e proventos do ano foram totalmente investidos e reinvestidos na B3!**")

        st.progress(min(1.0, percent_achieved))

import streamlit as st
import datetime
from dashboard.dashboard_service import DashboardService
from dashboard.components.annual_planning import AnnualPlanningWidget
from dashboard.components.patrimony_summary import PatrimonySummaryWidget
from dashboard.components.detailed_holdings import DetailedHoldingsWidget
from dashboard.components.charts import DashboardCharts

class DashboardView:
    """Clean orchestrator for the Dashboard tab layout, delegating to SRP components."""

    def render(self):
        # 1. Fetch consolidated positions from service
        df_positions = DashboardService.calculate_positions()
        
        today = datetime.date.today()
        current_year = today.year
        ytd_dividends = df_positions['ytd_dividends'].sum() if not df_positions.empty else 0.0

        # 2. Render target annual progress bar (At the very top)
        AnnualPlanningWidget().render(current_year, ytd_dividends)

        st.markdown("---")
        st.header("Resumo Patrimonial")

        if df_positions.empty:
            st.info("Sua carteira está vazia. Vá até a aba 'Lançamentos' para inserir seus ativos ou importar seu extrato da B3!")
        else:
            # 3. Render the 5 core KPI metrics (Patrimony, Capital, YoY, YoC, Dividends)
            PatrimonySummaryWidget().render(df_positions)
            
            # 4. Render all interactive Plotly figures
            DashboardCharts().render(df_positions)
            
            # 5. Render detailed holdings dataframe grid (At the bottom)
            DetailedHoldingsWidget().render(df_positions)

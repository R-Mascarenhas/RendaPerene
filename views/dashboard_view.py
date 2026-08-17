import datetime

import streamlit as st

from core.strings import MSG_PORTFOLIO_EMPTY
from services.assets_service import AssetService
from views.components.annual_planning import AnnualPlanningWidget
from views.components.charts import DashboardCharts
from views.components.detailed_holdings import DetailedHoldingsWidget
from views.components.patrimony_summary import PatrimonySummaryWidget


class DashboardView:
    """Clean orchestrator for the Dashboard tab layout, delegating to SRP components."""

    def render(self):
        # 1. Fetch consolidated positions from service
        df_positions = AssetService.calculate_positions()

        today = datetime.date.today()
        current_year = today.year
        ytd_dividends = df_positions["ytd_dividends"].sum() if not df_positions.empty else 0.0

        # 2. Render target annual progress bar (At the very top)
        AnnualPlanningWidget().render(current_year, ytd_dividends)

        st.markdown("---")
        st.header("Resumo Patrimonial")

        if df_positions.empty:
            st.info(MSG_PORTFOLIO_EMPTY)
        else:
            # 3. Render the 5 core KPI metrics (Patrimony, Capital, YoY, YoC, Dividends)
            PatrimonySummaryWidget().render(df_positions)

            # 4. Render all interactive Plotly figures
            DashboardCharts().render(df_positions)

            # 5. Render detailed holdings dataframe grid (At the bottom)
            DetailedHoldingsWidget().render(df_positions)

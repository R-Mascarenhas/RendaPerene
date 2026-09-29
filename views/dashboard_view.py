import datetime

import streamlit as st

from core.performance import instrument_screen, measure_navigation
from core.strings import MSG_PORTFOLIO_EMPTY
from views.cached_market_data import StreamlitCachedPortfolioData
from views.components.accumulation_goals import AccumulationGoalProgressWidget
from views.components.annual_planning import AnnualPlanningWidget
from views.components.charts import DashboardCharts
from views.components.detailed_holdings import DetailedHoldingsWidget
from views.components.patrimony_summary import PatrimonySummaryWidget
from views.components.portfolio_activity import PortfolioActivityWidget


class DashboardView:
    """Clean orchestrator for the Dashboard tab layout, delegating to SRP components."""

    @instrument_screen("dashboard")
    def render(self):
        # 1. Fetch consolidated positions from service
        with measure_navigation("dashboard", "local_projection"):
            df_positions = StreamlitCachedPortfolioData.calculate_positions()

        today = datetime.date.today()
        current_year = today.year
        ytd_dividends = df_positions["ytd_dividends"].sum() if not df_positions.empty else 0.0

        # 2. Render target annual progress bar (At the very top)
        with measure_navigation("dashboard", "annual_goal"):
            AnnualPlanningWidget().render(current_year, ytd_dividends)
        with measure_navigation("dashboard", "accumulation_goals"):
            AccumulationGoalProgressWidget().render()

        st.markdown("---")
        st.header("Resumo Patrimonial")

        if df_positions.empty:
            st.info(MSG_PORTFOLIO_EMPTY)
        else:
            # 3. Render the 5 core KPI metrics (Patrimony, Capital, YoY, YoC, Dividends)
            with measure_navigation("dashboard", "patrimony_summary"):
                PatrimonySummaryWidget().render(df_positions)

            # 4. Render all interactive Plotly figures
            with measure_navigation("dashboard", "charts"):
                DashboardCharts().render(df_positions)

            # 5. Render detailed holdings dataframe grid (At the bottom)
            with measure_navigation("dashboard", "detailed_holdings"):
                DetailedHoldingsWidget().render(df_positions)

        with measure_navigation("dashboard", "recent_activity"):
            PortfolioActivityWidget().render()

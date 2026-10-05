import datetime

import streamlit as st

from core.constants import (
    SESSION_BAZIN_TARGET_SPREAD,
    SESSION_BAZIN_TARGET_YIELD,
    SESSION_CEILING_MODEL_SELECTION,
)
from core.performance import instrument_screen, measure_navigation
from core.strings import MODEL_CLASSIC, MSG_PORTFOLIO_EMPTY
from services.assets_service import AssetService
from services.portfolio_read_service import PortfolioReadService
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
            target = AssetService.get_bazin_target_context(
                st.session_state.get(SESSION_CEILING_MODEL_SELECTION, MODEL_CLASSIC),
                classic_target_yield=st.session_state.get(SESSION_BAZIN_TARGET_YIELD, 6.0),
                target_spread=st.session_state.get(SESSION_BAZIN_TARGET_SPREAD, 3.0),
            )
            portfolio = PortfolioReadService.read_portfolio(target_yield=target["target_yield"])
            df_positions = portfolio.positions

        today = datetime.date.today()
        current_year = today.year
        ytd_dividends = portfolio.summary.get("ytd_dividends", 0.0)

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
                PatrimonySummaryWidget().render(portfolio)

            # 4. Render all interactive Plotly figures
            with measure_navigation("dashboard", "charts"):
                DashboardCharts().render(portfolio)

            # 5. Render detailed holdings dataframe grid (At the bottom)
            with measure_navigation("dashboard", "detailed_holdings"):
                DetailedHoldingsWidget().render(portfolio)

        with measure_navigation("dashboard", "recent_activity"):
            PortfolioActivityWidget().render()

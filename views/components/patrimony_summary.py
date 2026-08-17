import streamlit as st

from core.strings import (
    HELP_PATRIMONY_RETURN,
    HELP_PLANNING_PARAM,
    HELP_YOC_L12M,
    HELP_YOC_TOTAL,
    LABEL_CAPITAL_INVESTED,
    LABEL_DIVIDENDS_L12M,
    LABEL_DIVIDENDS_TOTAL,
    LABEL_DIVIDENDS_YTD,
    LABEL_PATRIMONY_TOTAL,
)
from core.utils import Formatter
from services.assets_service import AssetService


class PatrimonySummaryWidget:
    """Displays the 5 main portfolio KPI metrics (Patrimônio, Capital, YoC, Dividends)."""

    def render(self, df_positions):
        with st.spinner("Buscando cotações em tempo real na B3..."):
            df_positions, metrics = AssetService.get_portfolio_summary_metrics(df_positions)

        if not metrics:
            return

        st.session_state.calculated_equity_cache = metrics["total_equity"]

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(
            LABEL_PATRIMONY_TOTAL,
            Formatter.format_currency(metrics["total_equity"]),
            HELP_PATRIMONY_RETURN.format(val=metrics["overall_return"]),
        )
        m2.metric(
            LABEL_CAPITAL_INVESTED,
            Formatter.format_currency(metrics["total_invested"]),
            HELP_PLANNING_PARAM,
        )
        m3.metric(
            LABEL_DIVIDENDS_TOTAL,
            Formatter.format_currency(metrics["total_dividends"]),
            HELP_YOC_TOTAL.format(val=metrics["overall_yoc"]),
        )
        m4.metric(
            LABEL_DIVIDENDS_L12M,
            Formatter.format_currency(metrics["l12m_dividends"]),
            HELP_YOC_L12M.format(val=metrics["overall_l12m_yoc"]),
        )
        m5.metric(LABEL_DIVIDENDS_YTD, Formatter.format_currency(metrics["ytd_dividends"]))

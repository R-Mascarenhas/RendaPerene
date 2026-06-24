import streamlit as st

from core.utils import Formatter, MarketData
from services.planning_service import SimulationService
from core.strings import (
    LABEL_PATRIMONY_TOTAL, LABEL_CAPITAL_INVESTED, LABEL_DIVIDENDS_TOTAL,
    LABEL_DIVIDENDS_L12M, LABEL_DIVIDENDS_YTD, HELP_PATRIMONY_RETURN, HELP_YOC_TOTAL,
    HELP_YOC_L12M, HELP_PLANNING_PARAM
)
from core.constants import (
    TICKER, QUANTITY, INVESTED_AMOUNT, TOTAL_DIVIDENDS, L12M_DIVIDENDS, YTD_DIVIDENDS,
    CURRENT_PRICE, CURRENT_VALUE, PROFIT_LOSS
)

class PatrimonySummaryWidget:
    """Displays the 5 main portfolio KPI metrics (Patrimônio, Capital, YoC, Dividends)."""

    def render(self, df_positions):
        tickers = df_positions[TICKER].tolist()
        with st.spinner("Buscando cotações em tempo real na B3..."):
            quote_map = MarketData.get_batch_quotes(tickers)

        df_positions[CURRENT_PRICE] = df_positions[TICKER].map(quote_map)
        df_positions[CURRENT_VALUE] = df_positions[QUANTITY] * df_positions[CURRENT_PRICE]
        df_positions[PROFIT_LOSS] = df_positions[CURRENT_VALUE] - df_positions[INVESTED_AMOUNT]

        df_positions['return_pct'] = (df_positions[PROFIT_LOSS] / df_positions[INVESTED_AMOUNT]) * 100
        df_positions['total_yoc'] = (df_positions[TOTAL_DIVIDENDS] / df_positions[INVESTED_AMOUNT]) * 100
        df_positions['l12m_yoc'] = (df_positions[L12M_DIVIDENDS] / df_positions[INVESTED_AMOUNT]) * 100

        total_invested = df_positions[INVESTED_AMOUNT].sum()
        total_equity = df_positions[CURRENT_VALUE].sum()
        st.session_state.calculated_equity_cache = total_equity

        total_dividends = df_positions[TOTAL_DIVIDENDS].sum()
        l12m_dividends = df_positions[L12M_DIVIDENDS].sum()
        ytd_dividends = df_positions[YTD_DIVIDENDS].sum()

        total_profit = total_equity - total_invested
        overall_return = (total_profit / total_invested * 100) if total_invested > 0 else 0.0

        overall_yoc = (total_dividends / total_invested * 100) if total_invested > 0 else 0.0
        overall_l12m_yoc = (l12m_dividends / total_invested * 100) if total_invested > 0 else 0.0

        # Pull the invested capital parameter used in PMT calculations from the planning service
        sim = SimulationService.get_current_simulation()
        total_invested = sim["total_invested"] if sim else 0.0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(LABEL_PATRIMONY_TOTAL, Formatter.format_currency(total_equity), HELP_PATRIMONY_RETURN.format(val=overall_return))
        m2.metric(LABEL_CAPITAL_INVESTED, Formatter.format_currency(total_invested), HELP_PLANNING_PARAM)
        m3.metric(LABEL_DIVIDENDS_TOTAL, Formatter.format_currency(total_dividends), HELP_YOC_TOTAL.format(val=overall_yoc))
        m4.metric(LABEL_DIVIDENDS_L12M, Formatter.format_currency(l12m_dividends), HELP_YOC_L12M.format(val=overall_l12m_yoc))
        m5.metric(LABEL_DIVIDENDS_YTD, Formatter.format_currency(ytd_dividends))

import streamlit as st
from core.utils import Formatter, MarketData
from services.planning_service import SimulationService

class PatrimonySummaryWidget:
    """Displays the 5 main portfolio KPI metrics (Patrimônio, Capital, YoC, Dividends)."""

    def render(self, df_positions):
        tickers = df_positions['ticker'].tolist()
        with st.spinner("Buscando cotações em tempo real na B3..."):
            quote_map = MarketData.get_batch_quotes(tickers)

        df_positions['current_price'] = df_positions['ticker'].map(quote_map)
        df_positions['current_value'] = df_positions['quantity'] * df_positions['current_price']
        df_positions['profit_loss'] = df_positions['current_value'] - df_positions['invested_amount']

        df_positions['return_pct'] = (df_positions['profit_loss'] / df_positions['invested_amount']) * 100
        df_positions['total_yoc'] = (df_positions['total_dividends'] / df_positions['invested_amount']) * 100
        df_positions['l12m_yoc'] = (df_positions['l12m_dividends'] / df_positions['invested_amount']) * 100

        total_invested = df_positions['invested_amount'].sum()
        total_equity = df_positions['current_value'].sum()
        st.session_state.calculated_equity_cache = total_equity

        total_dividends = df_positions['total_dividends'].sum()
        l12m_dividends = df_positions['l12m_dividends'].sum()
        ytd_dividends = df_positions['ytd_dividends'].sum()

        total_profit = total_equity - total_invested
        overall_return = (total_profit / total_invested * 100) if total_invested > 0 else 0.0

        overall_yoc = (total_dividends / total_invested * 100) if total_invested > 0 else 0.0
        overall_l12m_yoc = (l12m_dividends / total_invested * 100) if total_invested > 0 else 0.0

        # Pull the invested capital parameter used in PMT calculations from the planning service
        sim = SimulationService.get_current_simulation()
        total_invested = sim["total_invested"] if sim else 0.0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Patrimônio Atual", Formatter.format_currency(total_equity), f"Retorno: {overall_return:+.2f}%")
        m2.metric("Capital Investido", Formatter.format_currency(total_invested), "Parâmetro do Planejamento")
        m3.metric("Proventos Totais", Formatter.format_currency(total_dividends), f"YoC Total: {overall_yoc:.2f}%")
        m4.metric("Proventos 12 Meses (L12M)", Formatter.format_currency(l12m_dividends), f"YoC L12M: {overall_l12m_yoc:.2f}%")
        m5.metric("Proventos Ano Corrente (YTD)", Formatter.format_currency(ytd_dividends))

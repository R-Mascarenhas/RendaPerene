import streamlit as st
import pandas as pd
from core.utils import Formatter

class DetailedHoldingsWidget:
    """Displays the active asset holdings detailed dataframe grid with custom financial metrics and color indicators."""

    def render(self, df_positions):
        st.markdown("---")
        st.subheader("Ativos em Custódia (Detalhado)")
        
        # 1. Compute customized financial columns
        df_positions['adjusted_price'] = (df_positions['invested_amount'] - df_positions['total_dividends']) / df_positions['quantity']
        df_positions['return_pct_custom'] = (df_positions['profit_loss'] / df_positions['invested_amount'] * 100)
        df_positions['yoc_custom'] = (df_positions['total_dividends'] / df_positions['invested_amount'] * 100)
        df_positions['yoc_12_custom'] = (df_positions['l12m_dividends'] / df_positions['invested_amount'] * 100)

        # 2. Assemble display dataframe
        df_display = pd.DataFrame()
        df_display['Código'] = df_positions['ticker']
        df_display['Nome'] = df_positions['name']
        df_display['Quantidade'] = df_positions['quantity']
        df_display['Preço médio'] = df_positions['average_price'].map(Formatter.format_currency)
        df_display['Preço Ajustado'] = df_positions['adjusted_price'].map(Formatter.format_currency)
        df_display['Investido'] = df_positions['invested_amount'].map(Formatter.format_currency)
        df_display['Atual'] = df_positions['current_value'].map(Formatter.format_currency)
        df_display['Cotação hoje'] = df_positions['current_price'].map(Formatter.format_currency)

        # Apply high-contrast green/red visual indicators (🟢 or 🔴)
        def format_return_pct(val):
            if val > 0:
                return f"🟢 +{val:.2f}%"
            elif val < 0:
                return f"🔴 {val:.2f}%"
            return f"⚪ 0,00%"

        def format_result(val):
            formatted = Formatter.format_currency(val)
            if val > 0:
                return f"🟢 {formatted}"
            elif val < 0:
                return f"🔴 {formatted}"
            return f"⚪ {formatted}"

        df_display['Rendimento %'] = df_positions['return_pct_custom'].map(format_return_pct)
        df_display['Resultado'] = df_positions['profit_loss'].map(format_result)
        df_display['YoC'] = df_positions['yoc_custom'].map(lambda x: f"{x:.2f}%")
        df_display['YoC/12'] = df_positions['yoc_12_custom'].map(lambda x: f"{x:.2f}%")
        df_display['Proventos'] = df_positions['total_dividends'].map(Formatter.format_currency)
        df_display['Setor'] = df_positions['sector']

        st.dataframe(df_display, width="stretch", hide_index=True)

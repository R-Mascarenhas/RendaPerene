import streamlit as st
import pandas as pd
from core.utils import Formatter, MarketData

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

        df_display['Rendimento %'] = df_positions['return_pct_custom'].map(Formatter.format_currency)
        df_display['Resultado'] = df_positions['profit_loss'].map(Formatter.format_currency)
        df_display['YoC'] = df_positions['yoc_custom'].map(lambda x: f"{x:.2f}%")
        df_display['YoC/12'] = df_positions['yoc_12_custom'].map(lambda x: f"{x:.2f}%")
        df_display['Proventos'] = df_positions['total_dividends'].map(Formatter.format_currency)
        df_display['Setor'] = df_positions['sector']

        # 3. DRY-compliant Bazin and trend cell coloring
        ceilings = {}
        target_yield = st.session_state.get("target_bazin_yield_pct", 6.0)

        # Load Bazin ceiling prices for each active ticker
        for t in df_positions['ticker']:
            details = MarketData.get_ticker_market_analysis(t, target_yield_pct=target_yield)
            ceilings[t] = details.get("ceiling_price", 0.0) if details else 0.0

        def style_detailed_dataframe(df):
            style_df = pd.DataFrame('', index=df.index, columns=df.columns)
            for idx in df.index:
                ticker = df_positions.loc[idx, "ticker"]
                price = df_positions.loc[idx, "current_price"] if "current_price" in df_positions.columns else 0.0
                ceiling = ceilings.get(ticker, 0.0)

                # A. Cotação hoje: Style based on Bazin Price-to-Ceiling ratio
                style_df.loc[idx, "Cotação hoje"] = Formatter.get_colored_cell_style(price, ceiling)

                # B. Rendimento %: Style based on positive/negative percentage return trend
                ret_pct = df_positions.loc[idx, "return_pct_custom"]
                style_df.loc[idx, "Rendimento %"] = Formatter.get_trend_cell_style(ret_pct)

                # C. Resultado: Style based on positive/negative cash profit trend
                pl = df_positions.loc[idx, "profit_loss"]
                style_df.loc[idx, "Resultado"] = Formatter.get_trend_cell_style(pl)

            return style_df

        styled_display = df_display.style.apply(style_detailed_dataframe, axis=None)

        st.dataframe(styled_display, width="stretch", hide_index=True)

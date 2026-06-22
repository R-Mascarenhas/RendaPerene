import streamlit as st
import pandas as pd
from core.utils import Formatter, MarketData
from core.constants import (
    TICKER, NAME, ASSET_TYPE, SECTOR, QUANTITY, AVERAGE_PRICE,
    INVESTED_AMOUNT, TOTAL_DIVIDENDS, L12M_DIVIDENDS, YTD_DIVIDENDS,
    CURRENT_PRICE, CURRENT_VALUE, PROFIT_LOSS,
    ADJUSTED_PRICE, RETURN_PCT_CUSTOM, YOC_CUSTOM, YOC_12_CUSTOM
)
from core.strings import (
    DISPLAY_CODE, DISPLAY_NAME, DISPLAY_QTY, DISPLAY_AVG_PRICE, DISPLAY_ADJ_PRICE,
    DISPLAY_INVESTED, DISPLAY_CURRENT, DISPLAY_QUOTE_TODAY, DISPLAY_RETURN_PCT,
    DISPLAY_RESULT, DISPLAY_YOC, DISPLAY_YOC_12, DISPLAY_EARNINGS, DISPLAY_SECTOR
)

class DetailedHoldingsWidget:
    """Displays the active asset holdings detailed dataframe grid with custom financial metrics and color indicators."""

    def render(self, df_positions):
        st.markdown("---")
        st.subheader("Ativos em Custódia (Detalhado)")

        # 1. Compute customized financial columns using compiler-checked constants
        df_positions[ADJUSTED_PRICE] = (df_positions[INVESTED_AMOUNT] - df_positions[TOTAL_DIVIDENDS]) / df_positions[QUANTITY]
        df_positions[RETURN_PCT_CUSTOM] = (df_positions[PROFIT_LOSS] / df_positions[INVESTED_AMOUNT] * 100)
        df_positions[YOC_CUSTOM] = (df_positions[TOTAL_DIVIDENDS] / df_positions[INVESTED_AMOUNT] * 100)
        df_positions[YOC_12_CUSTOM] = (df_positions[L12M_DIVIDENDS] / df_positions[INVESTED_AMOUNT] * 100)

        # 2. Assemble display dataframe using display constants
        df_display = pd.DataFrame()
        df_display[DISPLAY_CODE] = df_positions[TICKER]
        df_display[DISPLAY_NAME] = df_positions[NAME]
        df_display[DISPLAY_QTY] = df_positions[QUANTITY]
        df_display[DISPLAY_AVG_PRICE] = df_positions[AVERAGE_PRICE].map(Formatter.format_currency)
        df_display[DISPLAY_ADJ_PRICE] = df_positions[ADJUSTED_PRICE].map(Formatter.format_currency)
        df_display[DISPLAY_INVESTED] = df_positions[INVESTED_AMOUNT].map(Formatter.format_currency)
        df_display[DISPLAY_CURRENT] = df_positions[CURRENT_VALUE].map(Formatter.format_currency)
        df_display[DISPLAY_QUOTE_TODAY] = df_positions[CURRENT_PRICE].map(Formatter.format_currency)

        df_display[DISPLAY_RETURN_PCT] = df_positions[RETURN_PCT_CUSTOM].map(lambda x: f"{x:.2f}%")
        df_display[DISPLAY_RESULT] = df_positions[PROFIT_LOSS].map(Formatter.format_currency)
        df_display[DISPLAY_YOC] = df_positions[YOC_CUSTOM].map(lambda x: f"{x:.2f}%")
        df_display[DISPLAY_YOC_12] = df_positions[YOC_12_CUSTOM].map(lambda x: f"{x:.2f}%")
        df_display[DISPLAY_EARNINGS] = df_positions[TOTAL_DIVIDENDS].map(Formatter.format_currency)
        df_display[DISPLAY_SECTOR] = df_positions[SECTOR]

        # 3. DRY-compliant Bazin and trend cell coloring
        ceilings = {}
        target_yield = st.session_state.get("target_bazin_yield_pct", 6.0)

        # Load Bazin ceiling prices for each active ticker
        for t in df_positions[TICKER]:
            details = MarketData.get_ticker_market_analysis(t, target_yield_pct=target_yield)
            ceilings[t] = details.get("ceiling_price", 0.0) if details else 0.0

        def style_detailed_dataframe(df):
            style_df = pd.DataFrame('', index=df.index, columns=df.columns)
            for idx in df.index:
                ticker = df_positions.loc[idx, TICKER]
                price = df_positions.loc[idx, CURRENT_PRICE] if CURRENT_PRICE in df_positions.columns else 0.0
                ceiling = ceilings.get(ticker, 0.0)

                # A. Cotação hoje: Style based on Bazin Price-to-Ceiling ratio using constants
                style_df.loc[idx, DISPLAY_QUOTE_TODAY] = Formatter.get_colored_cell_style(price, ceiling)

                # B. Rendimento %: Style based on positive/negative percentage return trend using constants
                ret_pct = df_positions.loc[idx, RETURN_PCT_CUSTOM]
                style_df.loc[idx, DISPLAY_RETURN_PCT] = Formatter.get_trend_cell_style(ret_pct)

                # C. Resultado: Style based on positive/negative cash profit trend using constants
                pl = df_positions.loc[idx, PROFIT_LOSS]
                style_df.loc[idx, DISPLAY_RESULT] = Formatter.get_trend_cell_style(pl)

            return style_df

        styled_display = df_display.style.apply(style_detailed_dataframe, axis=None)

        st.dataframe(styled_display, width="stretch", hide_index=True)

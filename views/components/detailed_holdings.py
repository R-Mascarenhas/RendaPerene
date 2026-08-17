import pandas as pd
import streamlit as st

from core.constants import CURRENT_PRICE, PROFIT_LOSS, RETURN_PCT_CUSTOM, TICKER
from core.strings import (
    DISPLAY_ADJ_PRICE,
    DISPLAY_AVG_PRICE,
    DISPLAY_CEILING,
    DISPLAY_EARNINGS,
    DISPLAY_QUOTE_TODAY,
    DISPLAY_RESULT,
    DISPLAY_RETURN_PCT,
    DISPLAY_WEIGHT,
    DISPLAY_YOC,
    DISPLAY_YOC_12,
    HELP_ADJ_PRICE,
    HELP_AVG_PRICE,
    HELP_CEILING,
    HELP_EARNINGS,
    HELP_RESULT,
    HELP_RETURN_PCT,
    HELP_WEIGHT_PCT,
    HELP_YOC,
    HELP_YOC_12,
    MSG_CUSTODY_ASSETS_TITLE,
)
from core.utils import Formatter
from services.assets_service import AssetService


class DetailedHoldingsWidget:
    """Displays the active asset holdings detailed dataframe grid with custom financial metrics and color indicators."""

    def render(self, df_positions):
        st.markdown("---")
        st.subheader(MSG_CUSTODY_ASSETS_TITLE)

        target_yield = st.session_state.get("target_bazin_yield_pct", 6.0)

        with st.spinner("Buscando informações do catálogo e preço teto..."):
            df_display, ceilings = AssetService.get_detailed_holdings_dataframe(
                df_positions, target_yield
            )

        if df_display.empty:
            return

        # DRY-compliant Bazin and trend cell coloring
        def style_detailed_dataframe(df):
            style_df = pd.DataFrame("", index=df.index, columns=df.columns)
            for idx in df.index:
                ticker = df_positions.loc[idx, TICKER]
                price = (
                    df_positions.loc[idx, CURRENT_PRICE]
                    if CURRENT_PRICE in df_positions.columns
                    else 0.0
                )
                ceiling = ceilings.get(ticker, 0.0)

                # A. Cotação hoje: Style based on Bazin Price-to-Ceiling ratio using constants
                style_df.loc[idx, DISPLAY_QUOTE_TODAY] = Formatter.get_colored_cell_style(
                    price, ceiling
                )

                # B. Rendimento %: Style based on positive/negative percentage return trend using constants
                ret_pct = df_positions.loc[idx, RETURN_PCT_CUSTOM]
                style_df.loc[idx, DISPLAY_RETURN_PCT] = Formatter.get_trend_cell_style(ret_pct)

                # C. Resultado: Style based on positive/negative cash profit trend using constants
                pl = df_positions.loc[idx, PROFIT_LOSS]
                style_df.loc[idx, DISPLAY_RESULT] = Formatter.get_trend_cell_style(pl)

            return style_df

        styled_display = df_display.style.apply(style_detailed_dataframe, axis=None)

        st.dataframe(
            styled_display,
            width="stretch",
            hide_index=True,
            column_config={
                DISPLAY_WEIGHT: st.column_config.TextColumn(help=HELP_WEIGHT_PCT),
                DISPLAY_AVG_PRICE: st.column_config.TextColumn(help=HELP_AVG_PRICE),
                DISPLAY_ADJ_PRICE: st.column_config.TextColumn(help=HELP_ADJ_PRICE),
                DISPLAY_CEILING: st.column_config.TextColumn(help=HELP_CEILING),
                DISPLAY_RETURN_PCT: st.column_config.TextColumn(help=HELP_RETURN_PCT),
                DISPLAY_RESULT: st.column_config.TextColumn(help=HELP_RESULT),
                DISPLAY_YOC: st.column_config.TextColumn(help=HELP_YOC),
                DISPLAY_YOC_12: st.column_config.TextColumn(help=HELP_YOC_12),
                DISPLAY_EARNINGS: st.column_config.TextColumn(help=HELP_EARNINGS),
            },
        )

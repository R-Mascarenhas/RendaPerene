import streamlit as st

import pandas as pd
import datetime
from services.assets_service import AssetService
from services.planning_service import SimulationService
from core.utils import Formatter, MarketData
from core.constants import (
    TICKER, NAME, CURRENT_PRICE, CEILING_PRICE, MARKET_PB, MARKET_PE,
    CURRENT_DY, MARKET_ROE, MARKET_LOW_52W, MARKET_HIGH_52W,
    MARKET_AVG_DIV_5Y, MARKET_AVG_DY_5Y, MARKET_DIVIDENDS_5Y, MARKET_NAME,
    BIRTH_DATE, RETIREMENT_AGE, DESIRED_INCOME_MW, ANNUAL_INTEREST_RATE,
    MW_VALUE, DESIRED_INCOME_TYPE, DESIRED_INCOME_FIXED,
    SESSION_CEILING_MODEL_SELECTION, SESSION_BAZIN_TARGET_YIELD, SESSION_BAZIN_TARGET_SPREAD,
    WIDGET_CEILING_MODEL_SELECTOR, WIDGET_BAZIN_YIELD_INPUT, WIDGET_BAZIN_SPREAD_INPUT
)
from core.strings import (
    MSG_MARKET_MONITOR_TITLE, MSG_MARKET_MONITOR_DESC, MSG_INVALID_ASSET_SELECTION,
    MSG_ASSET_ADDED_SUCCESS, MSG_ASSET_ADD_ERROR, MSG_NO_ASSETS_MONITOR,
    MSG_CONFIRM_REMOVE, MSG_ASSET_REMOVED_SUCCESS, MSG_MONITORED_ASSETS_PANEL,
    MSG_YF_FETCH_ERROR, MSG_ADJUST_DIVIDENDS_EXPANDER, MSG_ADJUST_DIVIDENDS_DESC,
    MSG_INVALID_ASSET_CORRECTION, MSG_DIVIDEND_CORRECTION_SUCCESS, MSG_DIVIDEND_CORRECTION_ERROR,
    HELP_MARKET_MONITOR_SEARCH, DISPLAY_TICKER, DISPLAY_COMPANY, DISPLAY_QUOTE,
    DISPLAY_CEILING, DISPLAY_AVG_5Y, DISPLAY_DY_AVG_5Y, DISPLAY_P_VP, DISPLAY_P_L,
    DISPLAY_DY_CURRENT, DISPLAY_ROE, DISPLAY_RANGE_52W, MODEL_CLASSIC, MODEL_SELIC, MODEL_IPCA_SPREAD
)

class MarketView:
    """Class responsible for rendering the centralized Bazin Market Watchlist monitor under the 3rd top-level tab."""

    def render(self):
        st.subheader(MSG_MARKET_MONITOR_TITLE)
        st.write(MSG_MARKET_MONITOR_DESC)

        catalog = MarketData.load_assets_catalog()
        available_tickers = sorted(catalog.index.tolist()) if not catalog.empty else []

        col_add, col_yield = st.columns([2, 1])

        with col_add:
            with st.form("form_add_market_asset", clear_on_submit=True):
                # Construct autocompleting ticker + name options for premium UX
                market_options = ["--- Selecione ---"] + [f"{t} - {catalog.loc[t, 'NOME']}" for t in available_tickers if t in catalog.index]
                new_ticker_selection = st.selectbox(
                    "Adicionar Ticker para Acompanhamento",
                    options=market_options,
                    index=0,
                    help=HELP_MARKET_MONITOR_SEARCH
                )
                submit_add = st.form_submit_button("➕ Adicionar à Lista")
                if submit_add:
                    if new_ticker_selection == "--- Selecione ---":
                        st.error(MSG_INVALID_ASSET_SELECTION)
                    else:
                        ticker_to_add = new_ticker_selection.split(" - ")[0]
                        success = AssetService.add_tracked_market_asset(ticker_to_add)
                        if success:
                            st.success(MSG_ASSET_ADDED_SUCCESS.format(ticker=ticker_to_add))
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(MSG_ASSET_ADD_ERROR.format(ticker=ticker_to_add))

        with col_yield:
            # Load from persistent session state using visual string constants
            default_db_model = st.session_state.get(SESSION_CEILING_MODEL_SELECTION, MODEL_CLASSIC)
            model_options = [MODEL_CLASSIC, MODEL_SELIC, MODEL_IPCA_SPREAD]
            default_index = model_options.index(default_db_model) if default_db_model in model_options else 0

            st.selectbox(
                "Modelo de Preço Teto",
                options=model_options,
                index=default_index,
                key=WIDGET_CEILING_MODEL_SELECTOR,
                on_change=self._on_bazin_model_change
            )

            model = st.session_state.get(SESSION_CEILING_MODEL_SELECTION, MODEL_CLASSIC)
            ipca_val = MarketData.get_current_ipca_l12m()
            selic_val = MarketData.get_current_selic()

            if model == MODEL_CLASSIC:
                st.number_input(
                    "Taxa Alvo Bazin (%)",
                    min_value=1.0,
                    max_value=20.0,
                    value=float(st.session_state[SESSION_BAZIN_TARGET_YIELD]),
                    key=WIDGET_BAZIN_YIELD_INPUT,
                    step=0.5,
                    on_change=self._on_bazin_yield_change
                )
                target_yield = st.session_state[SESSION_BAZIN_TARGET_YIELD]
            elif model == MODEL_SELIC:
                target_yield = selic_val
                st.caption(f"ℹ️ Taxa SELIC Meta (BCB): **{selic_val:.2f}% a.a.**")
            else: # IPCA + Spread Alvo
                st.number_input(
                    "Spread Alvo (%)",
                    min_value=0.0,
                    max_value=15.0,
                    value=float(st.session_state[SESSION_BAZIN_TARGET_SPREAD]),
                    key=WIDGET_BAZIN_SPREAD_INPUT,
                    step=0.5,
                    on_change=self._on_bazin_spread_change
                )
                spread = st.session_state[SESSION_BAZIN_TARGET_SPREAD]
                target_yield = ipca_val + spread
                st.caption(f"ℹ️ Divisor Resultante: **{target_yield:.2f}%** (IPCA: {ipca_val:.2f}% + Spread: {spread:.2f}%)")

            # Permanently cache the evaluated target yield in session state so other views sync instantly!
            st.session_state.target_bazin_yield_pct = target_yield

        tracked_tickers = AssetService.get_tracked_market_assets()

        if not tracked_tickers:
            st.info(MSG_NO_ASSETS_MONITOR)
            return

        col_rem, _ = st.columns([2, 2])
        with col_rem:
            remove_ticker = st.selectbox("Remover empresa do monitor", ["--- Selecione ---"] + tracked_tickers)
            if remove_ticker != "--- Selecione ---":
                if st.button(MSG_CONFIRM_REMOVE.format(ticker=remove_ticker)):
                    AssetService.remove_tracked_market_asset(remove_ticker)
                    st.success(MSG_ASSET_REMOVED_SUCCESS.format(ticker=remove_ticker))
                    st.cache_data.clear()
                    st.rerun()

        st.markdown("---")
        st.subheader(MSG_MONITORED_ASSETS_PANEL)

        with st.spinner("Buscando indicadores em tempo real no Yahoo Finance..."):
            df_display, df_market = AssetService.get_market_analysis_data(tracked_tickers, target_yield)

        if df_display.empty:
            st.warning(MSG_YF_FETCH_ERROR)
            return

        current_year = datetime.date.today().year
        last_5_years = [current_year - i for i in range(1, 6)]

        def format_range_52w(row):
            low = row[MARKET_LOW_52W]
            high = row[MARKET_HIGH_52W]
            if low <= 0 or high <= 0:
                return "N/D"
            return f"{Formatter.format_currency(low)} - {Formatter.format_currency(high)}"

        df_display[DISPLAY_RANGE_52W] = df_market.apply(format_range_52w, axis=1)

        col_configs = {
            DISPLAY_TICKER: st.column_config.TextColumn(width="small"),
            DISPLAY_COMPANY: st.column_config.TextColumn(width="medium"),
            DISPLAY_QUOTE: st.column_config.NumberColumn(format="R$ %.2f", width="small"),
            DISPLAY_CEILING: st.column_config.NumberColumn(format="R$ %.2f", width="small"),
        }

        for yr in last_5_years:
            col_configs[f"Div {yr}"] = st.column_config.NumberColumn(format="R$ %.2f", width="small")

        col_configs.update({
            DISPLAY_AVG_5Y: st.column_config.NumberColumn(format="R$ %.2f", width="small"),
            DISPLAY_DY_AVG_5Y: st.column_config.NumberColumn(format="%.2f%%", width="small"),
            DISPLAY_P_VP: st.column_config.NumberColumn(format="%.2f", width="small"),
            DISPLAY_P_L: st.column_config.NumberColumn(format="%.2f", width="small"),
            DISPLAY_DY_CURRENT: st.column_config.NumberColumn(format="%.2f%%", width="small"),
            DISPLAY_ROE: st.column_config.NumberColumn(format="%.2f%%", width="small"),
            DISPLAY_RANGE_52W: st.column_config.TextColumn(width="medium")
        })

        def style_market_dataframe(df):
            style_df = pd.DataFrame('', index=df.index, columns=df.columns)
            for idx in df.index:
                price = df_market.loc[idx, DISPLAY_QUOTE]
                ceiling = df_market.loc[idx, DISPLAY_CEILING]
                style_df.loc[idx, DISPLAY_QUOTE] = Formatter.get_colored_cell_style(price, ceiling)
            return style_df

        styled_display = df_display.style.apply(style_market_dataframe, axis=None)

        st.dataframe(
            styled_display,
            width="stretch",
            hide_index=True,
            column_config=col_configs
        )

        st.markdown("---")
        with st.expander(MSG_ADJUST_DIVIDENDS_EXPANDER):
            st.write(MSG_ADJUST_DIVIDENDS_DESC)

            with st.form("form_dividend_correction", clear_on_submit=True):
                col_c1, col_c2, col_c3 = st.columns(3)
                with col_c1:
                    corr_ticker = st.selectbox("Selecione o Ativo para Corrigir", options=["--- Selecione ---"] + tracked_tickers)
                with col_c2:
                    current_year = datetime.date.today().year
                    corr_year = st.selectbox("Selecione o Ano", options=[current_year - i for i in range(1, 6)])
                with col_c3:
                    corr_value = st.number_input("Valor Total Pago no Ano (R$)", min_value=0.01, value=2.00, step=0.05)

                submit_corr = st.form_submit_button("💾 Salvar Correção")
                if submit_corr:
                    if corr_ticker == "--- Selecione ---":
                        st.error(MSG_INVALID_ASSET_CORRECTION)
                    else:
                        success = AssetService.save_dividend_correction(corr_ticker, corr_year, corr_value)
                        if success:
                            st.success(MSG_DIVIDEND_CORRECTION_SUCCESS.format(ticker=corr_ticker, year=corr_year, value=Formatter.format_currency(corr_value)))
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(MSG_DIVIDEND_CORRECTION_ERROR)

    def _on_bazin_model_change(self):
        """Syncs the selectbox model change to persistent state and database."""
        st.session_state[SESSION_CEILING_MODEL_SELECTION] = st.session_state[WIDGET_CEILING_MODEL_SELECTOR]
        self._save_market_params()

    def _on_bazin_yield_change(self):
        """Syncs target yield input back to persistent state and database."""
        st.session_state[SESSION_BAZIN_TARGET_YIELD] = float(st.session_state[WIDGET_BAZIN_YIELD_INPUT])
        self._save_market_params()

    def _on_bazin_spread_change(self):
        """Syncs target spread input back to persistent state and database."""
        st.session_state[SESSION_BAZIN_TARGET_SPREAD] = float(st.session_state[WIDGET_BAZIN_SPREAD_INPUT])
        self._save_market_params()

    def _save_market_params(self):
        """Calculates the resulting target yield dynamically and persists configurations to SQLite portfolio.db."""
        model = st.session_state[SESSION_CEILING_MODEL_SELECTION]
        yield_val = float(st.session_state[SESSION_BAZIN_TARGET_YIELD])
        spread_val = float(st.session_state[SESSION_BAZIN_TARGET_SPREAD])

        ipca_val = MarketData.get_current_ipca_l12m()
        selic_val = MarketData.get_current_selic()

        if model == MODEL_CLASSIC:
            target_yield = yield_val
        elif model == MODEL_SELIC:
            target_yield = selic_val
        else:
            target_yield = ipca_val + spread_val

        st.session_state.target_bazin_yield_pct = target_yield

        # Retrieve and load general simulation settings to preserve them cleanly
        config = SimulationService.get_configuration()
        if config:
            SimulationService.save_configuration(
                config[BIRTH_DATE],
                config[RETIREMENT_AGE],
                config[DESIRED_INCOME_MW],
                config[ANNUAL_INTEREST_RATE],
                config[MW_VALUE],
                0.0,
                desired_income_type=config[DESIRED_INCOME_TYPE],
                desired_income_fixed=config[DESIRED_INCOME_FIXED],
                ceiling_model_selection=model,
                bazin_target_yield=yield_val,
                bazin_target_spread=spread_val
            )

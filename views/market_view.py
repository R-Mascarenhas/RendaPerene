import streamlit as st
import pandas as pd
import datetime
from services.assets_service import AssetService
from core.utils import Formatter, MarketData
from core.constants import (
    TICKER, NAME, CURRENT_PRICE, CEILING_PRICE, MARKET_PB, MARKET_PE,
    CURRENT_DY, MARKET_ROE, MARKET_LOW_52W, MARKET_HIGH_52W,
    MARKET_AVG_DIV_5Y, MARKET_AVG_DY_5Y, MARKET_DIVIDENDS_5Y, MARKET_NAME
)
from core.strings import (
    DISPLAY_TICKER, DISPLAY_COMPANY, DISPLAY_QUOTE, DISPLAY_CEILING,
    DISPLAY_AVG_5Y, DISPLAY_DY_AVG_5Y, DISPLAY_P_VP, DISPLAY_P_L,
    DISPLAY_DY_CURRENT, DISPLAY_ROE, DISPLAY_RANGE_52W
)

class MarketView:
    """Class responsible for rendering the centralized Bazin Market Watchlist monitor under the 3rd top-level tab."""

    def render(self):
        st.subheader("📈 Central de Monitoramento de Mercado (Bazin)")
        st.write("Acompanhe empresas da B3 em tempo real e identifique oportunidades de compra utilizando o modelo de Preço Teto de Décio Bazin.")

        catalog = MarketData.load_assets_catalog()
        available_tickers = sorted(catalog.index.tolist()) if not catalog.empty else []

        col_add, col_yield = st.columns([2, 1])

        with col_add:
            with st.form("form_add_market_asset", clear_on_submit=True):
                new_ticker = st.selectbox(
                    "Adicionar Ticker para Acompanhamento",
                    options=["--- Selecione ---"] + available_tickers,
                    index=0,
                    help="Digite para buscar e autocompletar ativos válidos cadastrados no arquivo assets.csv"
                )
                submit_add = st.form_submit_button("➕ Adicionar à Lista")
                if submit_add:
                    if new_ticker == "--- Selecione ---":
                        st.error("Por favor, selecione um ativo válido da lista.")
                    else:
                        success = AssetService.add_tracked_market_asset(new_ticker)
                        if success:
                            st.success(f"Ativo {new_ticker} adicionado com sucesso ao monitor!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(f"Erro ao adicionar o ativo {new_ticker} (ou ele já existe no monitor).")

        with col_yield:
            target_yield = st.number_input(
                "Taxa de Rendimento Alvo Bazin (%)",
                min_value=1.0,
                max_value=20.0,
                value=6.0,
                step=0.5,
                key="target_bazin_yield_pct"
            )

        tracked_tickers = AssetService.get_tracked_market_assets()

        if not tracked_tickers:
            st.info("Nenhuma empresa adicionada ao monitor. Digite um ticker no formulário acima para começar a acompanhar!")
            return

        col_rem, _ = st.columns([2, 2])
        with col_rem:
            remove_ticker = st.selectbox("Remover empresa do monitor", ["--- Selecione ---"] + tracked_tickers)
            if remove_ticker != "--- Selecione ---":
                if st.button(f"🗑️ Confirmar Remoção de {remove_ticker}"):
                    AssetService.remove_tracked_market_asset(remove_ticker)
                    st.success(f"Ativo {remove_ticker} removido com sucesso!")
                    st.cache_data.clear()
                    st.rerun()

        st.markdown("---")
        st.subheader("Painel de Ativos Monitorados")

        market_rows = []
        with st.spinner("Buscando indicadores em tempo real no Yahoo Finance..."):
            for t in tracked_tickers:
                details = MarketData.get_ticker_market_analysis(t, target_yield_pct=target_yield)
                metadata = AssetService.get_asset_metadata(t)

                if details:
                    current_year = datetime.date.today().year
                    last_5_years = [current_year - i for i in range(1, 6)]

                    row_data = {
                        DISPLAY_TICKER: t,
                        DISPLAY_COMPANY: details.get(MARKET_NAME, metadata.get(NAME, t)),
                        DISPLAY_QUOTE: details.get(CURRENT_PRICE, 0.0),
                        DISPLAY_CEILING: details.get(CEILING_PRICE, 0.0),
                        DISPLAY_P_VP: details.get(MARKET_PB, 0.0),
                        DISPLAY_P_L: details.get(MARKET_PE, 0.0),
                        DISPLAY_DY_CURRENT: details.get(CURRENT_DY, 0.0),
                        DISPLAY_ROE: details.get(MARKET_ROE, 0.0),
                        MARKET_LOW_52W: details.get(MARKET_LOW_52W, 0.0),
                        MARKET_HIGH_52W: details.get(MARKET_HIGH_52W, 0.0),
                        MARKET_AVG_DIV_5Y: details.get(MARKET_AVG_DIV_5Y, 0.0),
                        MARKET_AVG_DY_5Y: details.get(MARKET_AVG_DY_5Y, 0.0)
                    }

                    for yr in last_5_years:
                        row_data[f"Div {yr}"] = details.get(MARKET_DIVIDENDS_5Y, {}).get(yr, 0.0)

                    market_rows.append(row_data)

        if not market_rows:
            st.warning("Falha ao obter dados do Yahoo Finance para as empresas monitoradas. Verifique se digitou os tickers corretamente.")
            return

        df_market = pd.DataFrame(market_rows)

        df_display = pd.DataFrame()
        df_display[DISPLAY_TICKER] = df_market[DISPLAY_TICKER]
        df_display[DISPLAY_COMPANY] = df_market[DISPLAY_COMPANY]

        df_display[DISPLAY_QUOTE] = df_market[DISPLAY_QUOTE]
        df_display[DISPLAY_CEILING] = df_market[DISPLAY_CEILING]

        current_year = datetime.date.today().year
        last_5_years = [current_year - i for i in range(1, 6)]
        for yr in last_5_years:
            df_display[f"Div {yr}"] = df_market[f"Div {yr}"]

        df_display[DISPLAY_AVG_5Y] = df_market[MARKET_AVG_DIV_5Y]
        df_display[DISPLAY_DY_AVG_5Y] = df_market[MARKET_AVG_DY_5Y]
        df_display[DISPLAY_P_VP] = df_market[DISPLAY_P_VP]
        df_display[DISPLAY_P_L] = df_market[DISPLAY_P_L]
        df_display[DISPLAY_DY_CURRENT] = df_market[DISPLAY_DY_CURRENT]
        df_display[DISPLAY_ROE] = df_market[DISPLAY_ROE]

        def format_range_52w(row):
            low = row[MARKET_LOW_52W]
            high = row[MARKET_HIGH_52W]
            if low <= 0 or high <= 0:
                return "N/D"
            return f"{Formatter.format_currency(low)} - {Formatter.format_currency(high)}"

        df_display[DISPLAY_RANGE_52W] = df_market.apply(format_range_52w, axis=1)

        col_configs = {
            DISPLAY_TICKER: st.column_config.TextColumn("Ticker", width="small"),
            DISPLAY_COMPANY: st.column_config.TextColumn("Empresa", width="medium"),
            DISPLAY_QUOTE: st.column_config.NumberColumn("Cotação", format="R$ %.2f", width="small"),
            DISPLAY_CEILING: st.column_config.NumberColumn("Preço Teto (Bazin)", format="R$ %.2f", width="small"),
        }

        for yr in last_5_years:
            col_configs[f"Div {yr}"] = st.column_config.NumberColumn(f"Div {yr}", format="R$ %.2f", width="small")

        col_configs.update({
            DISPLAY_AVG_5Y: st.column_config.NumberColumn("Média 5a", format="R$ %.2f", width="small"),
            DISPLAY_DY_AVG_5Y: st.column_config.NumberColumn("DY Médio 5a", format="%.2f%%", width="small"),
            DISPLAY_P_VP: st.column_config.NumberColumn("P/VP", format="%.2f", width="small"),
            DISPLAY_P_L: st.column_config.NumberColumn("P/L", format="%.2f", width="small"),
            DISPLAY_DY_CURRENT: st.column_config.NumberColumn("DY Atual", format="%.2f%%", width="small"),
            DISPLAY_ROE: st.column_config.NumberColumn("ROE", format="%.2f%%", width="small"),
            DISPLAY_RANGE_52W: st.column_config.TextColumn("Faixa 52s (Mín-Máx)", width="medium")
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
        with st.expander("🔧 Ajustar Proventos Históricos (Bazin)"):
            st.write("Caso identifique erros de omissão de dividendos no Yahoo Finance (como JCPs complementares), corrija os valores consolidados de cada ano abaixo:")

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
                        st.error("Por favor, selecione um ativo válido para aplicar a correção.")
                    else:
                        success = AssetService.save_dividend_correction(corr_ticker, corr_year, corr_value)
                        if success:
                            st.success(f"Proventos de {corr_ticker} para o ano de {corr_year} corrigidos com sucesso para {Formatter.format_currency(corr_value)}!")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Erro ao salvar a correção de dividendos.")

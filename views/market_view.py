import streamlit as st
import pandas as pd
import datetime
from services.assets_service import AssetService
from core.utils import Formatter, MarketData

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
                        "Ticker": t,
                        "Empresa": details.get("name", metadata.get("name", t)),
                        "Cotação": details.get("current_price", 0.0),
                        "Preço Teto": details.get("ceiling_price", 0.0),
                        "P/VP": details.get("pb", 0.0),
                        "P/L": details.get("pe", 0.0),
                        "DY %": details.get("dy", 0.0),
                        "ROE %": details.get("roe", 0.0),
                        "low_52w": details.get("low_52w", 0.0),
                        "high_52w": details.get("high_52w", 0.0),
                        "avg_div_5y": details.get("avg_dividend_5y", 0.0),
                        "avg_dy_5y": details.get("avg_dy_5y", 0.0)
                    }

                    for yr in last_5_years:
                        row_data[f"Div {yr}"] = details.get("dividends_5y", {}).get(yr, 0.0)

                    market_rows.append(row_data)

        if not market_rows:
            st.warning("Falha ao obter dados do Yahoo Finance para as empresas monitoradas. Verifique se digitou os tickers corretamente.")
            return

        df_market = pd.DataFrame(market_rows)

        df_display = pd.DataFrame()
        df_display["Ticker"] = df_market["Ticker"]
        df_display["Empresa"] = df_market["Empresa"]

        df_display["Cotação"] = df_market["Cotação"]
        df_display["Preço Teto"] = df_market["Preço Teto"]

        current_year = datetime.date.today().year
        last_5_years = [current_year - i for i in range(1, 6)]
        for yr in last_5_years:
            df_display[f"Div {yr}"] = df_market[f"Div {yr}"]

        df_display["Média 5a"] = df_market["avg_div_5y"]
        df_display["DY Médio 5a"] = df_market["avg_dy_5y"]
        df_display["P/VP"] = df_market["P/VP"]
        df_display["P/L"] = df_market["P/L"]
        df_display["DY Atual"] = df_market["DY %"]
        df_display["ROE"] = df_market["ROE %"]

        def format_range_52w(row):
            low = row["low_52w"]
            high = row["high_52w"]
            if low <= 0 or high <= 0:
                return "N/D"
            return f"{Formatter.format_currency(low)} - {Formatter.format_currency(high)}"

        df_display["Faixa 52s"] = df_market.apply(format_range_52w, axis=1)

        col_configs = {
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Empresa": st.column_config.TextColumn("Empresa", width="medium"),
            "Cotação": st.column_config.NumberColumn("Cotação", format="R$ %.2f", width="small"),
            "Preço Teto": st.column_config.NumberColumn("Preço Teto (Bazin)", format="R$ %.2f", width="small"),
        }

        for yr in last_5_years:
            col_configs[f"Div {yr}"] = st.column_config.NumberColumn(f"Div {yr}", format="R$ %.2f", width="small")

        col_configs.update({
            "Média 5a": st.column_config.NumberColumn("Média 5a", format="R$ %.2f", width="small"),
            "DY Médio 5a": st.column_config.NumberColumn("DY Médio 5a", format="%.2f%%", width="small"),
            "P/VP": st.column_config.NumberColumn("P/VP", format="%.2f", width="small"),
            "P/L": st.column_config.NumberColumn("P/L", format="%.2f", width="small"),
            "DY Atual": st.column_config.NumberColumn("DY Atual", format="%.2f%%", width="small"),
            "ROE": st.column_config.NumberColumn("ROE", format="%.2f%%", width="small"),
            "Faixa 52s": st.column_config.TextColumn("Faixa 52s (Mín-Máx)", width="medium")
        })

        def style_market_dataframe(df):
            style_df = pd.DataFrame('', index=df.index, columns=df.columns)
            for idx in df.index:
                price = df_market.loc[idx, "Cotação"]
                ceiling = df_market.loc[idx, "Preço Teto"]
                style_df.loc[idx, "Cotação"] = Formatter.get_colored_cell_style(price, ceiling)
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

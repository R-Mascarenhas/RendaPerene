import streamlit as st
import pandas as pd
import datetime
from assets.assets_service import AssetService
from core.utils import Formatter, MarketData

class MarketView:
    """Class responsible for rendering the centralized Bazin Market Watchlist monitor under the 3rd top-level tab."""

    def render(self):
        st.subheader("📈 Central de Monitoramento de Mercado (Bazin)")
        st.write("Acompanhe empresas da B3 em tempo real e identifique oportunidades de compra utilizando o modelo de Preço Teto de Décio Bazin.")
        
        # 1. Action Row: Add tracked ticker & adjust target yield
        col_add, col_yield = st.columns([2, 1])
        
        with col_add:
            with st.form("form_add_market_asset", clear_on_submit=True):
                new_ticker = st.text_input("Adicionar Ticker para Acompanhamento (ex: BBAS3, TAEE11)").strip().upper()
                submit_add = st.form_submit_button("➕ Adicionar à Lista")
                if submit_add:
                    if len(new_ticker) < 5 or not new_ticker[:4].isalpha():
                        st.error("Digite um Ticker de ativo da B3 válido (ex: BBAS3, TAEE11).")
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

        # 2. Get currently tracked assets from the personal database
        tracked_tickers = AssetService.get_tracked_market_assets()
        
        if not tracked_tickers:
            st.info("Nenhuma empresa adicionada ao monitor. Digite um ticker no formulário acima para começar a acompanhar!")
            return
            
        # Allow the user to remove a tracked ticker cleanly
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

        # 3. Fetch live metrics & compute Bazin formula for each tracked ticker
        market_rows = []
        with st.spinner("Buscando indicadores em tempo real no Yahoo Finance..."):
            for t in tracked_tickers:
                details = MarketData.get_ticker_market_analysis(t, target_yield_pct=target_yield)
                metadata = AssetService.get_asset_metadata(t)
                
                if details:
                    current_year = datetime.date.today().year
                    last_5_years = [current_year - i for i in range(1, 6)] # e.g. [2025, 2024, 2023, 2022, 2021]
                    
                    row_data = {
                        "Ticker": t,
                        "Empresa": details.get("name", metadata.get("name", t)),
                        "Setor": metadata.get("sector", "Outros"),
                        "Segmento": metadata.get("segment", "N/D"),
                        "Cotação": details.get("current_price", 0.0),
                        "Preço Teto": details.get("ceiling_price", 0.0),
                        "VPA": details.get("vpa", 0.0),
                        "Bai 52s": details.get("low_52w", 0.0),
                        "Alt 52s": details.get("high_52w", 0.0),
                        "P/VP": details.get("pb", 0.0),
                        "P/L": details.get("pe", 0.0),
                        "DY %": details.get("dy", 0.0),
                        "ROE %": details.get("roe", 0.0),
                        "avg_div_5y": details.get("avg_dividend_5y", 0.0),
                        "avg_dy_5y": details.get("avg_dy_5y", 0.0)
                    }
                    
                    # Append dynamic historical annual dividends
                    for yr in last_5_years:
                        row_data[f"Div {yr}"] = details.get("dividends_5y", {}).get(yr, 0.0)
                        
                    market_rows.append(row_data)

        if not market_rows:
            st.warning("Falha ao obter dados do Yahoo Finance para as empresas monitoradas. Verifique se digitou os tickers corretamente.")
            return

        df_market = pd.DataFrame(market_rows)

        # 4. Form Display Dataframe and Apply Indicators
        df_display = pd.DataFrame()
        df_display["Ticker"] = df_market["Ticker"]
        df_display["Empresa"] = df_market["Empresa"]
        df_display["Setor"] = df_market["Setor"]
        df_display["Segmento"] = df_market["Segmento"]
        
        # Apply high-contrast colored indicators based on Bazin Price Ceiling
        def format_cotacao_indicator(row):
            price = row["Cotação"]
            ceiling = row["Preço Teto"]
            formatted = Formatter.format_currency(price)
            
            if ceiling <= 0:
                return f"⚪ {formatted}"
                
            # Under Bazin margin safety:
            # 🟢 (Muito abaixo): Price is <= 80% of Ceiling Price (Excellent margin)
            # 🟡 (Abaixo/Perto): Price is between 80% and 100% of Ceiling Price (Fair margin)
            # 🔴 (Acima): Price is > Ceiling Price (Overvalued)
            if price <= (ceiling * 0.8):
                return f"🟢 {formatted}"
            elif price <= ceiling:
                return f"🟡 {formatted}"
            return f"🔴 {formatted}"

        df_display["Cotação"] = df_market.apply(format_cotacao_indicator, axis=1)
        df_display["Preço Teto"] = df_market["Preço Teto"].map(Formatter.format_currency)
        df_display["VPA"] = df_market["VPA"].map(Formatter.format_currency)
        df_display["Bai 52 semanas"] = df_market["Bai 52s"].map(Formatter.format_currency)
        df_display["Alt 52 semanas"] = df_market["Alt 52s"].map(Formatter.format_currency)
        df_display["P/VP"] = df_market["P/VP"].map(lambda x: f"{x:.2f}" if x > 0 else "N/D")
        df_display["P/L"] = df_market["P/L"].map(lambda x: f"{x:.2f}" if x > 0 else "N/D")
        df_display["DY"] = df_market["DY %"].map(lambda x: f"{x:.2f}%" if x > 0 else "N/D")
        df_display["ROE"] = df_market["ROE %"].map(lambda x: f"{x:.2f}%" if x > 0 else "N/D")

        # Show each of the last 5 years' dividend columns dynamically
        current_year = datetime.date.today().year
        last_5_years = [current_year - i for i in range(1, 6)]
        for yr in last_5_years:
            df_display[f"Div {yr}"] = df_market[f"Div {yr}"].map(Formatter.format_currency)

        df_display["Média 5 anos"] = df_market["avg_div_5y"].map(Formatter.format_currency)
        df_display["DY Médio 5 anos"] = df_market["avg_dy_5y"].map(lambda x: f"{x:.2f}%" if x > 0 else "N/D")

        st.dataframe(df_display, width="stretch", hide_index=True)

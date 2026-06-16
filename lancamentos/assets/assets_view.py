import streamlit as st
import pandas as pd
import plotly.express as px
from lancamentos.transactions_service import TransactionService
from dashboard.dashboard_service import DashboardService
from core.utils import Formatter, MarketData

class AssetsView:
    """Class responsible for rendering the detailed metrics, charts, and pivot tables per active asset."""

    def render(self):
        st.header("Detalhamento por Ativo em Carteira")

        # Fetch active assets to determine subtabs
        df_positions = DashboardService.calculate_positions()
        if df_positions.empty:
            st.info("Nenhum ativo em custódia encontrado. Faça um lançamento para visualizar.")
            return

        tickers = sorted(df_positions['ticker'].tolist())

        # Create streamlit nested tabs per active ticker
        asset_tabs = st.tabs(tickers)

        for idx, ticker in enumerate(tickers):
            with asset_tabs[idx]:
                self._render_single_asset_subtab(ticker, df_positions)

    def _render_single_asset_subtab(self, ticker, df_positions):
        # Fetch data for this specific asset
        row_pos = df_positions[df_positions['ticker'] == ticker].iloc[0]
        metadata = TransactionService.get_asset_metadata(ticker)

        # Fetch yfinance dynamic details
        with st.spinner(f"Buscando cotações em tempo real para {ticker}..."):
            details = MarketData.get_ticker_details(ticker)

        current_price = details.get("current_price", 0.0)
        dy = details.get("dy", 0.0)
        pe = details.get("pe", 0.0)
        pb = details.get("pb", 0.0)
        high_52w = details.get("high_52w", 0.0)
        low_52w = details.get("low_52w", 0.0)
        history = details.get("history", pd.DataFrame())

        # Header metadata block with UNBLOCKED GITHUB B3 LOGO CDN & DYNAMIC VECTOR FALLBACK
        # Since 'raw.githubusercontent.com' is whitelisted on all corporate networks,
        # it is guaranteed to bypass firewalls and download official B3 company logos.
        col_img, col_meta = st.columns([1, 4])
        with col_img:
            # Map sectors to gorgeous modern linear gradients
            sector_lower = str(metadata.get('sector', '')).lower()
            if any(s in sector_lower for s in ['financeiro', 'bancos', 'seguro', 'seguridade']):
                fallback_color = "%231e3c72" # Elegant Navy
            elif any(s in sector_lower for s in ['energia', 'elétrica', 'eletrica']):
                fallback_color = "%2311998e" # Emerald Green
            elif any(s in sector_lower for s in ['saneamento', 'água', 'agua', 'serviços']):
                fallback_color = "%230072ff" # Ocean Blue
            else:
                fallback_color = "%233a6073" # Slate Blue

            # The onerror fallback uses a dynamic vector SVG with the sector color and ticker text (108x108 square)
            github_logo_url = f"https://raw.githubusercontent.com/thefintz/icones-b3/main/icones/{ticker}.png"
            svg_fallback = f"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='108' height='108'><rect width='108' height='108' rx='12' fill='{fallback_color}'/><text x='54' y='62' fill='white' font-size='22' font-family='sans-serif' font-weight='bold' text-anchor='middle'>{ticker[:4]}</text></svg>"

            st.markdown(
                f'<img src="{github_logo_url}" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src=\'{svg_fallback}\';" style="width: 108px; height: 108px; border-radius: 12px; border: 2px solid white; box-shadow: 0 4px 10px rgba(0,0,0,0.15); object-fit: contain; background-color: white;">',
                unsafe_allow_html=True
            )
        with col_meta:
            st.subheader(f"{ticker} - {metadata.get('name', 'Nome não disponível')}")
            st.write(f"**CNPJ:** {metadata.get('cnpj', 'N/D')} | **Setor:** {metadata.get('sector', 'N/D')} | **Segmento:** {metadata.get('segment', 'N/D')}")

        # Fetch detailed dividends list for calculations
        df_div = TransactionService.get_asset_dividends(ticker)

        # SECTION 1 (AT THE TOP): Tabela Dinâmica do Ativo por Ano
        st.markdown("---")
        st.subheader("📅 Tabela Dinâmica de Proventos do Ativo")

        years = TransactionService.get_asset_years_with_dividends(ticker)
        if years:
            # 6 Columns row: Col 1 is Year Selector, Col 2-5 are Category Metrics, Col 6 is Paid Per Share!
            p_col1, p_col2, p_col3, p_col4, p_col5, p_col6 = st.columns([1.2, 1, 1, 1, 1, 1])

            with p_col1:
                chosen_year = st.selectbox(
                    "Filtrar Ano",
                    years,
                    key=f"year_selector_{ticker}",
                    label_visibility="visible"
                )

            df_pivot = TransactionService.get_asset_annual_dividends_pivot(ticker, chosen_year)
            val_div = df_pivot.loc[df_pivot['Categoria'] == 'Total de Dividendos', 'Valor (R$)'].values[0]
            val_jcp = df_pivot.loc[df_pivot['Categoria'] == 'Total de JCP', 'Valor (R$)'].values[0]
            val_rend = df_pivot.loc[df_pivot['Categoria'] == 'Total de Rendimentos', 'Valor (R$)'].values[0]
            val_total = df_pivot.loc[df_pivot['Categoria'] == 'Total de Proventos (Soma de todos)', 'Valor (R$)'].values[0]

            # CALCULATE DYNAMIC "TOTAL PAGO POR AÇÃO NO ANO"
            total_paid_per_share = 0.0
            if not df_div.empty:
                df_div_year = df_div[df_div['Data'].str.startswith(chosen_year)]
                for _, row in df_div_year.iterrows():
                    dt = row['Data']
                    tot = row['Total']
                    qty_on_date = TransactionService.get_quantity_on_date(ticker, dt)
                    if qty_on_date > 0:
                        total_paid_per_share += (tot / qty_on_date)

            p_col2.metric("Dividendos", Formatter.format_currency(val_div))
            p_col3.metric("JCP", Formatter.format_currency(val_jcp))
            p_col4.metric("Rendimentos", Formatter.format_currency(val_rend))
            p_col5.metric("Total Recebido", Formatter.format_currency(val_total))
            p_col6.metric(
                "Total por Ação",
                Formatter.format_currency(total_paid_per_share),
                help="Soma de todos os proventos unitários recebidos por cota neste ano selecionado"
            )

            # Render detailed summary table inside an expander so it stays compact and neat
            with st.expander("🔍 Ver Tabela Resumo Detalhada do Ano"):
                df_pivot_display = df_pivot.copy()

                # Append the Paid Per Share to the summary table as well
                df_pivot_display = pd.concat([df_pivot_display, pd.DataFrame([{
                    "Categoria": "Total Pago por Ação (Cota)", "Valor (R$)": total_paid_per_share
                }])], ignore_index=True)

                df_pivot_display['Valor (R$)'] = df_pivot_display['Valor (R$)'].map(Formatter.format_currency)
                st.dataframe(df_pivot_display, use_container_width=True, hide_index=True)
        else:
            st.info(f"Nenhum provento recebido registrado para o ativo {ticker} no banco de dados.")

        # SECTION 2: General Indicators & Metrics
        st.markdown("---")
        st.markdown("#### 📊 Indicadores Gerais do Ativo")
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)

        m_col1.metric("Preço Ajustado (Atual)", Formatter.format_currency(current_price) if current_price > 0 else "N/D")
        m_col2.metric("Preço Médio (PM)", Formatter.format_currency(row_pos['average_price']))
        m_col3.metric("Dividend Yield (DY)", f"{dy:.2f}%" if dy > 0 else "N/D")

        # Calculate Yield on Cost (YoC / 12)
        total_invested = row_pos['invested_amount']
        l12m_dividends = row_pos['l12m_dividends']
        yoc_12 = ((l12m_dividends / total_invested * 100) / 12) if total_invested > 0 else 0.0
        m_col4.metric("YoC / 12", f"{yoc_12:.2f}%")

        m_col5, m_col6, m_col7, m_col8 = st.columns(4)
        m_col5.metric("Índice P/L", f"{pe:.2f}" if pe > 0 else "N/D")
        m_col6.metric("P/VP", f"{pb:.2f}" if pb > 0 else "N/D")
        m_col7.metric("Alt. 52 Semanas", Formatter.format_currency(high_52w) if high_52w > 0 else "N/D")
        m_col8.metric("Bai. 52 Semanas", Formatter.format_currency(low_52w) if low_52w > 0 else "N/D")

        # SECTION 3: Behavior chart
        st.markdown("---")
        st.markdown("#### 📈 Comportamento Gráfico (Último Ano)")
        if not history.empty and 'Close' in history.columns:
            fig = px.line(
                history,
                y='Close',
                title=f"Histórico de Fechamento - {ticker} (Últimos 12 meses)",
                labels={'Close': 'Preço de Fechamento (R$)', 'Date': 'Data'}
            )
            fig.update_traces(line_color="#2ca02c", hovertemplate="Data: %{x}<br>Fechamento: R$ %{y:,.2f}<extra></extra>")
            fig.update_layout(yaxis_tickformat="R$ ,.2f")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Dados gráficos de cotações não disponíveis para este ativo no Yahoo Finance.")

        # SECTION 4: Tables (Transactions and Dividends side by side)
        st.markdown("---")
        st.markdown("#### 📂 Extrato de Transações e Proventos")
        col_t1, col_t2 = st.columns(2)

        with col_t1:
            st.subheader("🛒 Aportes Detalhados")
            df_tx = TransactionService.get_asset_transactions(ticker)
            if not df_tx.empty:
                # Format currency columns in DataFrame for visual table
                df_tx_display = df_tx.copy()
                df_tx_display['Valor Unitário'] = df_tx_display['Valor Unitário'].map(Formatter.format_currency)
                df_tx_display['Valor Total'] = df_tx_display['Valor Total'].map(Formatter.format_currency)
                st.dataframe(df_tx_display, use_container_width=True, hide_index=True)
            else:
                st.write("Nenhuma transação registrada.")

        with col_t2:
            st.subheader("💰 Proventos Recebidos")
            if not df_div.empty:
                # Calculate "unitário" dividend on-the-fly dynamically
                unit_vals = []
                for _, row in df_div.iterrows():
                    dt = row['Data']
                    total = row['Total']
                    qty_owned = TransactionService.get_quantity_on_date(ticker, dt)
                    unit_vals.append(total / qty_owned if qty_owned > 0 else 0.0)

                df_div_display = df_div.copy()
                df_div_display['Unitário'] = unit_vals

                # Reorder to place Unitário before Total
                df_div_display = df_div_display[['Data', 'Tipo', 'Unitário', 'Total']]

                # Format currencies
                df_div_display['Unitário'] = df_div_display['Unitário'].map(Formatter.format_currency)
                df_div_display['Total'] = df_div_display['Total'].map(Formatter.format_currency)
                st.dataframe(df_div_display, use_container_width=True, hide_index=True)
            else:
                st.write("Nenhum provento registrado.")

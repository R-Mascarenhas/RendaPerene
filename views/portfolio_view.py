import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import plotly.graph_objects as go
from core.database import db
from services.assets_service import AssetService
from core.utils.formatter import Formatter
from core.utils.market_data import MarketData

class PortfolioView:
    """Class responsible for rendering the detailed metrics, charts, and pivot tables per active asset in your portfolio."""

    def render(self):
        st.subheader("📁 Detalhamento de Ativos em Carteira")

        # Fetch active assets in portfolio
        df_positions = AssetService.calculate_positions()
        if df_positions.empty:
            st.info("Nenhum ativo em custódia encontrado. Vá na aba 'Ativos' para inserir seus ativos!")
            return

        tickers = sorted(df_positions['ticker'].tolist())

        # Create nested subtabs per active ticker (Strictly active tickers only!)
        asset_tabs = st.tabs(tickers)

        # Render each single asset subtab
        for idx, ticker in enumerate(tickers):
            with asset_tabs[idx]:
                self._render_single_asset_subtab(ticker, df_positions)

    def _render_single_asset_subtab(self, ticker, df_positions):
        row_pos = df_positions[df_positions['ticker'] == ticker].iloc[0]
        metadata = AssetService.get_asset_metadata(ticker)

        with st.spinner(f"Buscando cotações em tempo real para {ticker}..."):
            details = MarketData.get_ticker_details(ticker)

        current_price = details.get("current_price", 0.0)
        dy = details.get("dy", 0.0)
        pe = details.get("pe", 0.0)
        pb = details.get("pb", 0.0)
        high_52w = details.get("high_52w", 0.0)
        low_52w = details.get("low_52w", 0.0)

        # Header metadata block
        col_img, col_meta = st.columns([1, 4])
        with col_img:
            sector_lower = str(metadata.get('sector', '')).lower()
            if any(s in sector_lower for s in ['financeiro', 'bancos', 'seguro', 'seguridade']):
                fallback_color = "%231e3c72"
            elif any(s in sector_lower for s in ['energia', 'elétrica', 'eletrica']):
                fallback_color = "%2311998e"
            elif any(s in sector_lower for s in ['saneamento', 'água', 'agua', 'serviços']):
                fallback_color = "%230072ff"
            else:
                fallback_color = "%233a6073"

            github_logo_url = f"https://raw.githubusercontent.com/thefintz/icones-b3/main/icones/{ticker}.png"
            svg_fallback = f"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='108' height='108'><rect width='108' height='108' rx='12' fill='{fallback_color}'/><text x='54' y='62' fill='white' font-size='22' font-family='sans-serif' font-weight='bold' text-anchor='middle'>{ticker[:4]}</text></svg>"

            st.markdown(
                f'''<img src="{github_logo_url}" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='{svg_fallback}';" style="width: 144px; height: 144px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.15); object-fit: contain; background-color: white;">''',
                unsafe_allow_html=True
            )
        with col_meta:
            st.subheader(f"{ticker} - {metadata.get('name', 'Nome não disponível')}")
            st.write(f"**CNPJ:** {metadata.get('cnpj', 'N/D')}  \n**Setor:** {metadata.get('sector', 'N/D')}  \n**Segmento:** {metadata.get('segment', 'N/D')}")
        df_div = AssetService.get_asset_dividends(ticker)

        # SECTION 1 (AT THE TOP): Tabela Dinâmica do Ativo por Ano
        st.markdown("---")
        st.subheader("📅 Tabela Dinâmica de Proventos do Ativo")

        years = AssetService.get_asset_years_with_dividends(ticker)
        if years:
            p_col1, p_col2, p_col3, p_col4, p_col5, p_col6 = st.columns([1.2, 1, 1, 1, 1, 1])

            with p_col1:
                chosen_year = st.selectbox(
                    "Filtrar Ano",
                    years,
                    key=f"year_selector_{ticker}",
                    label_visibility="visible"
                )

            df_pivot = AssetService.get_asset_annual_dividends_pivot(ticker, chosen_year)
            val_div = df_pivot.loc[df_pivot['Categoria'] == 'Total de Dividendos', 'Valor (R$)'].values[0]
            val_jcp = df_pivot.loc[df_pivot['Categoria'] == 'Total de JCP', 'Valor (R$)'].values[0]
            val_rend = df_pivot.loc[df_pivot['Categoria'] == 'Total de Rendimentos', 'Valor (R$)'].values[0]
            val_total = df_pivot.loc[df_pivot['Categoria'] == 'Total de Proventos (Soma de todos)', 'Valor (R$)'].values[0]

            total_paid_per_share = 0.0
            if not df_div.empty:
                df_div_year = df_div[df_div['Data'].str.startswith(chosen_year)]
                for _, row in df_div_year.iterrows():
                    dt = row['Data']
                    tot = row['Total']
                    qty_on_date = AssetService.get_quantity_on_date(ticker, dt)
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

            with st.expander("🔍 Ver Tabela Resumo Detalhada do Ano"):
                df_pivot_display = df_pivot.copy()
                df_pivot_display = pd.concat([df_pivot_display, pd.DataFrame([{
                    "Categoria": "Total Pago por Ação (Cota)", "Valor (R$)": total_paid_per_share
                }])], ignore_index=True)

                df_pivot_display['Valor (R$)'] = df_pivot_display['Valor (R$)'].map(Formatter.format_currency)
                st.dataframe(df_pivot_display, width="stretch", hide_index=True)
        else:
            st.info(f"Nenhum provento recebido registrado para o ativo {ticker} no banco de dados.")

        # SECTION 2: General Indicators & Metrics
        st.markdown("---")
        st.markdown("#### 📊 Indicadores Gerais do Ativo")
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)

        m_col1.metric("Preço Ajustado (Atual)", Formatter.format_currency(current_price) if current_price > 0 else "N/D")
        m_col2.metric("Preço Médio (PM)", Formatter.format_currency(row_pos['average_price']))
        m_col3.metric("Dividend Yield (DY)", f"{dy:.2f}%" if dy > 0 else "N/D")

        total_invested = row_pos['invested_amount']
        l12m_dividends = row_pos['l12m_dividends']
        yoc_12 = ((l12m_dividends / total_invested * 100) / 12) if total_invested > 0 else 0.0
        m_col4.metric("YoC / 12", f"{yoc_12:.2f}%")

        m_col5, m_col6, m_col7, m_col8 = st.columns(4)
        m_col5.metric("Índice P/L", f"{pe:.2f}" if pe > 0 else "N/D")
        m_col6.metric("P/VP", f"{pb:.2f}" if pb > 0 else "N/D")
        m_col7.metric("Alt. 52 Semanas", Formatter.format_currency(high_52w) if high_52w > 0 else "N/D")
        m_col8.metric("Bai. 52 Semanas", Formatter.format_currency(low_52w) if low_52w > 0 else "N/D")

        # SECTION 3: Behavior chart (Google-Finance style dynamic range selector!)
        st.markdown("---")
        st.markdown("#### 📈 Comportamento Gráfico")

        period_map = {
            "1 Dia": "1d",
            "5 Dias": "5d",
            "1 Mês": "1mo",
            "6 Meses": "6mo",
            "YTD": "ytd",
            "1 Ano": "1y",
            "5 Anos": "5y",
            "Máximo": "max"
        }

        # Render a clean, horizontal selection bar just like Google Finance!
        chosen_label = st.radio(
            "Selecione o período do histórico de fechamento",
            options=list(period_map.keys()),
            index=5, # Default is "1 Ano" (1y)
            horizontal=True,
            key=f"period_selector_{ticker}",
            label_visibility="collapsed"
        )
        chosen_period = period_map[chosen_label]

        # Fetch the selected history dynamically from Yahoo Finance with caching
        with st.spinner(f"Buscando histórico ({chosen_label}) para {ticker}..."):
            history = MarketData.get_ticker_history(ticker, period=chosen_period)

        if not history.empty and 'Close' in history.columns:
            # 1. Calculate dynamic financial change metrics since the start of the period
            price_current = float(history['Close'].iloc[-1])
            price_initial = float(history['Close'].iloc[0])
            value_change = price_current - price_initial
            pct_change = (value_change / price_initial * 100) if price_initial > 0 else 0.0

            price_fmt = Formatter.format_currency(price_current)
            abs_change_fmt = f"{abs(value_change):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            pct_change_fmt = f"{abs(pct_change):.2f}%"

            period_label_map = {
                "1d": "hoje",
                "5d": "nos últimos 5 dias",
                "1mo": "no último mês",
                "6mo": "nos últimos 6 meses",
                "ytd": "no ano (YTD)",
                "1y": "no último ano",
                "5y": "nos últimos 5 anos",
                "max": "no período máximo"
            }
            period_label = period_label_map.get(chosen_period, "no período")

            # Style badges and absolute value text based on positive/negative change
            if value_change > 0:
                badge_html = f'<span style="background-color: #28a745; color: white; padding: 4px 10px; border-radius: 8px; font-weight: bold; font-size: 14px; margin-left: 10px; margin-right: 12px;">↑ {pct_change_fmt}</span>'
                text_html = f'<span style="color: #28a745; font-weight: bold; font-size: 15px;">+{abs_change_fmt} {period_label}</span>'
            elif value_change < 0:
                badge_html = f'<span style="background-color: #dc3545; color: white; padding: 4px 10px; border-radius: 8px; font-weight: bold; font-size: 14px; margin-left: 10px; margin-right: 12px;">↓ {pct_change_fmt}</span>'
                text_html = f'<span style="color: #dc3545; font-weight: bold; font-size: 15px;">-{abs_change_fmt} {period_label}</span>'
            else:
                badge_html = f'<span style="background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 8px; font-weight: bold; font-size: 14px; margin-left: 10px; margin-right: 12px;">0,00%</span>'
                text_html = f'<span style="color: #6c757d; font-weight: bold; font-size: 15px;">0,00 {period_label}</span>'

            header_html = f'<div style="display: flex; align-items: center; margin-top: 15px; margin-bottom: 5px;"><span style="font-size: 32px; font-weight: bold; color: inherit;">{price_fmt}</span>{badge_html}{text_html}</div>'
            st.markdown(header_html, unsafe_allow_html=True)

            # Convert index to localized string representation to completely eliminate
            # non-trading hours, nights, and weekends gaps (categorical time axis).
            if chosen_period in ["1d", "5d"]:
                x_vals = history.index.strftime('%d/%m %H:%M')
                hover_fmt = "Tempo: %{x}<br>Preço: R$ %{y:,.2f}<extra></extra>"
            else:
                x_vals = history.index.strftime('%d/%m/%Y')
                hover_fmt = "Data: %{x}<br>Fechamento: R$ %{y:,.2f}<extra></extra>"

            # Fetch raw transactions for this ticker to plot Buy/Sell markers
            conn = db.get_personal_connection()
            df_raw_tx = pd.read_sql_query(
                "SELECT date, transaction_type, quantity, unit_price FROM transactions WHERE ticker = ? ORDER BY date ASC",
                conn, params=(ticker,)
            )
            conn.close()

            # Filter transactions that fall within the current selected chart timeline
            history_start = pd.to_datetime(history.index.min()).date()
            history_end = pd.to_datetime(history.index.max()).date()

            buys_x = []
            buys_y = []
            buys_hover = []

            sells_x = []
            sells_y = []
            sells_hover = []

            if not df_raw_tx.empty:
                df_raw_tx['dt'] = pd.to_datetime(df_raw_tx['date']).dt.date
                df_filtered_tx = df_raw_tx[(df_raw_tx['dt'] >= history_start) & (df_raw_tx['dt'] <= history_end)]

                # Pre-map available historical dates to their exact coordinate in x_vals
                date_to_x = {}
                for idx, dt_val in enumerate(history.index):
                    d_key = pd.to_datetime(dt_val).date()
                    date_to_x[d_key] = x_vals[idx]

                for _, row in df_filtered_tx.iterrows():
                    t_date = row['dt']
                    t_type = row['transaction_type'] # BUY or SELL
                    qty = row['quantity']
                    t_price = row['unit_price']

                    # Find closest trading day in history index to sit the marker perfectly on the line
                    available_dates = [d for d in date_to_x.keys() if d >= t_date]
                    if not available_dates:
                        available_dates = [d for d in date_to_x.keys() if d <= t_date]

                    if available_dates:
                        match_date = min(available_dates, key=lambda d: abs((d - t_date).days))
                        x_coord = date_to_x[match_date]

                        # Fetch the closing price on that matching trading day to position the dot exactly on the line
                        chart_price = float(history.loc[history.index.map(lambda d: pd.to_datetime(d).date() == match_date), 'Close'].iloc[0])

                        op_label = "Aporte (Compra)" if t_type == "BUY" else "Resgate (Venda)"
                        hover_text = (
                            f"<b>{op_label}</b><br>"
                            f"Data: {t_date.strftime('%d/%m/%Y')}<br>"
                            f"Quantidade: {qty}<br>"
                            f"Preço Unitário: {Formatter.format_currency(t_price)}"
                        )

                        if t_type == "BUY":
                            buys_x.append(x_coord)
                            buys_y.append(chart_price)
                            buys_hover.append(hover_text)
                        elif t_type == "SELL":
                            sells_x.append(x_coord)
                            sells_y.append(chart_price)
                            sells_hover.append(hover_text)

            # Create a highly polished, pure Graph Objects figure to guarantee 100% exact layering order!
            fig = go.Figure()

            # 1. Add the main closing price line FIRST (so it sits at the bottom layer of the SVG canvas)
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=history['Close'],
                    name="Preço de Fechamento",
                    mode="lines",
                    line=dict(color="#2ca02c", width=2.5),
                    hovertemplate=hover_fmt
                )
            )

            # 2. Add gorgeous, high-contrast markers NEXT (so they are rendered absolutely ON TOP of the line)
            if buys_x:
                fig.add_trace(
                    go.Scatter(
                        x=buys_x,
                        y=buys_y,
                        name="Compra",
                        mode="markers",
                        marker=dict(
                            color="#28a745",
                            size=13, # Increased size for pristine visibility
                            symbol="triangle-up",
                            line=dict(color="white", width=1.5)
                        ),
                        text=buys_hover,
                        hovertemplate="%{text}<extra></extra>"
                    )
                )

            if sells_x:
                fig.add_trace(
                    go.Scatter(
                        x=sells_x,
                        y=sells_y,
                        name="Venda",
                        mode="markers",
                        marker=dict(
                            color="#dc3545",
                            size=13, # Increased size for pristine visibility
                            symbol="triangle-down",
                            line=dict(color="white", width=1.5)
                        ),
                        text=sells_hover,
                        hovertemplate="%{text}<extra></extra>"
                    )
                )

            # Configure X-axis as category to completely collapse any non-trading gaps,
            # and limit nticks to 8 to prevent text overlapping!
            fig.update_xaxes(
                type='category',
                tickangle=-45,
                nticks=8
            )

            fig.update_layout(yaxis_tickformat="R$ ,.2f")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Dados gráficos de cotações não disponíveis para este ativo no Yahoo Finance.")

        # SECTION 4: Tables (Transactions and Dividends side by side)
        st.markdown("---")
        st.markdown("#### 📂 Extrato de Transações e Proventos")
        col_t1, col_t2 = st.columns(2)

        with col_t1:
            st.subheader("🛒 Aportes Detalhados")
            df_tx = AssetService.get_asset_transactions(ticker)
            if not df_tx.empty:
                df_tx_display = df_tx.copy()
                df_tx_display['Valor Unitário'] = df_tx_display['Valor Unitário'].map(Formatter.format_currency)
                df_tx_display['Valor Total'] = df_tx_display['Valor Total'].map(Formatter.format_currency)
                st.dataframe(df_tx_display, width="stretch", hide_index=True)
            else:
                st.write("Nenhuma transação registrada.")

        with col_t2:
            st.subheader("💰 Proventos Recebidos")
            if not df_div.empty:
                unit_vals = []
                for _, row in df_div.iterrows():
                    dt = row['Data']
                    total = row['Total']
                    qty_owned = AssetService.get_quantity_on_date(ticker, dt)
                    unit_vals.append(total / qty_owned if qty_owned > 0 else 0.0)

                df_div_display = df_div.copy()
                df_div_display['Unitário'] = unit_vals
                df_div_display = df_div_display[['Data', 'Tipo', 'Unitário', 'Total']]

                df_div_display['Unitário'] = df_div_display['Unitário'].map(Formatter.format_currency)
                df_div_display['Total'] = df_div_display['Total'].map(Formatter.format_currency)
                st.dataframe(df_div_display, width="stretch", hide_index=True)
            else:
                st.write("Nenhum provento registrado.")

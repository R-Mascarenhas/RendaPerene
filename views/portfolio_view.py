import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.strings import *
from core.utils.formatter import Formatter
from core.utils.market_history import (
    MARKET_HISTORY_PERIODS,
    downsample_history_for_chart,
    get_closing_price_summary,
)
from services.assets_service import AssetService
from views.cached_market_data import StreamlitCachedMarketData as MarketData


class PortfolioView:
    """Class responsible for rendering the detailed metrics, charts, and pivot tables per active asset in your portfolio."""

    def render(self):
        st.subheader(MSG_PORTFOLIO_DETAIL_TITLE)

        # Fetch active assets in portfolio
        df_positions = AssetService.calculate_positions()
        if df_positions.empty:
            st.info(MSG_PORTFOLIO_EMPTY_ASSETS)
            return

        tickers = sorted(df_positions["ticker"].tolist())

        # Premium segmented control to isolate and lazy-load details for exactly one asset (extremely fast and matches tabs style!)
        selected_ticker = st.segmented_control(
            "Selecione o Ativo para Detalhar",
            options=tickers,
            default=tickers[0] if tickers else None,
            label_visibility="collapsed",
        )

        if not selected_ticker and tickers:
            selected_ticker = tickers[0]

        if selected_ticker:
            self._render_single_asset_subtab(selected_ticker, df_positions)

    def _render_single_asset_subtab(self, ticker, df_positions):
        row_pos = df_positions[df_positions["ticker"] == ticker].iloc[0]
        metadata = AssetService.get_asset_metadata(ticker)

        with st.spinner(f"Buscando cotações em tempo real para {ticker}..."):
            details = MarketData.get_ticker_market_analysis(ticker)

        self._render_header_metadata_block(ticker, metadata)
        self._render_behavior_chart(ticker, details)
        df_div = AssetService.get_asset_dividends(ticker)
        self._render_proventos_pivot_table(ticker, df_div)
        self._render_indicators_block(row_pos, details)
        self._render_transactions_and_dividends_tables(ticker, df_div)

    def _render_header_metadata_block(self, ticker, metadata):
        """Renders the top header block containing the asset's logo, name, and main registry details."""
        col_img, col_meta = st.columns([1, 4])
        with col_img:
            sector_lower = str(metadata.get("sector", "")).lower()
            if any(s in sector_lower for s in ["financeiro", "bancos", "seguro", "seguridade"]):
                fallback_color = "#1e3c72"
            elif any(s in sector_lower for s in ["energia", "elétrica", "eletrica"]):
                fallback_color = "#11998e"
            elif any(s in sector_lower for s in ["saneamento", "água", "agua", "serviços"]):
                fallback_color = "#0072ff"
            else:
                fallback_color = "#3a6073"

            github_logo_url = (
                f"https://raw.githubusercontent.com/thefintz/icones-b3/main/icones/{ticker}.png"
            )

            import base64

            svg_markup = f"<svg xmlns='http://www.w3.org/2000/svg' width='108' height='108'><rect width='108' height='108' rx='12' fill='{fallback_color}'/><text x='54' y='62' fill='white' font-size='22' font-family='sans-serif' font-weight='bold' text-anchor='middle'>{ticker[:4]}</text></svg>"
            svg_base64 = base64.b64encode(svg_markup.encode("utf-8")).decode("utf-8")
            svg_fallback = f"data:image/svg+xml;base64,{svg_base64}"

            st.markdown(
                f'''<img src="{github_logo_url}" referrerpolicy="no-referrer" onerror="this.onerror=null; this.src='{svg_fallback}';" style="width: 144px; height: 144px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.15); object-fit: contain; background-color: white;">''',
                unsafe_allow_html=True,
            )
        with col_meta:
            st.subheader(f"{ticker} - {metadata.get('name', 'Nome não disponível')}")
            st.write(
                MSG_ASSET_INFO_CNPJ.format(
                    cnpj=metadata.get("cnpj", "N/D"),
                    sector=metadata.get("sector", "N/D"),
                    segment=metadata.get("segment", "N/D"),
                )
            )

    def _render_proventos_pivot_table(self, ticker, df_div):
        """SECTION 1: Renders the annual pivot table of received dividends and metrics."""
        st.markdown("---")
        st.subheader(MSG_DIVIDENDS_DYNAMIC_TABLE)

        years = AssetService.get_asset_years_with_dividends(ticker)
        if years:
            p_col1, p_col2, p_col3, p_col4, p_col5, p_col6, p_col7 = st.columns(
                [0.5, 1, 1, 1, 1, 1, 1]
            )

            with p_col1:
                chosen_year = st.selectbox(
                    "Filtrar Ano", years, key=f"year_selector_{ticker}", label_visibility="visible"
                )

            df_pivot = AssetService.get_asset_annual_dividends_pivot(ticker, chosen_year)
            val_div = df_pivot.loc[
                df_pivot["Categoria"] == "Total de Dividendos", "Valor (R$)"
            ].values[0]
            val_jcp = df_pivot.loc[df_pivot["Categoria"] == "Total de JCP", "Valor (R$)"].values[0]
            val_rend = df_pivot.loc[
                df_pivot["Categoria"] == "Total de Rendimentos", "Valor (R$)"
            ].values[0]
            val_total = df_pivot.loc[
                df_pivot["Categoria"] == "Total de Proventos (Soma de todos)", "Valor (R$)"
            ].values[0]

            metrics = AssetService.get_annual_dividends_metrics(ticker, chosen_year, df_div)
            total_paid_per_share = metrics["total_paid_per_share"]
            qty_end_of_year = metrics["qty_end_of_year"]
            qty_prev_year = metrics["qty_prev_year"]
            prev_year = metrics["prev_year"]
            diff = qty_end_of_year - qty_prev_year

            qty_delta = f"{diff:+d} cotas" if diff != 0 else None

            if diff > 0:
                qty_help = f"Aumento de +{diff} cotas em relação ao ano de {prev_year} (posição anterior: {qty_prev_year} cotas)."
            elif diff < 0:
                qty_help = f"Redução de {diff} cotas em relação ao ano de {prev_year} (posição anterior: {qty_prev_year} cotas)."
            else:
                qty_help = HELP_QTY_NO_CHANGE.format(
                    prev_year=prev_year, qty_prev_year=qty_prev_year
                )

            p_col2.metric(LABEL_DIVIDENDS, Formatter.format_currency(val_div))
            p_col3.metric(LABEL_JCP, Formatter.format_currency(val_jcp))
            p_col4.metric(LABEL_YIELDS, Formatter.format_currency(val_rend))
            p_col5.metric(LABEL_TOTAL_RECEIVED, Formatter.format_currency(val_total))
            p_col6.metric(
                LABEL_QUANTITY, f"{qty_end_of_year} cotas", delta=qty_delta, help=qty_help
            )
            p_col7.metric(
                LABEL_TOTAL_PER_SHARE,
                Formatter.format_currency(total_paid_per_share),
                help=HELP_TOTAL_PAID_PER_SHARE,
            )

            with st.expander(MSG_VIEW_DETAILED_YEAR_TABLE):
                df_pivot_display = df_pivot.copy()
                df_pivot_display = pd.concat(
                    [
                        df_pivot_display,
                        pd.DataFrame(
                            [
                                {
                                    "Categoria": "Total Pago por Ação (Cota)",
                                    "Valor (R$)": total_paid_per_share,
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )

                df_pivot_display["Valor (R$)"] = df_pivot_display["Valor (R$)"].map(
                    Formatter.format_currency
                )
                st.dataframe(df_pivot_display, width="stretch", hide_index=True)
        else:
            st.info(MSG_NO_DIVIDENDS_RECORDED.format(ticker=ticker))

    def _render_indicators_block(self, row_pos, details):
        """SECTION 2: Renders general financial and valuation indicators for the asset."""
        current_price = details.get("current_price", 0.0)
        dy = details.get("dy", 0.0)
        pe = details.get("pe", 0.0)
        pb = details.get("pb", 0.0)
        high_52w = details.get("high_52w", 0.0)
        low_52w = details.get("low_52w", 0.0)

        # Calculate actual adjusted price: (invested_amount - total_dividends) / quantity
        qty = row_pos["quantity"]
        total_dividends = row_pos["total_dividends"]
        invested_amount = row_pos["invested_amount"]
        adjusted_price = (invested_amount - total_dividends) / qty if qty > 0 else 0.0

        st.markdown("---")
        st.markdown(MSG_ASSET_GENERAL_INDICATORS)
        m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)

        m_col1.metric(
            LABEL_CURRENT_PRICE,
            Formatter.format_currency(current_price) if current_price > 0 else "N/D",
            help=HELP_CURRENT_PRICE,
        )
        m_col2.metric(
            LABEL_AVG_PRICE,
            Formatter.format_currency(row_pos["average_price"]),
            help=HELP_AVG_PRICE,
        )
        m_col3.metric(
            DISPLAY_ADJ_PRICE, Formatter.format_currency(adjusted_price), help=HELP_ADJ_PRICE
        )
        m_col4.metric(LABEL_DY, f"{dy:.2f}%" if dy > 0 else "N/D", help=HELP_DY)

        total_invested = row_pos["invested_amount"]
        l12m_dividends = row_pos["l12m_dividends"]
        yoc_12 = ((l12m_dividends / total_invested * 100) / 12) if total_invested > 0 else 0.0
        m_col5.metric(LABEL_YOC_12_MONTHLY, f"{yoc_12:.2f}%", help=HELP_YOC_12)

        m_col6_row2, m_col7_row2, m_col8_row2, m_col9_row2 = st.columns(4)
        m_col6_row2.metric(
            LABEL_PE_RATIO,
            Formatter.format_market_value(pe, "number"),
            help=HELP_PE_RATIO,
        )
        m_col7_row2.metric(
            LABEL_P_VP,
            Formatter.format_market_value(pb, "number"),
            help=HELP_P_VP,
        )
        m_col8_row2.metric(
            LABEL_HIGH_52W, Formatter.format_currency(high_52w) if high_52w > 0 else "N/D"
        )
        m_col9_row2.metric(
            LABEL_LOW_52W, Formatter.format_currency(low_52w) if low_52w > 0 else "N/D"
        )

    def _render_behavior_chart(self, ticker, details):
        """SECTION 3: Renders the historical behavior chart with buy/sell annotations."""
        st.markdown("---")
        st.markdown(MSG_CHART_BEHAVIOR)

        chosen_label = st.radio(
            "Selecione o período do histórico de fechamento",
            options=list(MARKET_HISTORY_PERIODS),
            index=5,  # Default is "1 Ano" (1y)
            horizontal=True,
            key=f"period_selector_{ticker}",
            label_visibility="collapsed",
        )
        chosen_period, chosen_interval = MARKET_HISTORY_PERIODS[chosen_label]

        # Fetch the selected history dynamically from Yahoo Finance with caching
        with st.spinner(f"Buscando histórico ({chosen_label}) para {ticker}..."):
            history = MarketData.get_ticker_history(
                ticker, period=chosen_period, interval=chosen_interval
            )

        if not history.empty and "Close" in history.columns:
            summary = get_closing_price_summary(history)
            if summary is None:
                st.info(MSG_NO_YF_CHART_DATA)
                return
            history = summary["history"]

            # Downsample 'max' if duration is > 8 years
            if chosen_period == "max":
                days_span = (
                    pd.to_datetime(history.index.max()).date()
                    - pd.to_datetime(history.index.min()).date()
                ).days
                if days_span > (8 * 365.25):
                    history = downsample_history_for_chart(history, step=3)

            # 1. Calculate dynamic financial change metrics since the start of the period
            price_current = summary["current_price"]

            is_1d_not_open_yet = (
                chosen_period == "1d"
                and pd.to_datetime(history.index.max()).date() != datetime.date.today()
            )

            if is_1d_not_open_yet:
                value_change = 0.0
                pct_change = 0.0
            else:
                value_change = summary["value_change"]
                pct_change = summary["change_pct"]

            price_fmt = Formatter.format_currency(price_current)
            abs_change_fmt = (
                f"{abs(value_change):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
            pct_change_fmt = f"{abs(pct_change):.2f}%"

            period_label_map = {
                "1d": "hoje",
                "5d": "nos últimos 5 dias",
                "1mo": "no último mês",
                "6mo": "nos últimos 6 meses",
                "ytd": "no ano (YTD)",
                "1y": "no último ano",
                "5y": "nos últimos 5 anos",
                "max": "no período máximo",
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
                badge_html = '<span style="background-color: #6c757d; color: white; padding: 4px 10px; border-radius: 8px; font-weight: bold; font-size: 14px; margin-left: 10px; margin-right: 12px;">0,00%</span>'
                text_html = f'<span style="color: #6c757d; font-weight: bold; font-size: 15px;">0,00 {period_label}</span>'

            header_html = f'<div style="display: flex; align-items: center; margin-top: 15px; margin-bottom: 5px;"><span style="font-size: 32px; font-weight: bold; color: inherit;">{price_fmt}</span>{badge_html}{text_html}</div>'
            st.markdown(header_html, unsafe_allow_html=True)

            # Convert index to localized string representation to completely eliminate
            # non-trading hours, nights, and weekends gaps (categorical time axis).
            if chosen_period in ["1d", "5d"]:
                x_vals = history.index.strftime("%d/%m %H:%M")
                hover_fmt = "Preço: R$ %{y:,.2f}<extra></extra>"
            else:
                x_vals = history.index.strftime("%d/%m/%Y")
                hover_fmt = "Fechamento: R$ %{y:,.2f}<extra></extra>"

            # Fetch raw transactions for this ticker to plot Buy/Sell markers
            df_raw_tx = AssetService.get_raw_transactions_for_chart(ticker)

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
                df_raw_tx["dt"] = pd.to_datetime(df_raw_tx["date"]).dt.date
                df_filtered_tx = df_raw_tx[
                    (df_raw_tx["dt"] >= history_start) & (df_raw_tx["dt"] <= history_end)
                ]

                # Pre-map available historical dates to their exact coordinate in x_vals
                date_to_x = {}
                for idx, dt_val in enumerate(history.index):
                    d_key = pd.to_datetime(dt_val).date()
                    date_to_x[d_key] = x_vals[idx]

                for _, row in df_filtered_tx.iterrows():
                    t_date = row["dt"]
                    t_type = row["transaction_type"]  # BUY or SELL
                    qty = row["quantity"]
                    t_price = row["unit_price"]

                    # Find closest trading day in history index to sit the marker perfectly on the line
                    available_dates = [d for d in date_to_x if d >= t_date]
                    if not available_dates:
                        available_dates = [d for d in date_to_x if d <= t_date]

                    if available_dates:
                        match_date = min(available_dates, key=lambda d: abs((d - t_date).days))
                        x_coord = date_to_x[match_date]

                        # Fetch the closing price on that matching trading day to position the dot exactly on the line
                        chart_price = float(
                            history.loc[
                                history.index.map(lambda d: pd.to_datetime(d).date() == match_date),
                                "Close",
                            ].iloc[0]
                        )

                        op_label = "Aporte (Compra)" if t_type == "BUY" else "Resgate (Venda)"
                        hover_text = (
                            f"<b>{op_label}</b><br>"
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

            line_color = "#2ca02c"
            if is_1d_not_open_yet:
                line_color = "#6c757d"

            # 1. Add the main closing price line FIRST (so it sits at the bottom layer of the SVG canvas)
            fig.add_trace(
                go.Scatter(
                    x=x_vals,
                    y=history["Close"],
                    name="Preço de Fechamento",
                    mode="lines",
                    line=dict(color=line_color, width=2.5),
                    hovertemplate=hover_fmt,
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
                            size=13,  # Increased size for pristine visibility
                            symbol="triangle-up",
                            line=dict(color="white", width=1.5),
                        ),
                        text=buys_hover,
                        hovertemplate="%{text}<extra></extra>",
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
                            size=13,  # Increased size for pristine visibility
                            symbol="triangle-down",
                            line=dict(color="white", width=1.5),
                        ),
                        text=sells_hover,
                        hovertemplate="%{text}<extra></extra>",
                    )
                )

            # Configure X-axis as category to completely collapse any non-trading gaps,
            # and limit nticks to 8 to prevent text overlapping!
            fig.update_xaxes(type="category", tickangle=-45, nticks=8)

            fig.update_layout(yaxis_tickformat="R$ ,.2f", hovermode="x unified")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info(MSG_NO_YF_CHART_DATA)

    def _render_transactions_and_dividends_tables(self, ticker, df_div):
        """SECTION 4: Renders detailed tables for deposits and dividends side-by-side."""
        st.markdown("---")
        st.markdown(MSG_TX_EXTRACT_TITLE)
        col_t1, col_t2 = st.columns(2)

        with col_t1:
            st.subheader(MSG_DETAILED_CONTRIBUTIONS)
            df_tx = AssetService.get_asset_transactions(ticker)
            if not df_tx.empty:
                df_tx_display = df_tx.copy()
                df_tx_display["Valor Unitário"] = df_tx_display["Valor Unitário"].map(
                    Formatter.format_currency
                )
                df_tx_display["Valor Total"] = df_tx_display["Valor Total"].map(
                    Formatter.format_currency
                )
                st.dataframe(df_tx_display, width="stretch", hide_index=True)
            else:
                st.write(MSG_NO_TX_RECORDED)

        with col_t2:
            st.subheader(MSG_RECEIVED_DIVIDENDS)
            if not df_div.empty:
                df_div_display = AssetService.get_asset_dividends_detailed(ticker)
                df_div_display["Unitário"] = df_div_display["Unitário"].map(
                    Formatter.format_currency
                )
                df_div_display["Total"] = df_div_display["Total"].map(Formatter.format_currency)
                st.dataframe(df_div_display, width="stretch", hide_index=True)
            else:
                st.write(MSG_NO_DIVIDENDS_RECORDED_SIMPLE)

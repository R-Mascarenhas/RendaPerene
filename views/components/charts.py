import streamlit as st

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from core.constants import (
    MONTHS_PT, TICKER, SECTOR, CURRENT_VALUE, INVESTED_AMOUNT, TOTAL_DIVIDENDS,
    MONTH_STR, MONTH_DISPLAY, CUMULATIVE_INVESTED, PLANNED_INVESTED, CUMULATIVE_DIVIDENDS,
    PLANNED_DIVIDENDS, MONTHLY_DIVIDEND, ANNUAL_INTEREST_RATE, PLANNING_START_DATE
)
from core.strings import (
    MSG_HISTORIC_EVOLUTION_TITLE, MSG_HISTORIC_CONTRIBUTIONS_TITLE,
)
from core.utils.formatter import Formatter
from services.assets_service import AssetService
from services.planning_service import SimulationService

class DashboardCharts:
    """Displays all interactive Plotly figures on the Dashboard."""

    def render(self, df_positions):
        self._render_top_charts(df_positions)
        self._render_evolution_chart()
        self._render_monthly_contributions_chart()

    def _render_top_charts(self, df_positions):
        chart_col1, chart_col2, chart_col3 = st.columns(3)
        with chart_col1:
            # Group df_positions by SECTOR to calculate sector sum and build custom hover details
            total_portfolio_equity = df_positions[CURRENT_VALUE].sum()
            sector_groups = df_positions.groupby(SECTOR)

            sector_data = []
            for sector_name, group in sector_groups:
                sector_val = group[CURRENT_VALUE].sum()
                sector_pct = (sector_val / total_portfolio_equity * 100) if total_portfolio_equity > 0 else 0.0

                # Sort tickers within sector by CURRENT_VALUE descending
                group_sorted = group.sort_values(by=CURRENT_VALUE, ascending=False)

                # Build detail lines for each ticker
                details = []
                for _, row in group_sorted.iterrows():
                    ticker = row[TICKER]
                    ticker_val = row[CURRENT_VALUE]
                    ticker_pct_portfolio = (ticker_val / total_portfolio_equity * 100) if total_portfolio_equity > 0 else 0.0
                    ticker_pct_sector = (ticker_val / sector_val * 100) if sector_val > 0 else 0.0

                    formatted_val = Formatter.format_currency(ticker_val)
                    details.append(f"  • {ticker}: {formatted_val} ({ticker_pct_sector:.2f}% do setor / {ticker_pct_portfolio:.2f}% do total)")

                details_str = "<br>".join(details)

                sector_data.append({
                    SECTOR: sector_name,
                    CURRENT_VALUE: sector_val,
                    'Percentual': sector_pct,
                    'Detalhes': details_str
                })

            df_sectors = pd.DataFrame(sector_data)

            fig_sectors = px.pie(
                df_sectors,
                names=SECTOR,
                values=CURRENT_VALUE,
                title="Divisão do Patrimônio por Setor",
                hole=0.4,
                custom_data=['Detalhes']
            )
            fig_sectors.update_traces(
                textposition='inside',
                textinfo='percent+label',
                hovertemplate="<b>%{label}</b><br>Valor Total: R$ %{value:,.2f} (%{percent})<br><br><b>Ativos:</b><br>%{customdata[0]}<extra></extra>"
            )
            st.plotly_chart(fig_sectors, width="stretch")

        with chart_col2:
            df_chart_evol = df_positions[[TICKER, INVESTED_AMOUNT, CURRENT_VALUE]].copy()
            df_chart_evol = df_chart_evol.rename(columns={INVESTED_AMOUNT: 'Investido', CURRENT_VALUE: 'Atual'})
            df_chart_evol = df_chart_evol.sort_values(by="Investido", ascending=False)

            fig_evol = px.bar(
                df_chart_evol,
                x=TICKER,
                y=["Investido", "Atual"],
                barmode="group",
                title="Evolução por ativo",
                labels={"value": "Valores (R$)", TICKER: "Ticker", "variable": "Legenda"},
                color_discrete_sequence=["#1f77b4", "#2ca02c"]
            )
            fig_evol.update_traces(hovertemplate="<b>%{x}</b><br>Valor: R$ %{y:,.2f}<extra></extra>")
            fig_evol.update_layout(
                yaxis_tickformat="R$ ,.2f",
                hovermode="x unified"
            )
            st.plotly_chart(fig_evol, width="stretch")

        with chart_col3:
            if 'total_yoc' not in df_positions.columns:
                df_positions['total_yoc'] = (df_positions[TOTAL_DIVIDENDS] / df_positions[INVESTED_AMOUNT]) * 100

            df_chart_yoc = df_positions[df_positions['total_yoc'] > 0].sort_values(by='total_yoc', ascending=True)
            if not df_chart_yoc.empty:
                fig_proventos = px.bar(
                    df_chart_yoc,
                    x='total_yoc',
                    y=TICKER,
                    orientation="h",
                    title="Eficiência por Ativo (Yield on Cost Total)",
                    labels={'total_yoc': "Yield on Cost (%)", TICKER: "Ticker"},
                    color='total_yoc',
                    color_continuous_scale="Viridis"
                )
                fig_proventos.update_traces(hovertemplate="<b>%{y}</b><br>Yield on Cost: %{x:.2f}%<extra></extra>")
                fig_proventos.update_layout(
                    xaxis_tickformat=".2f",
                    hovermode="y unified"
                )
                st.plotly_chart(fig_proventos, width="stretch")

    def _render_evolution_chart(self):
        st.markdown("---")
        config = SimulationService.get_configuration()
        start_date = config.get(PLANNING_START_DATE) if config else None
        df_evolution = AssetService.calculate_historical_evolution(start_date=start_date)

        if not df_evolution.empty:
            st.subheader(MSG_HISTORIC_EVOLUTION_TITLE)

            df_evolution = df_evolution.sort_values(by=MONTH_STR).reset_index(drop=True)
            df_evolution[MONTH_DISPLAY] = df_evolution[MONTH_STR].apply(Formatter.format_month_year)

            # Pull dynamic values
            if config:
                annual_interest_rate_val = float(config[ANNUAL_INTEREST_RATE])
                monthly_interest_rate = (1 + annual_interest_rate_val / 100) ** (1 / 12) - 1
            else:
                monthly_interest_rate = (1 + 6.0 / 100) ** (1 / 12) - 1

            monthly_contribution = SimulationService.get_required_contribution()

            # Call centralized, DRY-compliant mathematical projection service method!
            df_evolution = SimulationService.calculate_planned_historical_evolution(df_evolution, monthly_contribution, monthly_interest_rate)

            # Dual-timeline multi-axis figure
            fig_multi = make_subplots(specs=[[{"secondary_y": True}]])

            # 1. Real Invested Capital (Solid Blue)
            fig_multi.add_trace(
                go.Scatter(
                    x=df_evolution[MONTH_DISPLAY],
                    y=df_evolution[CUMULATIVE_INVESTED],
                    name="Valor Investido",
                    mode="lines+markers",
                    line=dict(color="#1f77b4", width=3),
                    marker=dict(size=6),
                    hovertemplate="Valor Investido: R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=False
            )

            # 2. Planned Capital / Target (Dashed Blue)
            fig_multi.add_trace(
                go.Scatter(
                    x=df_evolution[MONTH_DISPLAY],
                    y=df_evolution[PLANNED_INVESTED],
                    name="Planejado (Meta)",
                    mode="lines",
                    line=dict(color="#1f77b4", width=2, dash="dash"),
                    hovertemplate="Planejado (Meta): R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=False
            )

            # 3. Real Total Dividends Received (Solid Green)
            fig_multi.add_trace(
                go.Scatter(
                    x=df_evolution[MONTH_DISPLAY],
                    y=df_evolution[CUMULATIVE_DIVIDENDS],
                    name="Total de Proventos",
                    mode="lines+markers",
                    line=dict(color="#2ca02c", width=3),
                    marker=dict(size=6),
                    hovertemplate="Total de Proventos: R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=False
            )

            # 4. Planned Dividends (Dashed Green)
            fig_multi.add_trace(
                go.Scatter(
                    x=df_evolution[MONTH_DISPLAY],
                    y=df_evolution[PLANNED_DIVIDENDS],
                    name="Proventos Planejados",
                    mode="lines",
                    line=dict(color="#2ca02c", width=2, dash="dash"),
                    hovertemplate="Proventos Planejados: R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=False
            )

            bar_labels = [f"R$ {val:,.0f}".replace(",", ".") if val > 0 else "" for val in df_evolution[MONTHLY_DIVIDEND]]

            # 5. Monthly Dividends received (Translucent Yellow Bar)
            fig_multi.add_trace(
                go.Bar(
                    x=df_evolution[MONTH_DISPLAY],
                    y=df_evolution[MONTHLY_DIVIDEND],
                    name="Proventos (Mês)",
                    marker_color="rgba(242, 196, 26, 0.6)",
                    text=bar_labels,
                    textposition="outside",
                    textfont=dict(size=12, color="#f2c41a", family="sans-serif"),
                    hovertemplate="Proventos (Mês): R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=True
            )

            fig_multi.update_layout(
                title_text="Histórico de Evolução Patrimonial: Real vs. Planejado",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0.01),
                uniformtext=dict(minsize=12, mode="show")
            )

            fig_multi.update_yaxes(title_text="Valores Acumulados (R$)", tickformat="R$ ,.2f", secondary_y=False)
            fig_multi.update_yaxes(title_text="Proventos Mensais Recebidos (R$)", tickformat="R$ ,.2f", secondary_y=True)
            fig_multi.update_xaxes(title_text="Linha do Tempo (Mês/Ano)", type="category", tickangle=-45, tickmode="linear")

            st.plotly_chart(fig_multi, width="stretch")

    def _render_monthly_contributions_chart(self):
        st.markdown("---")
        config = SimulationService.get_configuration()
        start_date = config.get(PLANNING_START_DATE) if config else None
        df_contribs = AssetService.get_monthly_contributions_by_year(start_date=start_date)
        if not df_contribs.empty:
            st.subheader(MSG_HISTORIC_CONTRIBUTIONS_TITLE)

            df_contribs['Mês'] = df_contribs['month'].map(MONTHS_PT)
            df_contribs = df_contribs.sort_values(by=['month'])

            meses_completos = list(MONTHS_PT.values())
            anos_ordenados = sorted(df_contribs['year'].unique().tolist())

            fig_contribs = px.bar(
                df_contribs,
                x="Mês",
                y="amount",
                color="year",
                barmode="group",
                title="Aportes Mensais",
                labels={"amount": "Valor Aportado (R$)", "Mês": "Mês", "year": "Ano"},
                category_orders={"year": anos_ordenados}
            )

            fig_contribs.update_traces(hovertemplate="Ano: %{data.name}<br>Aporte: R$ %{y:,.2f}<extra></extra>")
            fig_contribs.update_xaxes(categoryorder='array', categoryarray=meses_completos)
            fig_contribs.update_layout(
                yaxis_tickformat="R$ ,.2f",
                hovermode="x unified"
            )

            st.plotly_chart(fig_contribs, width="stretch")

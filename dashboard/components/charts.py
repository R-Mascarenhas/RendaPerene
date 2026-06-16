import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from core.constants import MONTHS_PT
from core.utils import Formatter
from dashboard.dashboard_service import DashboardService

class DashboardCharts:
    """Displays all interactive Plotly figures on the Dashboard."""

    def render(self, df_positions):
        self._render_top_charts(df_positions)
        self._render_evolution_chart()
        self._render_monthly_contributions_chart()

    def _render_top_charts(self, df_positions):
        chart_col1, chart_col2, chart_col3 = st.columns(3)
        with chart_col1:
            fig_sectors = px.pie(
                df_positions,
                names="sector",
                values="current_value",
                title="Divisão do Patrimônio por Setor",
                hole=0.4
            )
            fig_sectors.update_traces(textposition='inside', textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Valor: R$ %{value:,.2f} (%{percent})<extra></extra>")
            st.plotly_chart(fig_sectors, use_container_width=True)

        with chart_col2:
            df_chart_evol = df_positions[['ticker', 'invested_amount', 'current_value']].copy()
            df_chart_evol = df_chart_evol.rename(columns={'invested_amount': 'Investido', 'current_value': 'Atual'})
            df_chart_evol = df_chart_evol.sort_values(by="Investido", ascending=False)
            
            fig_evol = px.bar(
                df_chart_evol, 
                x="ticker", 
                y=["Investido", "Atual"],
                barmode="group",
                title="Evolução por ativo",
                labels={"value": "Valores (R$)", "ticker": "Ticker", "variable": "Legenda"},
                color_discrete_sequence=["#1f77b4", "#2ca02c"]
            )
            fig_evol.update_traces(hovertemplate="<b>%{x}</b><br>Valor: R$ %{y:,.2f}<extra></extra>")
            fig_evol.update_layout(yaxis_tickformat="R$ ,.2f")
            st.plotly_chart(fig_evol, use_container_width=True)

        with chart_col3:
            df_chart_prov = df_positions[df_positions["total_dividends"] > 0].sort_values(by="total_dividends", ascending=True)
            if not df_chart_prov.empty:
                fig_proventos = px.bar(
                    df_chart_prov,
                    x="total_dividends",
                    y="ticker",
                    orientation="h",
                    title="Resultado por Ativo (Proventos Recebidos)",
                    labels={"total_dividends": "Proventos (R$)", "ticker": "Ticker"},
                    color="total_dividends",
                    color_continuous_scale="Viridis"
                )
                fig_proventos.update_traces(hovertemplate="<b>%{y}</b><br>Proventos: R$ %{x:,.2f}<extra></extra>")
                fig_proventos.update_layout(xaxis_tickformat="R$ ,.2f")
                st.plotly_chart(fig_proventos, use_container_width=True)

    def _render_evolution_chart(self):
        st.markdown("---")
        df_evolution = DashboardService.calculate_historical_evolution()
        
        if not df_evolution.empty:
            st.subheader("📈 Evolução Patrimonial Histórica & Planejamento")
            
            df_evolution = df_evolution.sort_values(by="month_str").reset_index(drop=True)
            df_evolution['month_display'] = df_evolution['month_str'].apply(Formatter.format_month_year)
            
            planned_cumulative = []
            planned_dividends_cumulative = []
            
            # Start from the actual first month's cumulative invested
            prev_planned_equity = df_evolution.loc[0, 'cumulative_invested']
            prev_planned_dividends = 0.0
            
            # Dynamic interest rate and contribution from the configuration database
            from planning.planning_service import SimulationService
            config = SimulationService.get_configuration()
            if config:
                annual_interest_rate = float(config['annual_interest_rate'])
                monthly_interest_rate = (1 + annual_interest_rate / 100) ** (1 / 12) - 1
            else:
                monthly_interest_rate = (1 + 6.0 / 100) ** (1 / 12) - 1
                
            monthly_contribution = SimulationService.get_current_required_contribution()
            
            for idx, row in df_evolution.iterrows():
                if idx == 0:
                    planned_cumulative.append(prev_planned_equity)
                    planned_dividends_cumulative.append(prev_planned_dividends)
                else:
                    last_equity = planned_cumulative[-1]
                    last_dividends = planned_dividends_cumulative[-1]
                    
                    period_interest = last_equity * monthly_interest_rate
                    next_equity = last_equity * (1 + monthly_interest_rate) + monthly_contribution
                    next_dividends = last_dividends + period_interest
                    
                    planned_cumulative.append(next_equity)
                    planned_dividends_cumulative.append(next_dividends)
                    
            df_evolution['planned_equity'] = planned_cumulative
            df_evolution['planned_dividends'] = planned_dividends_cumulative
            
            # Dual-timeline multi-axis figure
            fig_multi = make_subplots(specs=[[{"secondary_y": True}]])
            
            # 1. Real Invested Capital (Solid Blue)
            fig_multi.add_trace(
                go.Scatter(
                    x=df_evolution['month_display'],
                    y=df_evolution['cumulative_invested'],
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
                    x=df_evolution['month_display'],
                    y=df_evolution['planned_equity'],
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
                    x=df_evolution['month_display'],
                    y=df_evolution['cumulative_dividends'],
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
                    x=df_evolution['month_display'],
                    y=df_evolution['planned_dividends'],
                    name="Proventos Planejados",
                    mode="lines",
                    line=dict(color="#2ca02c", width=2, dash="dash"),
                    hovertemplate="Proventos Planejados: R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=False
            )
            
            # Labels for the columns
            bar_labels = [f"R$ {val:,.0f}".replace(",", ".") if val > 0 else "" for val in df_evolution['monthly_dividend']]
            
            # 5. Monthly Dividends received (Translucent Yellow Bar)
            fig_multi.add_trace(
                go.Bar(
                    x=df_evolution['month_display'],
                    y=df_evolution['monthly_dividend'],
                    name="Proventos (Mês)",
                    marker_color="rgba(242, 196, 26, 0.6)",
                    text=bar_labels,
                    textposition="outside",
                    hovertemplate="Proventos (Mês): R$ %{y:,.2f}<extra></extra>"
                ),
                secondary_y=True
            )
            
            fig_multi.update_layout(
                title_text="Histórico de Evolução Patrimonial: Real vs. Planejado",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0.01)
            )
            
            fig_multi.update_yaxes(title_text="Valores Acumulados (R$)", tickformat="R$ ,.2f", secondary_y=False)
            fig_multi.update_yaxes(title_text="Proventos Mensais Recebidos (R$)", tickformat="R$ ,.2f", secondary_y=True)
            fig_multi.update_xaxes(title_text="Linha do Tempo (Mês/Ano)", type="category", tickangle=-45, tickmode="linear")
            
            st.plotly_chart(fig_multi, use_container_width=True)

    def _render_monthly_contributions_chart(self):
        st.markdown("---")
        df_contribs = DashboardService.get_monthly_contributions_by_year()
        if not df_contribs.empty:
            st.subheader("📊 Histórico de Aportes por Ano e Mês")
            
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
            
            fig_contribs.update_traces(hovertemplate="Ano: %{data.name}<br>Mês: %{x}<br>Aporte: R$ %{y:,.2f}<extra></extra>")
            fig_contribs.update_xaxes(categoryorder='array', categoryarray=meses_completos)
            fig_contribs.update_layout(yaxis_tickformat="R$ ,.2f")
            
            st.plotly_chart(fig_contribs, use_container_width=True)

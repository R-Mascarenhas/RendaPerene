import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from planning.planning_service import SimulationService
from dashboard.dashboard_service import DashboardService
from core.utils import Formatter, TrendlineCalculator

class ProjectionChartWidget:
    """Displays highly polished, interactive compounding projection and comparative curves."""

    def render(self, sim):
        # 1. RENDER SECTION 1: PROJECTION CHARTS (SIDE BY SIDE)
        st.markdown("---")
        chart_col1, chart_col2 = st.columns(2)

        self._render_cumulative_projection(sim, chart_col1)
        self._render_monthly_comparison(sim, chart_col2)

        # 2. RENDER SECTION 2: HISTORICAL REAL VS PLANNED (SIDE BY SIDE WITH EXTRAPOLATION)
        self._render_historical_comparisons(extrapolation=12)

    def _render_cumulative_projection(self, sim, container):
        """Renders the cumulative long-term projection area chart with crossover markers."""
        df_projection = SimulationService.build_projection_dataframe(
            sim["start_age_years"],
            sim["remaining_time_months"],
            sim["total_invested"],
            sim["updated_monthly_contribution"],
            sim["monthly_interest_rate"],
            sim["target_equity"]
        )

        if df_projection.empty:
            return

        with container:
            st.subheader("📈 Projeção Acumulada de Longo Prazo")
            fig = go.Figure()

            # Trace 1: Patrimônio Projetado (Green Area with Transparency)
            fig.add_trace(
                go.Scatter(
                    x=df_projection["Idade"],
                    y=df_projection["Patrimônio Projetado"],
                    name="Patrimônio Projetado",
                    mode="lines",
                    fill="tozeroy",
                    fillcolor="rgba(44, 160, 44, 0.15)",
                    line=dict(color="rgba(44, 160, 44, 0.8)", width=3),
                    hovertemplate="Patrimônio: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Trace 2: Valor Aportado Acumulado (Blue Area with Transparency)
            fig.add_trace(
                go.Scatter(
                    x=df_projection["Idade"],
                    y=df_projection["Valor Aportado Acumulado"],
                    name="Valor Aportado Acumulado",
                    mode="lines",
                    fill="tozeroy",
                    fillcolor="rgba(31, 119, 180, 0.25)",
                    line=dict(color="rgba(31, 119, 180, 0.8)", width=3),
                    hovertemplate="Aportado: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Trace 3: Juros Acumulado (Solid Red Line)
            fig.add_trace(
                go.Scatter(
                    x=df_projection["Idade"],
                    y=df_projection["Juros Acumulado (Rendimento)"],
                    name="Juros Acumulado (Rendimento)",
                    mode="lines",
                    line=dict(color="red", width=4),
                    hovertemplate="Juros: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Trace 4: Meta (Dashed Grey Line)
            fig.add_trace(
                go.Scatter(
                    x=df_projection["Idade"],
                    y=df_projection["Meta"],
                    name="Meta",
                    mode="lines",
                    line=dict(color="grey", width=2, dash="dash"),
                    hovertemplate="Meta: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # CALCULATE CROSSOVER POINT (Juros >= Valor Aportado Acumulado)
            crossover_rows = df_projection[df_projection["Juros Acumulado (Rendimento)"] >= df_projection["Valor Aportado Acumulado"]]
            if not crossover_rows.empty:
                crossover_row = crossover_rows.iloc[0]
                cross_age = float(crossover_row["Idade"])
                cross_val = float(crossover_row["Juros Acumulado (Rendimento)"])

                # Add vertical dashed marker line
                fig.add_vline(x=cross_age, line_width=2, line_dash="dash", line_color="orange")
                # Add elegant annotation box
                fig.add_annotation(
                    x=cross_age,
                    y=cross_val,
                    text=f"Juros >= Aportes<br>aos <b>{cross_age:.1f} anos</b>",
                    showarrow=True,
                    arrowhead=2,
                    ax=80,
                    ay=-50,
                    bgcolor="rgba(255, 255, 255, 0.9)",
                    bordercolor="orange",
                    borderwidth=1,
                    font=dict(size=12, color="#333333")
                )

            fig.update_layout(
                title="Crescimento e Composição Patrimonial até a Aposentadoria",
                hovermode="x unified",
                hoverlabel=dict(namelength=-1),
                xaxis=dict(hoverformat=".1f anos"),
                yaxis_tickformat="R$ ,.2f",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.01)
            )
            st.plotly_chart(fig, width="stretch")

    def _render_monthly_comparison(self, sim, container):
        """Renders the constant out-of-pocket contribution vs growing passive interest monthly comparison chart."""
        df_cashflow = SimulationService.build_monthly_cashflow_dataframe(
            sim["start_age_years"],
            sim["remaining_time_months"],
            sim["total_invested"],
            sim["updated_monthly_contribution"],
            sim["monthly_interest_rate"]
        )

        if df_cashflow.empty:
            return

        with container:
            st.subheader("📊 Aporte Constante vs. Juros Crescente")
            fig2 = go.Figure()

            # Trace 1: Constant Monthly Contribution (Solid Blue)
            fig2.add_trace(
                go.Scatter(
                    x=df_cashflow["Idade"],
                    y=df_cashflow["Aporte Mensal"],
                    name="Aporte Mensal (Constante)",
                    mode="lines",
                    line=dict(color="#1f77b4", width=3),
                    hovertemplate="Aporte: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Trace 2: Growing Monthly Interest (Solid Green)
            fig2.add_trace(
                go.Scatter(
                    x=df_cashflow["Idade"],
                    y=df_cashflow["Juros Mensal"],
                    name="Juros Mensal (Crescente)",
                    mode="lines",
                    line=dict(color="#2ca02c", width=3),
                    hovertemplate="Rendimento: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # CALCULATE FREEDOM CROSSOVER POINT (Juros Mensal >= Aporte Mensal)
            freedom_rows = df_cashflow[df_cashflow["Juros Mensal"] >= df_cashflow["Aporte Mensal"]]
            if not freedom_rows.empty:
                freedom_row = freedom_rows.iloc[0]
                freedom_age = float(freedom_row["Idade"])
                freedom_val = float(freedom_row["Juros Mensal"])

                # Add vertical dashed marker line
                fig2.add_vline(x=freedom_age, line_width=2, line_dash="dash", line_color="green")
                # Add elegant annotation box
                fig2.add_annotation(
                    x=freedom_age,
                    y=freedom_val,
                    text=f"Rendimentos >= Aporte<br>aos <b>{freedom_age:.1f} anos</b>",
                    showarrow=True,
                    arrowhead=2,
                    ax=-90,
                    ay=-50,
                    bgcolor="rgba(255, 255, 255, 0.9)",
                    bordercolor="green",
                    borderwidth=1,
                    font=dict(size=12, color="#333333")
                )

            fig2.update_layout(
                title="Fluxo Mensal: Aporte do Bolso vs. Geração de Renda Passiva",
                hovermode="x unified",
                hoverlabel=dict(namelength=-1),
                xaxis=dict(hoverformat=".1f anos"),
                yaxis_tickformat="R$ ,.2f",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.01)
            )
            st.plotly_chart(fig2, width="stretch")

    def _render_historical_comparisons(self, extrapolation=12):
        """Fetches and prepares the 12-month future extrapolation data, then renders both comparative charts."""
        df_ev = DashboardService.calculate_historical_evolution()
        if df_ev.empty:
            return

        st.markdown("---")
        st.subheader(f"📊 Histórico Real vs. Planejado (Com Projeção de {extrapolation} Meses no Futuro)")
        st.write(f"Compare as curvas planejadas no seu cockpit contra os dados reais colhidos da B3. A linha pontilhada extrapola a tendência do seu ritmo real pelos próximos {extrapolation} meses!")

        # 1. EXPAND TIMELINE BY 12 MONTHS
        df_ev = df_ev.sort_values(by="month_str").reset_index(drop=True)
        start_date_str = df_ev.loc[0, 'month_str'] + "-01"
        start_date = pd.to_datetime(start_date_str).replace(day=1)

        # Projected end date: Today + 1 Year (12 months)
        end_date = datetime.date.today() + datetime.timedelta(days=365)

        # Create continuous index including future months
        date_range_extrap = pd.date_range(start=start_date, end=end_date, freq='MS')
        all_months_extrap = date_range_extrap.strftime('%Y-%m').tolist()
        df_extrap = pd.DataFrame({'month_str': all_months_extrap})

        # Merge real historical data (leaves future months as NaN!)
        df_extrap = df_extrap.merge(
            df_ev[['month_str', 'cumulative_invested', 'cumulative_dividends']],
            on='month_str',
            how='left'
        )

        df_extrap['month_display'] = df_extrap['month_str'].apply(Formatter.format_month_year)

        # 2. GENERATE CONTINUOUS PLANNED CURVES
        planned_invested = []
        planned_dividends = []

        last_equity = 0.0
        last_dividends = 0.0

        config = SimulationService.get_configuration()
        if config:
            annual_interest_rate = float(config['annual_interest_rate'])
            monthly_interest_rate = (1 + annual_interest_rate / 100) ** (1 / 12) - 1
        else:
            monthly_interest_rate = (1 + 6.0 / 100) ** (1 / 12) - 1

        monthly_contribution = SimulationService.get_required_contribution()

        for idx, row in df_extrap.iterrows():
            period_interest = last_equity * monthly_interest_rate
            next_equity = last_equity + monthly_contribution
            next_dividends = last_dividends + period_interest

            planned_invested.append(next_equity)
            planned_dividends.append(next_dividends)

            last_equity = next_equity
            last_dividends = next_dividends

        df_extrap['planned_invested'] = planned_invested
        df_extrap['planned_dividends'] = planned_dividends

        # 3. COMPUTE EXTRAPOLATION TRENDLINES USING CENTRALIZED UTILITY
        # Fits polynomial/moving-average on historical rows, and projects into the future
        df_extrap['trend_dividends'] = TrendlineCalculator.get_poly_trendline(
            df_extrap, 'cumulative_dividends', deg=2, extrapolate_periods=extrapolation
        )
        df_extrap['trend_invested'] = TrendlineCalculator.get_moving_average_trendline(
            df_extrap, 'cumulative_invested', window=6, extrapolate_periods=extrapolation
        )

        # Find today's month string to plot the vertical boundary
        current_month_str = datetime.date.today().strftime("%Y-%m")
        current_month_display = Formatter.format_month_year(current_month_str)

        # 4. RENDER COMPARISON CHARTS SIDE BY SIDE
        comp_col1, comp_col2 = st.columns(2)

        self._render_real_vs_planned_dividends(df_extrap, current_month_display, comp_col1)
        self._render_real_vs_planned_invested(df_extrap, current_month_display, comp_col2)

    def _render_real_vs_planned_dividends(self, df_extrap, current_month_display, container):
        """Renders the Real vs Planned Dividends comparison chart with 12-month future extrapolation."""
        with container:
            fig3 = go.Figure()

            # Real Curve (stops at current month)
            fig3.add_trace(
                go.Scatter(
                    x=df_extrap['month_display'],
                    y=df_extrap['cumulative_dividends'],
                    name="Proventos Reais (B3)",
                    mode="lines+markers",
                    line=dict(color="#2ca02c", width=3),
                    hovertemplate="Real: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Planned Curve (Meta - continues into future)
            fig3.add_trace(
                go.Scatter(
                    x=df_extrap['month_display'],
                    y=df_extrap['planned_dividends'],
                    name="Proventos Planejados (Meta)",
                    mode="lines",
                    line=dict(color="#a02c2c", width=2, dash="dash"), # User's custom red
                    hovertemplate="Meta: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Trend Curve (Extrapolated into future)
            fig3.add_trace(
                go.Scatter(
                    x=df_extrap['month_display'],
                    y=df_extrap['trend_dividends'],
                    name="Tendência Polinomial (Real)",
                    mode="lines",
                    line=dict(color="#1a5c1a", width=2, dash="dot"), # Dark green dotted
                    hovertemplate="Tendência: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Draw vertical transition divider for "Hoje"
            fig3.add_vline(x=current_month_display, line_width=1.5, line_dash="dash", line_color="grey")
            fig3.add_annotation(
                x=current_month_display,
                y=0.1,
                text="Transição (Hoje)",
                showarrow=False,
                textangle=-90,
                yref="paper",
                yanchor="bottom",
                font=dict(size=10, color="grey")
            )

            fig3.update_layout(
                title="Histórico de Proventos: Real vs. Planejado",
                hovermode="x unified",
                hoverlabel=dict(namelength=-1),
                xaxis=dict(type="category", tickangle=-45),
                yaxis_tickformat="R$ ,.2f",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.01)
            )
            st.plotly_chart(fig3, width="stretch")

    def _render_real_vs_planned_invested(self, df_extrap, current_month_display, container):
        """Renders the Real vs Planned Invested Capital comparison chart with 12-month future extrapolation."""
        with container:
            fig4 = go.Figure()

            # Real Curve (stops at current month)
            fig4.add_trace(
                go.Scatter(
                    x=df_extrap['month_display'],
                    y=df_extrap['cumulative_invested'],
                    name="Aportes Reais (B3)",
                    mode="lines+markers",
                    line=dict(color="#1f77b4", width=3),
                    hovertemplate="Real: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Planned Curve (Meta - continues into future)
            fig4.add_trace(
                go.Scatter(
                    x=df_extrap['month_display'],
                    y=df_extrap['planned_invested'],
                    name="Aportes Planejados (Meta)",
                    mode="lines",
                    line=dict(color="#b41f1f", width=2, dash="dash"), # User's custom red
                    hovertemplate="Meta: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Trend Curve (Extrapolated into future)
            fig4.add_trace(
                go.Scatter(
                    x=df_extrap['month_display'],
                    y=df_extrap['trend_invested'],
                    name="Tendência Polinomial (Real)",
                    mode="lines",
                    line=dict(color="#0b4075", width=2, dash="dot"), # Dark blue dotted
                    hovertemplate="Tendência: R$ %{y:,.2f}<extra></extra>"
                )
            )

            # Draw vertical transition divider for "Hoje"
            fig4.add_vline(x=current_month_display, line_width=1.5, line_dash="dash", line_color="grey")
            fig4.add_annotation(
                x=current_month_display,
                y=0.1,
                text="Transição (Hoje)",
                showarrow=False,
                textangle=-90,
                yref="paper",
                yanchor="bottom",
                font=dict(size=10, color="grey")
            )

            fig4.update_layout(
                title="Histórico de Capital Investido: Real vs. Planejado",
                hovermode="x unified",
                hoverlabel=dict(namelength=-1),
                xaxis=dict(type="category", tickangle=-45),
                yaxis_tickformat="R$ ,.2f",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.01)
            )
            st.plotly_chart(fig4, width="stretch")

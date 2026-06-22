import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.graph_objects as go
from services.planning_service import SimulationService
from services.assets_service import AssetService
from core.utils.formatter import Formatter
from core.utils.trendlines import TrendlineCalculator, PolynomialTrendlineStrategy, LinearMomentumTrendlineStrategy
from core.constants import (
    SIM_CURRENT_AGE, SIM_START_AGE_YEARS, SIM_REMAINING_TIME_MONTHS, SIM_REQUIRED_CONTRIBUTION,
    SIM_UPDATED_CONTRIBUTION, SIM_TOTAL_INVESTED, SIM_MONTHLY_INTEREST_RATE, SIM_TARGET_EQUITY,
    ANNUAL_INTEREST_RATE, MONTH_STR, MONTH_DISPLAY, CUMULATIVE_INVESTED, PLANNED_INVESTED,
    CUMULATIVE_DIVIDENDS, PLANNED_DIVIDENDS, MONTHLY_DIVIDEND
)

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
            sim[SIM_START_AGE_YEARS],
            sim[SIM_REMAINING_TIME_MONTHS],
            sim[SIM_TOTAL_INVESTED],
            sim[SIM_UPDATED_CONTRIBUTION],
            sim[SIM_MONTHLY_INTEREST_RATE],
            sim[SIM_TARGET_EQUITY]
        )

        if df_projection.empty:
            return

        with container:
            st.subheader("📈 Projeção Acumulada de Longo Prazo")
            fig = go.Figure()

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

            crossover_rows = df_projection[df_projection["Juros Acumulado (Rendimento)"] >= df_projection["Valor Aportado Acumulado"]]
            if not crossover_rows.empty:
                crossover_row = crossover_rows.iloc[0]
                cross_age = float(crossover_row["Idade"])
                cross_val = float(crossover_row["Juros Acumulado (Rendimento)"])

                fig.add_vline(x=cross_age, line_width=2, line_dash="dash", line_color="orange")
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
            sim[SIM_START_AGE_YEARS],
            sim[SIM_REMAINING_TIME_MONTHS],
            sim[SIM_TOTAL_INVESTED],
            sim[SIM_UPDATED_CONTRIBUTION],
            sim[SIM_MONTHLY_INTEREST_RATE]
        )

        if df_cashflow.empty:
            return

        with container:
            st.subheader("📊 Aporte Constante vs. Juros Crescente")
            fig2 = go.Figure()

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

            freedom_rows = df_cashflow[df_cashflow["Juros Mensal"] >= df_cashflow["Aporte Mensal"]]
            if not freedom_rows.empty:
                freedom_row = freedom_rows.iloc[0]
                freedom_age = float(freedom_row["Idade"])
                freedom_val = float(freedom_row["Juros Mensal"])

                fig2.add_vline(x=freedom_age, line_width=2, line_dash="dash", line_color="green")
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
        df_evolution = AssetService.calculate_historical_evolution()
        if df_evolution.empty:
            return

        st.markdown("---")
        st.subheader(f"📊 Histórico Real vs. Planejado (Com Projeção de {extrapolation} Meses no Futuro)")
        st.write(f"Compare as curvas planejadas no seu cockpit contra os dados reais colhidos da B3. A linha pontilhada extrapola a tendência do seu ritmo real pelos próximos {extrapolation} meses!")

        # 1. EXPAND TIMELINE BY 12 MONTHS
        df_evolution = df_evolution.sort_values(by=MONTH_STR).reset_index(drop=True)
        start_date_str = df_evolution.loc[0, MONTH_STR] + "-01"
        start_date = pd.to_datetime(start_date_str).replace(day=1)

        end_date = datetime.date.today() + datetime.timedelta(days=365)

        date_range_extrap = pd.date_range(start=start_date, end=end_date, freq='MS')
        all_months_extrap = date_range_extrap.strftime('%Y-%m').tolist()
        df_extrap = pd.DataFrame({MONTH_STR: all_months_extrap})

        df_extrap = df_extrap.merge(
            df_evolution[[MONTH_STR, CUMULATIVE_INVESTED, CUMULATIVE_DIVIDENDS]],
            on=MONTH_STR,
            how='left'
        )

        df_extrap[MONTH_DISPLAY] = df_extrap[MONTH_STR].apply(Formatter.format_month_year)

        # 2. GENERATE CONTINUOUS PLANNED CURVES (DRY Compliant)
        config = SimulationService.get_configuration()
        if config:
            annual_interest_rate_val = float(config[ANNUAL_INTEREST_RATE])
            monthly_interest_rate = (1 + annual_interest_rate_val / 100) ** (1 / 12) - 1
        else:
            monthly_interest_rate = (1 + 6.0 / 100) ** (1 / 12) - 1

        monthly_contribution = SimulationService.get_required_contribution()

        # Call our centralized, DRY-compliant mathematical projection service method!
        df_extrap = SimulationService.calculate_planned_historical_evolution(df_extrap, monthly_contribution, monthly_interest_rate)

        # 3. COMPUTE EXTRAPOLATION TRENDLINES USING CENTRALIZED UTILITY STRATEGIES (OCP Compliant!)
        # - Dividends: 2nd degree Polynomial Strategy
        # - Invested: 12-month Linear Momentum Strategy (Highly realistic, goes flat if you stop contributing!)
        df_extrap['trend_dividends'] = TrendlineCalculator.calculate_trend(
            df_extrap, CUMULATIVE_DIVIDENDS, PolynomialTrendlineStrategy(deg=2), extrapolate_periods=extrapolation
        )
        df_extrap['trend_invested'] = TrendlineCalculator.calculate_trend(
            df_extrap, CUMULATIVE_INVESTED, LinearMomentumTrendlineStrategy(window_months=12), extrapolate_periods=extrapolation
        )

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

            fig3.add_trace(
                go.Scatter(
                    x=df_extrap[MONTH_DISPLAY],
                    y=df_extrap[CUMULATIVE_DIVIDENDS],
                    name="Proventos Reais (B3)",
                    mode="lines+markers",
                    line=dict(color="#2ca02c", width=3),
                    hovertemplate="Real: R$ %{y:,.2f}<extra></extra>"
                )
            )

            fig3.add_trace(
                go.Scatter(
                    x=df_extrap[MONTH_DISPLAY],
                    y=df_extrap[PLANNED_DIVIDENDS],
                    name="Proventos Planejados (Meta)",
                    mode="lines",
                    line=dict(color="#a02c2c", width=2, dash="dash"),
                    hovertemplate="Meta: R$ %{y:,.2f}<extra></extra>"
                )
            )

            fig3.add_trace(
                go.Scatter(
                    x=df_extrap[MONTH_DISPLAY],
                    y=df_extrap['trend_dividends'],
                    name="Tendência Polinomial (Real)",
                    mode="lines",
                    line=dict(color="#1a5c1a", width=2, dash="dot"),
                    hovertemplate="Tendência: R$ %{y:,.2f}<extra></extra>"
                )
            )

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

            fig4.add_trace(
                go.Scatter(
                    x=df_extrap[MONTH_DISPLAY],
                    y=df_extrap[CUMULATIVE_INVESTED],
                    name="Aportes Reais (B3)",
                    mode="lines+markers",
                    line=dict(color="#1f77b4", width=3),
                    hovertemplate="Real: R$ %{y:,.2f}<extra></extra>"
                )
            )

            fig4.add_trace(
                go.Scatter(
                    x=df_extrap[MONTH_DISPLAY],
                    y=df_extrap[PLANNED_INVESTED],
                    name="Aportes Planejados (Meta)",
                    mode="lines",
                    line=dict(color="#b41f1f", width=2, dash="dash"),
                    hovertemplate="Meta: R$ %{y:,.2f}<extra></extra>"
                )
            )

            fig4.add_trace(
                go.Scatter(
                    x=df_extrap[MONTH_DISPLAY],
                    y=df_extrap['trend_invested'],
                    name="Tendência (Real)",
                    mode="lines",
                    line=dict(color="#0b4075", width=2, dash="dot"),
                    hovertemplate="Tendência: R$ %{y:,.2f}<extra></extra>"
                )
            )

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

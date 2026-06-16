import streamlit as st
import plotly.express as px
from planning.planning_service import SimulationService

class ProjectionChartWidget:
    """Displays the Plotly compounding projection curves."""

    def render(self, sim):
        df_projection = SimulationService.build_projection_dataframe(
            sim["current_age"], 
            sim["remaining_time_months"], 
            sim["capital_investido"], 
            sim["updated_monthly_contribution"],
            sim["monthly_interest_rate"], 
            sim["target_equity"]
        )

        if not df_projection.empty:
            fig = px.line(
                df_projection,
                x="Idade",
                y=["Patrimônio Projetado", "Valor Aportado Acumulado", "Juros Acumulado (Rendimento)", "Meta"],
                title=f"Projeção de Crescimento e Composição Patrimonial até {sim['retirement_age']} anos",
                labels={"value": "Valores (R$)", "variable": "Linha de Tendência"}
            )
            fig.update_traces(hovertemplate="Idade: %{x:.2f} anos<br>Valor: R$ %{y:,.2f}<extra></extra>")
            fig.update_layout(yaxis_tickformat="R$ ,.2f")
            st.plotly_chart(fig, width="stretch")

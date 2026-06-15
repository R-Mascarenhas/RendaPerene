import streamlit as st
import datetime
import plotly.express as px
from planning.service import SimulationService
from core.utils import Formatter

class PlanningView:
    """Class responsible for rendering the Retirement Simulator Tab GUI."""

    def render(self):
        st.header("Simulador de Independência Financeira")

        # Renders interactive inputs (automatically bound to state and saved on change)
        current_age, months_age = self._render_life_parameters()

        st.markdown("---")
        col5, col6 = st.columns(2)
        with col5:
            st.number_input("Valor Atual do Salário Mínimo (R$)", min_value=1000.0, max_value=5000.0, key="mw_value", step=10.0, on_change=self._save_params)
        with col6:
            st.number_input("Patrimônio Atual Inicial (R$)", min_value=0.0, key="initial_equity_input", step=1000.0, on_change=self._save_params)

        # Unified Service call (Single source of truth)
        sim = SimulationService.get_current_simulation()
        if not sim:
            st.warning("Falha ao carregar as configurações do planejador.")
            return

        # Cache contribution in session state for fallback references if needed
        st.session_state.required_monthly_contribution_cache = sim["required_monthly_contribution"]

        self._render_time_metrics(sim)
        self._render_simulation_results(sim)
        self._render_projection_chart(sim)

    def _save_params(self):
        """Callback to save the current session state parameters to the database."""
        birth_str = st.session_state.birth_date.strftime("%Y-%m-%d") if hasattr(st.session_state.birth_date, 'strftime') else str(st.session_state.birth_date)
        SimulationService.save_configuration(
            birth_str,
            st.session_state.retirement_age,
            st.session_state.desired_income_mw,
            st.session_state.annual_interest_rate,
            st.session_state.mw_value,
            st.session_state.initial_equity_input
        )

    def _render_life_parameters(self):
        st.subheader("Seus Parâmetros de Vida")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            birth_date = st.date_input("Data de Nascimento", key="birth_date", format="DD/MM/YYYY", on_change=self._save_params)
            today = datetime.date.today()
            
            # Calculate exact age in months
            months_age = (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day)
            
            # Age in complete years for user display
            current_age = months_age // 12

        with col2:
            st.number_input("Idade Alvo de Aposentadoria", min_value=current_age+1, max_value=100, key="retirement_age", step=1, on_change=self._save_params)
        with col3:
            st.number_input("Renda Desejada (Salários Mínimos)", min_value=1.0, max_value=100.0, key="desired_income_mw", step=0.5, on_change=self._save_params)
        with col4:
            st.number_input("Taxa de Juros Real (% a.a.)", min_value=1.0, max_value=15.0, key="annual_interest_rate", step=0.5, on_change=self._save_params)

        return current_age, months_age

    def _render_time_metrics(self, sim):
        st.subheader("⏳ Prazos de Investimentos")
        col_t1, col_t2 = st.columns(2)

        total_time_months = sim["total_time_months"]
        total_time_years = total_time_months // 12
        total_time_months_leftover = total_time_months % 12
        
        remaining_time_months = sim["remaining_time_months"]
        remaining_time_years = remaining_time_months // 12
        remaining_months_leftover = remaining_time_months % 12
        
        start_age_years = int(sim["start_age_years"])
        current_age_years = int(sim["current_age"])

        col_t1.metric("Tempo Total de Investimento", f"{total_time_years} Anos e {total_time_months_leftover} meses ({total_time_months} meses)", f"Planejamento iniciado aos {start_age_years} anos")
        col_t2.metric("Tempo Restante de Aporte", f"{remaining_time_years} Anos e {remaining_months_leftover} meses ({remaining_time_months} meses)", f"Sua idade atual hoje: {current_age_years} anos")

    def _render_simulation_results(self, sim):
        st.subheader("🎯 Resultados da Simulação")
        res_col1, res_col2, res_col3, res_col4 = st.columns(4)
        res_col1.metric("Renda Mensal Alvo", Formatter.format_currency(sim["target_monthly_income"]))
        res_col2.metric("Meta de Patrimônio (Viver de Juros)", Formatter.format_currency(sim["target_equity"]))
        res_col3.metric("Aporte Mensal Necessário", Formatter.format_currency(sim["required_monthly_contribution"]))
        res_col4.metric("Aporte Mensal Atualizado", Formatter.format_currency(sim["updated_monthly_contribution"]))

    def _render_projection_chart(self, sim):
        df_projection = SimulationService.build_projection_dataframe(
            sim["current_age"], 
            sim["remaining_time_months"], 
            sim["initial_equity_input"], 
            sim["required_monthly_contribution"], 
            sim["monthly_interest_rate"], 
            sim["target_equity"]
        )

        if not df_projection.empty:
            fig = px.line(
                df_projection,
                x="Idade",
                y=["Patrimônio Projetado", "Valor Aportado Acumulado", "Juros Acumulado (Rendimento)", "Meta"],
                title=f"Projeção de Crescimento e Composição Patrimonial até {st.session_state.retirement_age} anos",
                labels={"value": "Valores (R$)", "variable": "Linha de Tendência"}
            )
            fig.update_traces(hovertemplate="Idade: %{x:.2f} anos<br>Valor: R$ %{y:,.2f}<extra></extra>")
            fig.update_layout(yaxis_tickformat="R$ ,.2f")
            st.plotly_chart(fig, use_container_width=True)

import streamlit as st
import datetime
from planning.planning_service import SimulationService
from planning.components.time_metrics import TimeMetricsWidget
from planning.components.simulation_results import SimulationResultsWidget
from planning.components.projection_chart import ProjectionChartWidget

class PlanningView:
    """Clean orchestrator for the Planning tab GUI layout, delegating to SRP components."""

    def render(self):
        st.header("Simulador de Independência Financeira")

        # 1. Renders interactive inputs (automatically bound to state and saved on change)
        current_age, months_age = self._render_life_parameters()

        # 2. Unified Service call (Single source of truth)
        sim = SimulationService.get_current_simulation()
        if not sim:
            st.warning("Falha ao carregar as configurações do planejador.")
            return

        st.markdown("---")
        col5, col6 = st.columns(2)
        with col5:
            st.number_input("Valor Atual do Salário Mínimo (R$)", min_value=1000.0, max_value=5000.0, key="mw_value", step=10.0, on_change=self._save_params)
        with col6:
            # Dynamically calculated from B3 database transactions
            st.metric(
                "Capital Investido Atual",
                f"R$ {sim['total_invested']:,.2f}",
                help="Calculado de forma automatizada a partir do seu histórico de compras na B3"
            )

        # Cache contribution in session state for fallback references if needed
        st.session_state.required_monthly_contribution_cache = sim["updated_monthly_contribution"]

        # 3. Render Metric Widgets & Compounding Line Chart
        TimeMetricsWidget().render(sim)
        SimulationResultsWidget().render(sim)
        ProjectionChartWidget().render(sim)

    def _save_params(self):
        """Callback to save the current session state parameters to the database."""
        import datetime
        birth_str = st.session_state.birth_date.strftime("%Y-%m-%d") if hasattr(st.session_state.birth_date, 'strftime') else str(st.session_state.birth_date)
        SimulationService.save_configuration(
            birth_str,
            st.session_state.retirement_age,
            st.session_state.desired_income_mw,
            st.session_state.annual_interest_rate,
            st.session_state.mw_value,
            0.0
        )

    def _render_life_parameters(self):
        st.subheader("Seus Parâmetros de Vida")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            birth_date = st.date_input("Data de Nascimento", key="birth_date", format="DD/MM/YYYY", on_change=self._save_params)
            today = datetime.date.today()

            # Calculate exact age in months
            months_age = (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day)
            current_age = months_age // 12

        with col2:
            st.number_input("Idade Alvo de Aposentadoria", min_value=current_age+1, max_value=100, key="retirement_age", step=1, on_change=self._save_params)
        with col3:
            st.number_input("Renda Desejada (Salários Mínimos)", min_value=1.0, max_value=100.0, key="desired_income_mw", step=0.5, on_change=self._save_params)
        with col4:
            st.number_input("Taxa de Juros Real (% a.a.)", min_value=1.0, max_value=15.0, key="annual_interest_rate", step=0.5, on_change=self._save_params)

        return current_age, months_age

import streamlit as st
import datetime
from services.planning_service import SimulationService
from core.utils.formatter import Formatter
from core.utils.market_data import MarketData
from views.components.time_metrics import TimeMetricsWidget
from views.components.simulation_results import SimulationResultsWidget
from views.components.projection_chart import ProjectionChartWidget

class PlanningView:
    """Clean orchestrator for the Planning tab GUI layout, delegating to SRP components."""

    def render(self):
        st.header("🎯 Planejamento de Aposentadoria e Independência Financeira")
        st.write("Calcule as metas de patrimônio necessárias e simule a sua curva de independência financeira utilizando as taxas reais da carteira.")

        # 1. Renders all editable life parameters and minimum wage controls on exactly the same single horizontal row!
        current_age, months_age = self._render_life_parameters()

        # 2. Unified Service call (Single source of truth)
        sim = SimulationService.get_current_simulation()
        if not sim:
            st.warning("Falha ao carregar as configurações do planejador.")
            return

        st.markdown("---")

        # # Display Capital Investido on top of widgets
        # st.metric(
        #     "Capital Investido Atual",
        #     f"R$ {sim['total_invested']:,.2f}",
        #     help="Calculado de forma automatizada a partir do seu histórico de compras na B3"
        # )

        # Cache contribution in session state for fallback references if needed
        st.session_state.required_monthly_contribution_cache = sim["updated_monthly_contribution"]

        # 3. Render Metric Widgets & Compounding Line Chart
        SimulationResultsWidget().render(sim)
        TimeMetricsWidget().render(sim)
        ProjectionChartWidget().render(sim)

    def _on_mw_value_change(self):
        """Syncs the custom widget key-input back to the core session state and saves it."""
        # Retrieve value from dynamic state key
        dynamic_key = f"mw_value_input_{st.session_state.mw_value}"
        if dynamic_key in st.session_state:
            st.session_state.mw_value = float(st.session_state[dynamic_key])
        self._save_params()

    def _on_birth_date_change(self):
        """Syncs birth date input back to core state and saves it."""
        st.session_state.birth_date = st.session_state.birth_date_input
        self._save_params()

    def _on_retirement_age_change(self):
        """Syncs retirement age input back to core state and saves it."""
        st.session_state.retirement_age = int(st.session_state.retirement_age_input)
        self._save_params()

    def _on_annual_interest_rate_change(self):
        """Syncs real interest rate input back to core state and saves it."""
        st.session_state.annual_interest_rate = float(st.session_state.annual_interest_rate_input)
        self._save_params()

    def _on_desired_income_mw_change(self):
        """Syncs multiplier numeric input back to core state and saves it."""
        st.session_state.desired_income_mw_val = st.session_state.desired_income_mw_input
        self._save_params()

    def _on_desired_income_fixed_change(self):
        """Syncs fixed numeric input back to core state and saves it."""
        st.session_state.desired_income_fixed_val = st.session_state.desired_income_fixed_input
        self._save_params()

    def _on_desired_income_type_change(self):
        """Syncs radio selection back to core English database state and saves it."""
        ui_type = st.session_state.desired_income_type_selector
        st.session_state.desired_income_type = "MULTIPLIER" if ui_type == "Multiplicador" else "FIXED"
        self._save_params()

    def _save_params(self):
        """Callback to save the current session state parameters to the database."""
        birth_str = st.session_state.birth_date.strftime("%Y-%m-%d") if hasattr(st.session_state.birth_date, 'strftime') else str(st.session_state.birth_date)

        db_type = st.session_state.desired_income_type
        desired_mw = float(st.session_state.desired_income_mw_val)
        desired_fixed = float(st.session_state.desired_income_fixed_val)

        SimulationService.save_configuration(
            birth_str,
            st.session_state.retirement_age,
            desired_mw,
            st.session_state.annual_interest_rate,
            st.session_state.mw_value,
            0.0,
            desired_income_type=db_type,
            desired_income_fixed=desired_fixed
        )

    def _render_life_parameters(self):
        st.subheader("Seus Parâmetros de Vida")

        # All 6 parameters and buttons placed on exactly the same single horizontal row!
        col_birth, col_ret_age, col_interest, col_type, col_val, col_mw = st.columns([1, 1, 1, 1.2, 1.2, 1.6])

        with col_birth:
            birth_date = st.date_input(
                "Data de Nascimento",
                value=st.session_state.birth_date,
                key="birth_date_input",
                format="DD/MM/YYYY",
                on_change=self._on_birth_date_change
            )
            today = datetime.date.today()

            # Calculate exact age in months
            months_age = (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day)
            current_age = months_age // 12

        with col_ret_age:
            st.number_input(
                "Idade de Aposentadoria",
                min_value=current_age+1,
                max_value=100,
                value=int(st.session_state.retirement_age),
                key="retirement_age_input",
                step=1,
                on_change=self._on_retirement_age_change
            )

        with col_interest:
            st.number_input(
                "Taxa de Juros (% a.a.)",
                min_value=1.0,
                max_value=15.0,
                value=float(st.session_state.annual_interest_rate),
                key="annual_interest_rate_input",
                step=0.5,
                on_change=self._on_annual_interest_rate_change
            )

        with col_type:
            # Map database state to UI text index representation
            default_db_type = st.session_state.get('desired_income_type', 'MULTIPLIER')
            default_index = 0 if default_db_type == 'MULTIPLIER' else 1

            # High-fidelity radio button replacing selectbox for premium UX with Bazin tooltip help!
            st.radio(
                "Tipo de Renda Desejada",
                options=["Multiplicador", "Valor Fixo"],
                index=default_index,
                key="desired_income_type_selector",
                horizontal=True,
                on_change=self._on_desired_income_type_change,
                help=f"Multiplicador: Define a renda com base em salários mínimos. O salário mínimo atual cadastrado é {Formatter.format_currency(st.session_state.mw_value)}."
            )

        with col_val:
            ui_type = st.session_state.get('desired_income_type_selector', "Multiplicador")

            if ui_type == "Multiplicador":
                st.number_input(
                    "Salários Desejados",
                    min_value=1.0,
                    max_value=100.0,
                    value=st.session_state.desired_income_mw_val,
                    key="desired_income_mw_input",
                    step=0.5,
                    on_change=self._on_desired_income_mw_change
                )
            else: # Valor Fixo em Reais
                st.number_input(
                    "Valor Desejado (R$)",
                    min_value=1000.0,
                    max_value=100000.0,
                    value=st.session_state.desired_income_fixed_val,
                    key="desired_income_fixed_input",
                    step=100.0,
                    on_change=self._on_desired_income_fixed_change
                )

        with col_mw:
            # Squeeze the number input and a tiny reload icon button next to it!
            col_mw_val, col_mw_btn = st.columns([3, 1])
            with col_mw_val:
                # Dynamic key is built from the current minimum wage value to force Streamlit to refresh completely on cloud fetch!
                st.number_input(
                    "Salário Mínimo (R$)",
                    min_value=1000.0,
                    max_value=10000.0,
                    value=st.session_state.mw_value,
                    key=f"mw_value_input_{st.session_state.mw_value}",
                    step=10.0,
                    on_change=self._on_mw_value_change
                )
            with col_mw_btn:
                st.write("") # Spacer label alignment
                st.write("")
                if st.button("🔄", help="Atualizar valor do salário mínimo da nuvem (API SGS Banco Central)"):
                    with st.spinner("BCB..."):
                        try:
                            # Clear cache and force live HTTP fetch
                            MarketData.get_current_minimum_wage.clear()
                            live_mw = MarketData.get_current_minimum_wage()
                            if live_mw > 1000.0:
                                st.session_state.mw_value = live_mw
                                self._save_params()
                                st.toast(f"Salário Mínimo atualizado com sucesso direto do BCB: {Formatter.format_currency(live_mw)}!", icon="🎉")
                                st.rerun()
                            else:
                                st.error("Falha ao recuperar dados oficiais do BCB.")
                        except Exception as e:
                            st.error(f"Erro ao conectar com a API do BCB: {e}")

        return current_age, months_age

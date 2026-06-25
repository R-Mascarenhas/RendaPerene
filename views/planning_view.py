import streamlit as st
import datetime
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from services.planning_service import SimulationService
from core.utils.formatter import Formatter
from core.utils.market_data import MarketData
from views.components.time_metrics import TimeMetricsWidget
from views.components.simulation_results import SimulationResultsWidget
from views.components.projection_chart import ProjectionChartWidget
from core.constants import (
    SESSION_BIRTH_DATE, SESSION_RETIREMENT_AGE, SESSION_DESIRED_INCOME_MW, SESSION_ANNUAL_INTEREST_RATE,
    SESSION_MW_VALUE, SESSION_DESIRED_INCOME_TYPE, SESSION_DESIRED_INCOME_FIXED,
    SESSION_REQUIRED_CONTRIBUTION_CACHE,
    WIDGET_BIRTH_DATE, WIDGET_RETIREMENT_AGE, WIDGET_INTEREST_RATE, WIDGET_INCOME_TYPE, WIDGET_INCOME_MW,
    WIDGET_INCOME_FIXED,
    SIM_CURRENT_AGE, SIM_START_AGE_YEARS, SIM_TOTAL_TIME_MONTHS, SIM_REMAINING_TIME_MONTHS,
    SIM_TARGET_MONTHLY_INCOME, SIM_MONTHLY_INTEREST_RATE, SIM_TARGET_EQUITY,
    SIM_REQUIRED_CONTRIBUTION, SIM_UPDATED_CONTRIBUTION, SIM_TOTAL_INVESTED
)
from core.strings import (
    MSG_PLANNING_DESC, MSG_PLANNING_LOAD_ERROR, MSG_PLANNING_INVESTED_CAPITAL,
    MSG_PLANNING_LIFE_PARAMS, MSG_UPDATE_MW_BTN, MSG_BCB_FETCH_ERROR, MSG_BCB_CONN_ERROR,
    HELP_PLANNING_AUTOMATED, HELP_INCOME_MULTIPLIER, HELP_UPDATE_MW
)

class PlanningView:
    """Clean orchestrator for the Planning tab GUI layout, delegating to SRP components."""

    def render(self):
        st.header("🎯 Planejamento de Aposentadoria e Independência Financeira")
        st.write(MSG_PLANNING_DESC)

        # Renders the Sandbox Simulation expander (in-memory play zone)
        self._render_sandbox_simulation()

        # 1. Renders all editable life parameters and minimum wage controls on exactly the same single horizontal row!
        current_age, months_age = self._render_life_parameters()

        # 2. Unified Service call (Single source of truth)
        sim = SimulationService.get_current_simulation()
        if not sim:
            st.warning(MSG_PLANNING_LOAD_ERROR)
            return

        st.markdown("---")

        # Display Capital Investido on top of widgets
        st.metric(
            MSG_PLANNING_INVESTED_CAPITAL,
            f"R$ {sim['total_invested']:,.2f}",
            help=HELP_PLANNING_AUTOMATED
        )

        # Cache contribution in session state for fallback references if needed
        st.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] = sim["updated_monthly_contribution"]

        # 3. Render Metric Widgets & Compounding Line Chart
        TimeMetricsWidget().render(sim)
        SimulationResultsWidget().render(sim)
        ProjectionChartWidget().render(sim)

    def _on_mw_value_change(self):
        """Syncs the custom widget key-input back to the core session state and saves it."""
        # Retrieve value from dynamic state key
        dynamic_key = f"mw_value_input_{st.session_state[SESSION_MW_VALUE]}"
        if dynamic_key in st.session_state:
            st.session_state[SESSION_MW_VALUE] = float(st.session_state[dynamic_key])
        self._save_params()

    def _on_birth_date_change(self):
        """Syncs birth date input back to core state and saves it."""
        st.session_state[SESSION_BIRTH_DATE] = st.session_state[WIDGET_BIRTH_DATE]
        self._save_params()

    def _on_retirement_age_change(self):
        """Syncs retirement age input back to core state and saves it."""
        st.session_state[SESSION_RETIREMENT_AGE] = int(st.session_state[WIDGET_RETIREMENT_AGE])
        self._save_params()

    def _on_annual_interest_rate_change(self):
        """Syncs real interest rate input back to core state and saves it."""
        st.session_state[SESSION_ANNUAL_INTEREST_RATE] = float(st.session_state[WIDGET_INTEREST_RATE])
        self._save_params()

    def _on_desired_income_mw_change(self):
        """Syncs multiplier numeric input back to core state and saves it."""
        st.session_state[SESSION_DESIRED_INCOME_MW] = st.session_state[WIDGET_INCOME_MW]
        self._save_params()

    def _on_desired_income_fixed_change(self):
        """Syncs fixed numeric input back to core state and saves it."""
        st.session_state[SESSION_DESIRED_INCOME_FIXED] = st.session_state[WIDGET_INCOME_FIXED]
        self._save_params()

    def _on_desired_income_type_change(self):
        """Syncs radio selection back to core English database state and saves it."""
        ui_type = st.session_state[WIDGET_INCOME_TYPE]
        st.session_state[SESSION_DESIRED_INCOME_TYPE] = "MULTIPLIER" if ui_type == "Multiplicador" else "FIXED"
        self._save_params()

    def _save_params(self):
        """Callback to save the current session state parameters to the database."""
        core_birth_date = st.session_state[SESSION_BIRTH_DATE]
        birth_str = core_birth_date.strftime("%Y-%m-%d") if hasattr(core_birth_date, 'strftime') else str(core_birth_date)

        db_type = st.session_state[SESSION_DESIRED_INCOME_TYPE]
        desired_mw = float(st.session_state[SESSION_DESIRED_INCOME_MW])
        desired_fixed = float(st.session_state[SESSION_DESIRED_INCOME_FIXED])

        SimulationService.save_configuration(
            birth_str,
            st.session_state[SESSION_RETIREMENT_AGE],
            desired_mw,
            st.session_state[SESSION_ANNUAL_INTEREST_RATE],
            st.session_state[SESSION_MW_VALUE],
            0.0,
            desired_income_type=db_type,
            desired_income_fixed=desired_fixed
        )

    def _render_life_parameters(self):
        st.subheader(MSG_PLANNING_LIFE_PARAMS)

        # All 6 parameters and buttons placed on exactly the same single horizontal row!
        col_birth, col_ret_age, col_interest, col_type, col_val, col_mw = st.columns([1, 1, 1, 1.2, 1.2, 1.6])

        with col_birth:
            birth_date = st.date_input(
                "Data de Nascimento",
                value=st.session_state[SESSION_BIRTH_DATE],
                key=WIDGET_BIRTH_DATE,
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
                value=int(st.session_state[SESSION_RETIREMENT_AGE]),
                key=WIDGET_RETIREMENT_AGE,
                step=1,
                on_change=self._on_retirement_age_change
            )

        with col_interest:
            st.number_input(
                "Taxa de Juros (% a.a.)",
                min_value=1.0,
                max_value=15.0,
                value=float(st.session_state[SESSION_ANNUAL_INTEREST_RATE]),
                key=WIDGET_INTEREST_RATE,
                step=0.5,
                on_change=self._on_annual_interest_rate_change
            )

        with col_type:
            # Map database state to UI text index representation
            default_db_type = st.session_state.get(SESSION_DESIRED_INCOME_TYPE, 'MULTIPLIER')
            default_index = 0 if default_db_type == 'MULTIPLIER' else 1

            # High-fidelity radio button replacing selectbox for premium UX with Bazin tooltip help!
            st.radio(
                "Tipo de Renda Desejada",
                options=["Multiplicador", "Valor Fixo"],
                index=default_index,
                key=WIDGET_INCOME_TYPE,
                horizontal=True,
                on_change=self._on_desired_income_type_change,
                help=HELP_INCOME_MULTIPLIER.format(value=Formatter.format_currency(st.session_state[SESSION_MW_VALUE]))
            )

        with col_val:
            ui_type = st.session_state.get(WIDGET_INCOME_TYPE, "Multiplicador")

            if ui_type == "Multiplicador":
                st.number_input(
                    "Salários Desejados",
                    min_value=1.0,
                    max_value=1000.0,
                    value=st.session_state[SESSION_DESIRED_INCOME_MW],
                    key=WIDGET_INCOME_MW,
                    step=0.5,
                    on_change=self._on_desired_income_mw_change
                )
            else: # Valor Fixo em Reais
                st.number_input(
                    "Valor Desejado (R$)",
                    min_value=1000.0,
                    max_value=100000.0,
                    value=st.session_state[SESSION_DESIRED_INCOME_FIXED],
                    key=WIDGET_INCOME_FIXED,
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
                    max_value=5000.0,
                    value=st.session_state[SESSION_MW_VALUE],
                    key=f"mw_value_input_{st.session_state[SESSION_MW_VALUE]}",
                    step=10.0,
                    on_change=self._on_mw_value_change
                )
            with col_mw_btn:
                st.write("") # Spacer label alignment
                st.write("")
                if st.button(MSG_UPDATE_MW_BTN, help=HELP_UPDATE_MW):
                    with st.spinner("BCB..."):
                        try:
                            # Clear cache and force live HTTP fetch
                            MarketData.get_current_minimum_wage.clear()
                            live_mw = MarketData.get_current_minimum_wage()
                            if live_mw > 1000.0:
                                # CRITICAL: Update BOTH the core state AND the active input widget state
                                # to prevent Streamlit from rolling back our fresh cloud value!
                                st.session_state[SESSION_MW_VALUE] = live_mw
                                self._save_params()
                                st.toast(f"Salário Mínimo atualizado com sucesso direto do BCB: {Formatter.format_currency(live_mw)}!", icon="🎉")
                                st.rerun()
                            else:
                                st.error(MSG_BCB_FETCH_ERROR)
                        except Exception as e:
                            st.error(MSG_BCB_CONN_ERROR.format(e=e))

        return current_age, months_age

    def _render_sandbox_simulation(self):
        """Renders an interactive, isolated sandbox simulation expander for quick scenarios without modifying saved state."""
        st.markdown("---")
        with st.expander("🧮 Simulação Rápida (Espaço de Simulação Independente)", expanded=False):
            st.write("Simule cenários alternativos rapidamente sem alterar seus parâmetros salvos de aposentadoria.")

            # 1. Inputs layout
            col_tempo, col_salario, col_taxa, col_inicial = st.columns(4)

            with col_tempo:
                tempo_anos = st.number_input(
                    "Tempo de Contribuição (Anos)",
                    min_value=1,
                    max_value=80,
                    value=20,
                    step=1,
                    key="sandbox_tempo_anos"
                )
            with col_salario:
                salario_desejado = st.number_input(
                    "Renda Mensal Desejada (R$)",
                    min_value=100.0,
                    max_value=200000.0,
                    value=10000.0,
                    step=500.0,
                    key="sandbox_salario_desejado"
                )
            with col_taxa:
                taxa_juros = st.number_input(
                    "Taxa de Juros (% a.a.)",
                    min_value=1.0,
                    max_value=15.0,
                    value=6.0,
                    step=0.5,
                    key="sandbox_taxa_juros"
                )
            with col_inicial:
                patrimonio_inicial = st.number_input(
                    "Patrimônio Inicial (R$, opcional)",
                    min_value=0.0,
                    max_value=10000000.0,
                    value=0.0,
                    step=1000.0,
                    key="sandbox_patrimonio_inicial"
                )

            # 2. Math calculations using core SimulationService
            n_months = tempo_anos * 12
            monthly_rate = (1 + taxa_juros / 100) ** (1 / 12) - 1
            target_equity = salario_desejado / monthly_rate if monthly_rate > 0 else 0.0

            aporte_necessario = SimulationService.pmt_annuity_due(
                monthly_rate, n_months, patrimonio_inicial, target_equity
            )

            # Build a dynamic simulation dictionary that fully satisfies existing Widget schemas
            sandbox_sim = {
                SIM_CURRENT_AGE: 0.0,
                SIM_START_AGE_YEARS: 0.0,
                SIM_TOTAL_TIME_MONTHS: n_months,
                SIM_REMAINING_TIME_MONTHS: n_months,
                SIM_TARGET_MONTHLY_INCOME: salario_desejado,
                SIM_MONTHLY_INTEREST_RATE: monthly_rate,
                SIM_TARGET_EQUITY: target_equity,
                SIM_REQUIRED_CONTRIBUTION: aporte_necessario,
                SIM_UPDATED_CONTRIBUTION: aporte_necessario,  # Required by ProjectionChartWidget
                SIM_TOTAL_INVESTED: patrimonio_inicial
            }

            # 3. Render Metric Widgets using existing core component (100% DRY!)
            SimulationResultsWidget().render(sandbox_sim, show_updated=False)

            # 4. Render Projection Charts side-by-side using existing core component (100% DRY!)
            st.markdown("---")
            chart_col1, chart_col2 = st.columns(2)
            ProjectionChartWidget()._render_cumulative_projection(sandbox_sim, chart_col1)
            ProjectionChartWidget()._render_monthly_comparison(sandbox_sim, chart_col2)

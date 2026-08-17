import datetime

import streamlit as st

from core.constants import (
    SESSION_ANNUAL_INTEREST_RATE,
    SESSION_BIRTH_DATE,
    SESSION_DESIRED_INCOME_FIXED,
    SESSION_DESIRED_INCOME_MW,
    SESSION_DESIRED_INCOME_TYPE,
    SESSION_INITIAL_EQUITY,
    SESSION_MW_VALUE,
    SESSION_PLANNING_START_DATE,
    SESSION_PLANNING_START_DATE_ENABLED,
    SESSION_REQUIRED_CONTRIBUTION_CACHE,
    SESSION_RETIREMENT_AGE,
    SIM_CURRENT_AGE,
    SIM_MONTHLY_INTEREST_RATE,
    SIM_REMAINING_TIME_MONTHS,
    SIM_REQUIRED_CONTRIBUTION,
    SIM_START_AGE_YEARS,
    SIM_TARGET_EQUITY,
    SIM_TARGET_MONTHLY_INCOME,
    SIM_TOTAL_INVESTED,
    SIM_TOTAL_TIME_MONTHS,
    SIM_UPDATED_CONTRIBUTION,
    WIDGET_BIRTH_DATE,
    WIDGET_INCOME_FIXED,
    WIDGET_INCOME_MW,
    WIDGET_INCOME_TYPE,
    WIDGET_INTEREST_RATE,
    WIDGET_PLANNING_START_DATE,
    WIDGET_PLANNING_START_DATE_ENABLED,
    WIDGET_RETIREMENT_AGE,
)
from core.strings import (
    HELP_INCOME_MULTIPLIER,
    HELP_INITIAL_EQUITY_INPUT_DYNAMIC,
    HELP_PLANNING_AUTOMATED,
    HELP_PLANNING_START_DATE_ENABLED,
    HELP_UPDATE_MW,
    MSG_BCB_CONN_ERROR,
    MSG_BCB_FETCH_ERROR,
    MSG_PLANNING_DESC,
    MSG_PLANNING_INVESTED_CAPITAL,
    MSG_PLANNING_LIFE_PARAMS,
    MSG_PLANNING_LOAD_ERROR,
    MSG_UPDATE_MW_BTN,
)
from core.utils.formatter import Formatter
from services.planning_service import SimulationService
from views.cached_market_data import StreamlitCachedMarketData as MarketData
from views.components.projection_chart import ProjectionChartWidget
from views.components.simulation_results import SimulationResultsWidget
from views.components.time_metrics import TimeMetricsWidget


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
            help=HELP_PLANNING_AUTOMATED,
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
        st.session_state[SESSION_ANNUAL_INTEREST_RATE] = float(
            st.session_state[WIDGET_INTEREST_RATE]
        )
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
        st.session_state[SESSION_DESIRED_INCOME_TYPE] = (
            "MULTIPLIER" if ui_type == "Multiplicador" else "FIXED"
        )
        self._save_params()

    def _on_planning_start_date_enabled_change(self):
        """Syncs custom start date toggle back to core state and saves it."""
        enabled = st.session_state[WIDGET_PLANNING_START_DATE_ENABLED]
        st.session_state[SESSION_PLANNING_START_DATE_ENABLED] = enabled
        if enabled:
            current_initial = float(st.session_state.get(SESSION_INITIAL_EQUITY, 0.0))
            if current_initial == 0.0:
                from services.assets_service import AssetService

                start_date_val = st.session_state.get(SESSION_PLANNING_START_DATE)
                start_date_str = start_date_val.strftime("%Y-%m-%d") if start_date_val else None
                computed_initial = AssetService.calculate_prior_invested_amount(start_date_str)
                st.session_state[SESSION_INITIAL_EQUITY] = computed_initial
        self._save_params()
        st.rerun()

    def _on_planning_start_date_change(self):
        """Syncs custom start date back to core state and saves it."""
        start_date_val = st.session_state[WIDGET_PLANNING_START_DATE]
        st.session_state[SESSION_PLANNING_START_DATE] = start_date_val

        current_initial = float(st.session_state.get(SESSION_INITIAL_EQUITY, 0.0))
        if current_initial == 0.0:
            from services.assets_service import AssetService

            new_start_date_str = start_date_val.strftime("%Y-%m-%d") if start_date_val else None
            computed_initial = AssetService.calculate_prior_invested_amount(new_start_date_str)
            st.session_state[SESSION_INITIAL_EQUITY] = computed_initial
        self._save_params()
        st.rerun()

    def _on_initial_equity_change(self):
        """Syncs the initial equity input back to core state and saves it."""
        dynamic_key = f"initial_equity_widget_{st.session_state[SESSION_INITIAL_EQUITY]}"
        if dynamic_key in st.session_state:
            st.session_state[SESSION_INITIAL_EQUITY] = float(st.session_state[dynamic_key])
        self._save_params()

    def _save_params(self):
        """Callback to save the current session state parameters to the database."""
        core_birth_date = st.session_state[SESSION_BIRTH_DATE]
        birth_str = (
            core_birth_date.strftime("%Y-%m-%d")
            if hasattr(core_birth_date, "strftime")
            else str(core_birth_date)
        )

        db_type = st.session_state[SESSION_DESIRED_INCOME_TYPE]
        desired_mw = float(st.session_state[SESSION_DESIRED_INCOME_MW])
        desired_fixed = float(st.session_state[SESSION_DESIRED_INCOME_FIXED])

        start_date_str = None
        if st.session_state.get(SESSION_PLANNING_START_DATE_ENABLED, False):
            start_date_val = st.session_state.get(SESSION_PLANNING_START_DATE)
            if start_date_val:
                start_date_str = (
                    start_date_val.strftime("%Y-%m-%d")
                    if hasattr(start_date_val, "strftime")
                    else str(start_date_val)
                )

        SimulationService.save_configuration(
            birth_str,
            st.session_state[SESSION_RETIREMENT_AGE],
            desired_mw,
            st.session_state[SESSION_ANNUAL_INTEREST_RATE],
            st.session_state[SESSION_MW_VALUE],
            float(st.session_state.get(SESSION_INITIAL_EQUITY, 0.0)),
            desired_income_type=db_type,
            desired_income_fixed=desired_fixed,
            planning_start_date=start_date_str,
        )

    def _render_life_parameters(self):
        st.subheader(MSG_PLANNING_LIFE_PARAMS)

        # All 6 parameters and buttons placed on exactly the same single horizontal row!
        col_birth, col_ret_age, col_interest, col_type, col_val, col_mw = st.columns(
            [1, 1, 1, 1.2, 1.2, 1.6]
        )

        with col_birth:
            today = datetime.date.today()
            birth_date = st.date_input(
                "Data de Nascimento",
                value=st.session_state[SESSION_BIRTH_DATE],
                min_value=datetime.date(today.year - 100, 1, 1),
                max_value=today,
                key=WIDGET_BIRTH_DATE,
                format="DD/MM/YYYY",
                on_change=self._on_birth_date_change,
            )

            # Calculate exact age in months
            months_age = (
                (today.year - birth_date.year) * 12
                + today.month
                - birth_date.month
                - (today.day < birth_date.day)
            )
            current_age = months_age // 12

        with col_ret_age:
            st.number_input(
                "Idade de Aposentadoria",
                min_value=current_age + 1,
                max_value=100,
                value=int(st.session_state[SESSION_RETIREMENT_AGE]),
                key=WIDGET_RETIREMENT_AGE,
                step=1,
                on_change=self._on_retirement_age_change,
            )

        with col_interest:
            st.number_input(
                "Taxa de Juros (% a.a.)",
                min_value=1.0,
                max_value=15.0,
                value=float(st.session_state[SESSION_ANNUAL_INTEREST_RATE]),
                key=WIDGET_INTEREST_RATE,
                step=0.5,
                on_change=self._on_annual_interest_rate_change,
            )

        with col_type:
            # Map database state to UI text index representation
            default_db_type = st.session_state.get(SESSION_DESIRED_INCOME_TYPE, "MULTIPLIER")
            default_index = 0 if default_db_type == "MULTIPLIER" else 1

            # High-fidelity radio button replacing selectbox for premium UX with Bazin tooltip help!
            st.radio(
                "Tipo de Renda Desejada",
                options=["Multiplicador", "Valor Fixo"],
                index=default_index,
                key=WIDGET_INCOME_TYPE,
                horizontal=True,
                on_change=self._on_desired_income_type_change,
                help=HELP_INCOME_MULTIPLIER.format(
                    value=Formatter.format_currency(st.session_state[SESSION_MW_VALUE])
                ),
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
                    on_change=self._on_desired_income_mw_change,
                )
            else:  # Valor Fixo em Reais
                st.number_input(
                    "Valor Desejado (R$)",
                    min_value=1000.0,
                    max_value=100000.0,
                    value=st.session_state[SESSION_DESIRED_INCOME_FIXED],
                    key=WIDGET_INCOME_FIXED,
                    step=100.0,
                    on_change=self._on_desired_income_fixed_change,
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
                    on_change=self._on_mw_value_change,
                )
            with col_mw_btn:
                st.write("")  # Spacer label alignment
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
                                st.toast(
                                    f"Salário Mínimo atualizado com sucesso direto do BCB: {Formatter.format_currency(live_mw)}!",
                                    icon="🎉",
                                )
                                st.rerun()
                            else:
                                st.error(MSG_BCB_FETCH_ERROR)
                        except Exception as e:
                            st.error(MSG_BCB_CONN_ERROR.format(e=e))

        # Renders the custom start date parameters on a small second row
        st.write("")  # Spacer row
        col_chk, col_date, col_initial, _ = st.columns([2.0, 1.5, 1.5, 1.0])
        with col_chk:
            st.write("")  # Downward spacing
            st.checkbox(
                "Ignorar aportes anteriores a uma data específica",
                value=st.session_state[SESSION_PLANNING_START_DATE_ENABLED],
                key=WIDGET_PLANNING_START_DATE_ENABLED,
                on_change=self._on_planning_start_date_enabled_change,
                help=HELP_PLANNING_START_DATE_ENABLED,
            )
        with col_date:
            if st.session_state.get(SESSION_PLANNING_START_DATE_ENABLED, False):
                st.date_input(
                    "Data de Início do Planejamento",
                    value=st.session_state[SESSION_PLANNING_START_DATE],
                    min_value=datetime.date(1930, 1, 1),
                    max_value=datetime.date.today(),
                    key=WIDGET_PLANNING_START_DATE,
                    format="DD/MM/YYYY",
                    on_change=self._on_planning_start_date_change,
                )
        with col_initial:
            if st.session_state.get(SESSION_PLANNING_START_DATE_ENABLED, False):
                from services.assets_service import AssetService

                start_date_val = st.session_state.get(SESSION_PLANNING_START_DATE)
                start_date_str = start_date_val.strftime("%Y-%m-%d") if start_date_val else None
                computed_initial = AssetService.calculate_prior_invested_amount(start_date_str)
                st.number_input(
                    "Patrimônio Inicial (R$)",
                    min_value=0.0,
                    max_value=10_000_000.0,
                    value=float(st.session_state[SESSION_INITIAL_EQUITY]),
                    key=f"initial_equity_widget_{st.session_state[SESSION_INITIAL_EQUITY]}",
                    step=1000.0,
                    on_change=self._on_initial_equity_change,
                    help=HELP_INITIAL_EQUITY_INPUT_DYNAMIC.format(
                        value=Formatter.format_currency(computed_initial)
                    ),
                )

        return current_age, months_age

    def _render_sandbox_simulation(self):
        """Renders an interactive, isolated sandbox simulation expander for quick scenarios without modifying saved state."""
        with st.expander("🧮 Simulação Rápida (Espaço de Simulação Independente)", expanded=False):
            st.write(
                "Simule cenários alternativos rapidamente sem alterar seus parâmetros salvos de aposentadoria."
            )

            # 1. Inputs layout
            col_tempo, col_salario, col_taxa, col_inicial = st.columns(4)

            with col_tempo:
                tempo_anos = st.number_input(
                    "Tempo de Contribuição (Anos)",
                    min_value=1,
                    max_value=80,
                    value=30,
                    step=1,
                    key="sandbox_tempo_anos",
                )
            with col_salario:
                salario_desejado = st.number_input(
                    "Renda Mensal Desejada (R$)",
                    min_value=1000.0,
                    max_value=200_000.0,
                    value=10000.0,
                    step=500.0,
                    key="sandbox_salario_desejado",
                )
            with col_taxa:
                taxa_juros = st.number_input(
                    "Taxa de Juros (% a.a.)",
                    min_value=1.0,
                    max_value=20.0,
                    value=6.0,
                    step=0.5,
                    key="sandbox_taxa_juros",
                )
            with col_inicial:
                patrimonio_inicial = st.number_input(
                    "Patrimônio Inicial (R$, opcional)",
                    min_value=0.0,
                    max_value=10_000_000.0,
                    value=0.0,
                    step=1000.0,
                    key="sandbox_patrimonio_inicial",
                )

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
                SIM_TOTAL_INVESTED: patrimonio_inicial,
            }

            SimulationResultsWidget().render(sandbox_sim, show_updated=False)

            st.markdown("---")
            chart_col1, chart_col2 = st.columns(2)
            ProjectionChartWidget()._render_cumulative_projection(sandbox_sim, chart_col1)
            ProjectionChartWidget()._render_monthly_comparison(sandbox_sim, chart_col2)

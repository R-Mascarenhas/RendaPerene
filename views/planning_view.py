import datetime
import sqlite3

import streamlit as st

from core.constants import (
    INITIAL_EQUITY_AUTO,
    INITIAL_EQUITY_MANUAL_OVERRIDE,
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
    WIDGET_BIRTH_DATE,
    WIDGET_INCOME_FIXED,
    WIDGET_INCOME_MW,
    WIDGET_INCOME_TYPE,
    WIDGET_INITIAL_EQUITY_DYNAMIC_PREFIX,
    WIDGET_INTEREST_RATE,
    WIDGET_MW_VALUE_PREFIX,
    WIDGET_PLANNING_START_DATE,
    WIDGET_PLANNING_START_DATE_ENABLED,
    WIDGET_RETIREMENT_AGE,
)
from core.performance import instrument_screen, measure_navigation
from core.planning import PlanningConfiguration, PlanningScenario
from core.strings import (
    HELP_INCOME_MULTIPLIER,
    HELP_INITIAL_EQUITY_INPUT_DYNAMIC,
    HELP_PLANNING_AUTOMATED,
    HELP_PLANNING_START_DATE_ENABLED,
    HELP_UPDATE_MW,
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
from views.goals_view import GoalsView


class PlanningView:
    """Clean orchestrator for the Planning tab GUI layout, delegating to SRP components."""

    @instrument_screen("planejamento")
    def render(self):
        st.header("🎯 Planejamento de Aposentadoria e Independência Financeira")
        selected_subtab = st.segmented_control(
            "Navegação Planejamento",
            options=["Aposentadoria", "Metas"],
            default="Aposentadoria",
            label_visibility="collapsed",
        )
        if not selected_subtab:
            selected_subtab = "Aposentadoria"

        if selected_subtab == "Aposentadoria":
            with measure_navigation("planejamento", "retirement"):
                self._render_retirement_planning()
        elif selected_subtab == "Metas":
            with measure_navigation("planejamento", "goals"):
                GoalsView().render()

    def _render_retirement_planning(self):
        """Renders retirement inputs and projections inside the planning tab."""
        self._finish_minimum_wage_refresh()
        st.write(MSG_PLANNING_DESC)

        # Renders the Sandbox Simulation expander (in-memory play zone)
        with measure_navigation("planejamento", "sandbox"):
            self._render_sandbox_simulation()

        # 1. Renders all editable life parameters and minimum wage controls on exactly the same single horizontal row!
        with measure_navigation("planejamento", "life_parameters"):
            self._render_life_parameters()

        # 2. Unified Service call (Single source of truth)
        with measure_navigation("planejamento", "simulation"):
            sim = SimulationService.get_current_simulation()
        if not sim:
            st.warning(MSG_PLANNING_LOAD_ERROR)
            return

        st.markdown("---")

        # Display Capital Investido on top of widgets
        st.metric(
            MSG_PLANNING_INVESTED_CAPITAL,
            Formatter.format_currency(sim["total_invested"]),
            help=HELP_PLANNING_AUTOMATED,
        )

        # Cache contribution in session state for fallback references if needed
        st.session_state[SESSION_REQUIRED_CONTRIBUTION_CACHE] = sim["updated_monthly_contribution"]

        # 3. Render Metric Widgets & Compounding Line Chart
        with measure_navigation("planejamento", "time_metrics"):
            TimeMetricsWidget().render(sim)
        with measure_navigation("planejamento", "simulation_results"):
            SimulationResultsWidget().render(sim)
        with measure_navigation("planejamento", "projection_chart"):
            ProjectionChartWidget().render(sim)

    def _on_mw_value_change(self):
        """Syncs the custom widget key-input back to the core session state and saves it."""
        st.session_state.pop("market_minimum_wage_refresh", None)
        # Retrieve value from dynamic state key
        dynamic_key = f"{WIDGET_MW_VALUE_PREFIX}{st.session_state[SESSION_MW_VALUE]}"
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
        was_enabled = st.session_state.get(SESSION_PLANNING_START_DATE_ENABLED, False)
        st.session_state[SESSION_PLANNING_START_DATE_ENABLED] = enabled
        if (
            enabled
            and not st.session_state.get(INITIAL_EQUITY_MANUAL_OVERRIDE, False)
            and (st.session_state.get(INITIAL_EQUITY_AUTO, False) or not was_enabled)
        ):
            start_date_val = st.session_state.get(SESSION_PLANNING_START_DATE)
            computed_initial = SimulationService.get_prior_invested_capital(start_date_val)
            if computed_initial is not None:
                st.session_state[SESSION_INITIAL_EQUITY] = computed_initial
            st.session_state[INITIAL_EQUITY_AUTO] = True
        self._save_params()
        st.rerun()

    def _on_planning_start_date_change(self):
        """Syncs custom start date back to core state and saves it."""
        start_date_val = st.session_state[WIDGET_PLANNING_START_DATE]
        st.session_state[SESSION_PLANNING_START_DATE] = start_date_val

        if not st.session_state.get(INITIAL_EQUITY_MANUAL_OVERRIDE, False) and st.session_state.get(
            INITIAL_EQUITY_AUTO, False
        ):
            computed_initial = SimulationService.get_prior_invested_capital(start_date_val)
            if computed_initial is not None:
                st.session_state[SESSION_INITIAL_EQUITY] = computed_initial
            st.session_state[INITIAL_EQUITY_AUTO] = True
        self._save_params()
        st.rerun()

    def _on_initial_equity_change(self):
        """Syncs the initial equity input back to core state and saves it."""
        dynamic_key = (
            f"{WIDGET_INITIAL_EQUITY_DYNAMIC_PREFIX}{st.session_state[SESSION_INITIAL_EQUITY]}"
        )
        if dynamic_key in st.session_state:
            st.session_state[SESSION_INITIAL_EQUITY] = float(st.session_state[dynamic_key])
            st.session_state[INITIAL_EQUITY_AUTO] = False
            st.session_state[INITIAL_EQUITY_MANUAL_OVERRIDE] = True
        self._save_params()

    def _sync_automatic_initial_equity(self, computed_initial: float | None) -> None:
        """Keeps the saved and displayed automatic baseline aligned with portfolio costs."""
        if st.session_state.get(INITIAL_EQUITY_MANUAL_OVERRIDE, False) or not st.session_state.get(
            INITIAL_EQUITY_AUTO, False
        ):
            return
        current_initial = float(st.session_state.get(SESSION_INITIAL_EQUITY, 0.0))
        if computed_initial is not None and current_initial != computed_initial:
            st.session_state[SESSION_INITIAL_EQUITY] = computed_initial
            self._save_params()

    def _finish_minimum_wage_refresh(self):
        """Apply a user-requested valid reply in the UI thread before widgets render."""
        pending = st.session_state.get("market_minimum_wage_refresh")
        if pending is None:
            return
        portfolio, revision = pending
        if portfolio != st.session_state.get("active_db", "portfolio.db"):
            st.session_state.pop("market_minimum_wage_refresh", None)
            return
        status = MarketData.status(("minimum_wage",))
        if status.revision == revision or status.updating:
            MarketData.get_current_minimum_wage()
            return
        st.session_state.pop("market_minimum_wage_refresh", None)
        if status.failed or not status.available:
            st.error(MSG_BCB_FETCH_ERROR)
            return
        live_mw = MarketData.get_current_minimum_wage()
        if not 1000 <= live_mw <= 5000:
            st.error(MSG_BCB_FETCH_ERROR)
            return
        previous_mw = st.session_state[SESSION_MW_VALUE]
        st.session_state[SESSION_MW_VALUE] = live_mw
        try:
            self._save_params()
        except (sqlite3.Error, RuntimeError, ValueError):
            st.session_state[SESSION_MW_VALUE] = previous_mw
            st.error("Não foi possível salvar o salário mínimo. Tente novamente.")
            return
        st.toast(
            f"Salário Mínimo atualizado pelo BCB: {Formatter.format_currency(live_mw)}!",
            icon="🎉",
        )

    def _save_params(self):
        """Callback to save the current session state parameters to the database."""
        SimulationService.save_planning_configuration(
            PlanningConfiguration(
                birth_date=st.session_state[SESSION_BIRTH_DATE],
                retirement_age=st.session_state[SESSION_RETIREMENT_AGE],
                desired_income_mw=float(st.session_state[SESSION_DESIRED_INCOME_MW]),
                annual_interest_rate=st.session_state[SESSION_ANNUAL_INTEREST_RATE],
                mw_value=st.session_state[SESSION_MW_VALUE],
                initial_equity_input=float(st.session_state.get(SESSION_INITIAL_EQUITY, 0.0)),
                desired_income_type=st.session_state[SESSION_DESIRED_INCOME_TYPE],
                desired_income_fixed=float(st.session_state[SESSION_DESIRED_INCOME_FIXED]),
                planning_start_date=(
                    st.session_state.get(SESSION_PLANNING_START_DATE)
                    if st.session_state.get(SESSION_PLANNING_START_DATE_ENABLED, False)
                    else None
                ),
                initial_equity_auto=st.session_state.get(INITIAL_EQUITY_AUTO, False),
                initial_equity_manual_override=st.session_state.get(
                    INITIAL_EQUITY_MANUAL_OVERRIDE, False
                ),
            )
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

            months_age = SimulationService.get_age_months(birth_date)
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
                    key=f"{WIDGET_MW_VALUE_PREFIX}{st.session_state[SESSION_MW_VALUE]}",
                    step=10.0,
                    on_change=self._on_mw_value_change,
                )
            with col_mw_btn:
                st.write("")  # Spacer label alignment
                st.write("")
                if st.button(MSG_UPDATE_MW_BTN, help=HELP_UPDATE_MW):
                    MarketData.get_current_minimum_wage.clear()
                    st.session_state["market_minimum_wage_refresh"] = (
                        st.session_state.get("active_db", "portfolio.db"),
                        MarketData.status(("minimum_wage",)).revision,
                    )
                    MarketData.get_current_minimum_wage()
                if "market_minimum_wage_refresh" in st.session_state:
                    st.caption("Consultando o BCB. O valor atual será mantido até a confirmação.")

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
                start_date_val = st.session_state.get(SESSION_PLANNING_START_DATE)
                computed_initial = SimulationService.get_prior_invested_capital(start_date_val)
                self._sync_automatic_initial_equity(computed_initial)
                initial_equity_help = (
                    Formatter.format_currency(computed_initial)
                    if computed_initial is not None
                    else "Indisponível até a regularização dos custos pendentes"
                )
                st.number_input(
                    "Patrimônio Inicial (R$)",
                    min_value=0.0,
                    max_value=10_000_000.0,
                    value=float(st.session_state[SESSION_INITIAL_EQUITY]),
                    key=f"{WIDGET_INITIAL_EQUITY_DYNAMIC_PREFIX}{st.session_state[SESSION_INITIAL_EQUITY]}",
                    step=1000.0,
                    on_change=self._on_initial_equity_change,
                    help=HELP_INITIAL_EQUITY_INPUT_DYNAMIC.format(value=initial_equity_help),
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

            sandbox_sim = SimulationService.simulate_scenario(
                PlanningScenario(
                    duration_years=tempo_anos,
                    target_monthly_income=salario_desejado,
                    annual_interest_rate=taxa_juros,
                    initial_equity_input=patrimonio_inicial,
                )
            )

            SimulationResultsWidget().render(sandbox_sim, show_updated=False)

            ProjectionChartWidget().render_scenario(sandbox_sim)

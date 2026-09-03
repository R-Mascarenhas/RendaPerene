import math

import streamlit as st

from core.constants import (
    TICKER,
    WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX,
    WIDGET_ACCUMULATION_PLAN_WEIGHTS_PREFIX,
)
from core.utils import Formatter
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.components.goal_progress import GoalProgressBar


def _format_quantity(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _format_percentage(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _goal_detail(goal: dict) -> str:
    return (
        f"{goal[TICKER]} — 01/01: {_format_quantity(goal['start_quantity'])} | "
        f"atual: {_format_quantity(goal['current_quantity'])} | "
        f"meta: {_format_quantity(goal['target_quantity'])} cotas | "
        f"{_format_percentage(goal['progress_percentage'])}% concluído"
    )


class AccumulationGoalProgressWidget:
    """Displays accumulation goal progress on the portfolio dashboard."""

    def render(self) -> None:
        if not ShareQuantityGoalService.get_goal_enabled():
            return

        goals = ShareQuantityGoalService.list_goals_with_progress()
        if not goals:
            return

        st.subheader("🎯 Metas de acumulação por ativo")
        overall_progress = ShareQuantityGoalService.calculate_weighted_progress(goals)
        goal_details = [_goal_detail(goal) for goal in goals]
        st.write(f"**Progresso geral — {_format_percentage(overall_progress)}% concluído**")
        GoalProgressBar.render(overall_progress, tooltip="\n".join(goal_details))
        st.caption("Passe o mouse sobre a barra ou abra os detalhes por ativo.")
        with st.expander("Detalhes por ativo"):
            for detail in goal_details:
                st.write(detail)


class AccumulationGoalPlanningWidget:
    """Displays and edits the annual accumulation plan for the whole portfolio."""

    def render(self) -> None:
        st.markdown("---")
        st.subheader("🎯 Metas de acumulação por ativo")
        st.write(
            "Distribua os proventos planejados entre as empresas da carteira. "
            "Os pesos precisam totalizar 100%."
        )

        active_database = st.session_state.get("active_db", "portfolio.db")
        weights_key = f"{WIDGET_ACCUMULATION_PLAN_WEIGHTS_PREFIX}{active_database}"
        editor_key = f"{WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX}{active_database}"
        selected_weights = st.session_state.get(weights_key)

        try:
            with st.spinner("Calculando metas com os proventos dos últimos 5 anos..."):
                plan = ShareQuantityGoalService.get_portfolio_goal_plan(selected_weights)
        except (RuntimeError, ValueError) as error:
            st.warning(str(error))
            return

        st.metric(
            "Proventos planejados no ano",
            Formatter.format_currency(plan["planned_annual_dividends"]),
        )
        if plan["rows"].empty:
            st.info("Adicione ativos à carteira para criar metas de acumulação.")
            return

        display_rows = plan["rows"].copy()
        for column in (
            ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND,
            ShareQuantityGoalService.PLAN_ALLOCATED_DIVIDENDS,
        ):
            display_rows[column] = display_rows[column].map(Formatter.format_currency)

        edited_rows = st.data_editor(
            display_rows,
            column_order=[
                ShareQuantityGoalService.PLAN_TICKER,
                ShareQuantityGoalService.PLAN_WEIGHT,
                ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND,
                ShareQuantityGoalService.PLAN_ALLOCATED_DIVIDENDS,
                ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY,
                ShareQuantityGoalService.PLAN_CURRENT_QUANTITY,
                ShareQuantityGoalService.PLAN_TARGET_QUANTITY,
                ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE,
                ShareQuantityGoalService.PLAN_HISTORY_NOTE,
            ],
            column_config={
                ShareQuantityGoalService.PLAN_TICKER: st.column_config.TextColumn("Ticker"),
                ShareQuantityGoalService.PLAN_WEIGHT: st.column_config.NumberColumn(
                    "Peso (%)",
                    min_value=0.0,
                    max_value=100.0,
                    step=0.5,
                    format="%.2f",
                    help="Use 0% para não aumentar a posição neste ativo.",
                ),
                ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND: st.column_config.TextColumn(
                    "Média anual de proventos"
                ),
                ShareQuantityGoalService.PLAN_ALLOCATED_DIVIDENDS: st.column_config.TextColumn(
                    "Meta de proventos do ativo"
                ),
                ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY: st.column_config.NumberColumn(
                    "Quantidade em 01/01", format="%.0f"
                ),
                ShareQuantityGoalService.PLAN_CURRENT_QUANTITY: st.column_config.NumberColumn(
                    "Quantidade atual", format="%.0f"
                ),
                ShareQuantityGoalService.PLAN_TARGET_QUANTITY: st.column_config.NumberColumn(
                    "Meta de cotas", format="%.0f"
                ),
                ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE: st.column_config.NumberColumn(
                    "Crescimento da posição (%)", format="%.2f%%"
                ),
                ShareQuantityGoalService.PLAN_HISTORY_NOTE: st.column_config.TextColumn(
                    "Observação",
                    width="large",
                ),
            },
            disabled=[
                ShareQuantityGoalService.PLAN_TICKER,
                ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND,
                ShareQuantityGoalService.PLAN_ALLOCATED_DIVIDENDS,
                ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY,
                ShareQuantityGoalService.PLAN_CURRENT_QUANTITY,
                ShareQuantityGoalService.PLAN_TARGET_QUANTITY,
                ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE,
                ShareQuantityGoalService.PLAN_HISTORY_NOTE,
            ],
            hide_index=True,
            width="stretch",
            key=editor_key,
        )
        edited_weights = ShareQuantityGoalService.allocation_weights_from_dataframe(edited_rows)
        edited_active_tickers = {
            ticker
            for ticker in edited_weights
            if math.isfinite(edited_weights.get(ticker, math.nan)) and edited_weights[ticker] > 0
        }
        weights_are_finite = all(math.isfinite(weight) for weight in edited_weights.values())
        if edited_weights != plan["allocation_weights"] and weights_are_finite:
            st.session_state[weights_key] = edited_weights
            st.rerun()

        weights_are_numeric = all(
            math.isfinite(weight) and weight >= 0 for weight in edited_weights.values()
        )
        total_weight = (
            sum(edited_weights[ticker] for ticker in edited_active_tickers)
            if weights_are_numeric
            else 0.0
        )
        no_active_goals = not edited_active_tickers
        weights_are_valid = weights_are_numeric and (
            no_active_goals or abs(total_weight - 100) <= 0.01
        )
        if no_active_goals and weights_are_valid:
            st.info("Nenhuma meta de acumulação está ativa.")
        elif not weights_are_numeric:
            st.error("Preencha os pesos com valores entre zero e 100%.")
        elif plan.get("has_unavailable_market_data"):
            st.warning(
                "Dados de mercado indisponíveis; salve as metas quando a consulta for restaurada."
            )
        elif weights_are_valid:
            st.success(f"Soma dos pesos: {total_weight:.2f}%")
        else:
            st.error(f"A soma dos pesos deve ser 100%. Soma atual: {total_weight:.2f}%.")

        if st.button(
            "Salvar metas anuais",
            type="primary",
            disabled=not weights_are_valid or plan.get("has_unavailable_market_data", False),
            key=f"save_accumulation_plan_{active_database}",
        ):
            try:
                ShareQuantityGoalService.save_portfolio_goal_plan(edited_weights)
            except ValueError as error:
                st.error(str(error))
            else:
                st.toast("Metas anuais salvas com sucesso!", icon="🎯")
                st.rerun()

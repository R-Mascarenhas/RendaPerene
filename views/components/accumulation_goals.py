import math

import streamlit as st

from core.constants import (
    TICKER,
    WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX,
    WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX,
)
from core.utils import Formatter
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.components.goal_editor_state import GoalEditorState, invalidate_asset_goal_state
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
        if any(goal.get("equal_progress_weights") for goal in goals):
            st.caption(
                "Cotações incompletas: o progresso geral usa pesos iguais entre as metas de compra. "
                "Passe o mouse sobre a barra ou abra os detalhes por ativo."
            )
        elif not any(goal.get("allocation_weight", 0) > 0 for goal in goals):
            st.caption(
                "Sem esforço de compra anual: o progresso geral usa a média dos percentuais por ativo. "
                "Passe o mouse sobre a barra ou abra os detalhes por ativo."
            )
        else:
            st.caption(
                "Progresso ponderado pelo esforço anual desde 01/01. "
                "Passe o mouse sobre a barra ou abra os detalhes por ativo."
            )
        with st.expander("Detalhes por ativo"):
            for detail in goal_details:
                st.write(detail)


class AccumulationGoalPlanningWidget:
    """Displays and edits the annual accumulation plan for the whole portfolio."""

    @staticmethod
    def _on_editor_change(original_plan, editor_key, plan_key):
        """Validate and save a cell edit using the snapshot shown to the user."""
        original_rows = original_plan["rows"]
        updated_plan = original_plan
        with GoalEditorState(plan_key).editing():
            targets = ShareQuantityGoalService.targets_from_editor_changes(
                original_rows, st.session_state.get(editor_key, {})
            )
            updated_plan = ShareQuantityGoalService.save_edited_goal_plan(original_plan, targets)
            invalidate_asset_goal_state()
        st.session_state[plan_key] = updated_plan
        st.session_state[f"{plan_key}pending"] = True

    def render(self) -> None:
        """Refresh the snapshot on page runs and isolate subsequent editor reruns."""
        active_database = st.session_state.get("active_db", "portfolio.db")
        plan_key = f"{WIDGET_ACCUMULATION_PLAN_DRAFT_PREFIX}{active_database}snapshot"
        if not st.session_state.get(f"{plan_key}pending"):
            try:
                st.session_state[plan_key] = ShareQuantityGoalService.get_portfolio_goal_plan()
            except (RuntimeError, ValueError) as error:
                st.warning(str(error))
                return
        self._render_editor(plan_key, active_database)

    @st.fragment
    def _render_editor(self, plan_key: str, active_database: str) -> None:
        st.session_state.pop(f"{plan_key}pending", None)
        plan = st.session_state[plan_key]
        st.subheader("🎯 Metas de acumulação por ativo")
        st.write(
            "Defina a meta anual por cotas ou pela variação da posição em relação a 01/01. Use 0% para manter a posição, valores negativos para reduzir e −100% para zerar."
        )
        st.caption("Alterações válidas são salvas automaticamente ao confirmar a célula.")
        editor_state = GoalEditorState(plan_key)
        editor_key = (
            f"{WIDGET_ACCUMULATION_PLAN_EDITOR_PREFIX}{active_database}_{editor_state.revision}"
        )
        if plan["rows"].empty:
            st.info("Adicione ativos à carteira para criar metas de acumulação.")
            return

        display_rows = plan["rows"].copy()
        for column in (
            ShareQuantityGoalService.PLAN_CURRENT_PRICE,
            ShareQuantityGoalService.PLAN_AVERAGE_DIVIDEND,
            ShareQuantityGoalService.PLAN_ESTIMATED_COST,
            ShareQuantityGoalService.PLAN_REMAINING_COST,
            ShareQuantityGoalService.PLAN_PROJECTED_DIVIDENDS,
        ):
            display_rows[column] = display_rows[column].map(
                lambda value: Formatter.format_currency(value) if math.isfinite(value) else "N/D"
            )
        display_rows[ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE] = display_rows[
            ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE
        ].map(lambda value: f"{value:.2f}".replace(".", ",") if math.isfinite(value) else "N/D")
        st.data_editor(
            display_rows,
            column_order=[
                ShareQuantityGoalService.PLAN_TICKER,
                ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY,
                ShareQuantityGoalService.PLAN_CURRENT_QUANTITY,
                ShareQuantityGoalService.PLAN_TARGET_QUANTITY,
                ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE,
                ShareQuantityGoalService.PLAN_CURRENT_PRICE,
                ShareQuantityGoalService.PLAN_ESTIMATED_COST,
                ShareQuantityGoalService.PLAN_REMAINING_COST,
                ShareQuantityGoalService.PLAN_WEIGHT,
                ShareQuantityGoalService.PLAN_PROJECTED_DIVIDENDS,
                ShareQuantityGoalService.PLAN_HISTORY_NOTE,
            ],
            column_config={
                ShareQuantityGoalService.PLAN_TICKER: st.column_config.TextColumn("Ticker"),
                ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY: st.column_config.NumberColumn(
                    "Quantidade em 01/01", format="%.0f"
                ),
                ShareQuantityGoalService.PLAN_CURRENT_QUANTITY: st.column_config.NumberColumn(
                    "Quantidade atual", format="%.0f"
                ),
                ShareQuantityGoalService.PLAN_TARGET_QUANTITY: st.column_config.NumberColumn(
                    "Meta de cotas", min_value=0, step=1, format="%.0f"
                ),
                ShareQuantityGoalService.PLAN_GROWTH_PERCENTAGE: st.column_config.TextColumn(
                    "Crescimento anual da posição (%)",
                    help="Digite o percentual, por exemplo 10,5. Zero mantém a posição; valores entre −100% e 0% permitem reduzir ou zerar. N/D sem posição em 01/01.",
                ),
                ShareQuantityGoalService.PLAN_CURRENT_PRICE: st.column_config.TextColumn(
                    "Cotação atual",
                    help="Cotação carregada ao abrir ou recarregar a tela e usada nas estimativas durante a edição.",
                ),
                ShareQuantityGoalService.PLAN_ESTIMATED_COST: st.column_config.TextColumn(
                    "Esforço anual estimado",
                    help="Cotas adicionais à posição de 01/01, avaliadas pela cotação atual.",
                ),
                ShareQuantityGoalService.PLAN_REMAINING_COST: st.column_config.TextColumn(
                    "Valor restante para investir",
                    help="Cotas que ainda faltam para a meta, avaliadas pela cotação atual.",
                ),
                ShareQuantityGoalService.PLAN_WEIGHT: st.column_config.NumberColumn(
                    "Participação no esforço (%)",
                    format="%.2f%%",
                    help="Participação no esforço anual desde 01/01; não limita a meta.",
                ),
                ShareQuantityGoalService.PLAN_PROJECTED_DIVIDENDS: st.column_config.TextColumn(
                    "Proventos anuais projetados",
                    help="Meta de cotas × média anual de proventos por cota, considerando a posição-alvo durante um ano.",
                ),
                ShareQuantityGoalService.PLAN_HISTORY_NOTE: st.column_config.TextColumn(
                    "Observação", width="large"
                ),
            },
            disabled=[
                ShareQuantityGoalService.PLAN_TICKER,
                ShareQuantityGoalService.PLAN_YEAR_START_QUANTITY,
                ShareQuantityGoalService.PLAN_CURRENT_QUANTITY,
                ShareQuantityGoalService.PLAN_CURRENT_PRICE,
                ShareQuantityGoalService.PLAN_ESTIMATED_COST,
                ShareQuantityGoalService.PLAN_REMAINING_COST,
                ShareQuantityGoalService.PLAN_WEIGHT,
                ShareQuantityGoalService.PLAN_PROJECTED_DIVIDENDS,
                ShareQuantityGoalService.PLAN_HISTORY_NOTE,
            ],
            hide_index=True,
            width="stretch",
            key=editor_key,
            on_change=self._on_editor_change,
            args=(plan, editor_key, plan_key),
        )
        editor_error = editor_state.error
        if editor_error:
            st.error(editor_error)

        def money(value):
            return Formatter.format_currency(value) if value is not None else "N/D"

        annual, remaining, dividends, external = st.columns(4)
        annual.metric(
            "Esforço anual total estimado",
            money(plan["total_estimated_cost"]),
            help=(
                "Soma das cotas adicionais à posição de 01/01 multiplicadas pela cotação atual. "
                "Metas de manutenção ou redução têm esforço de compra anual igual a zero."
            ),
        )
        remaining.metric(
            "Valor restante para investir",
            money(plan["total_remaining_cost"]),
            help="Soma das cotas que faltam para cada meta, pela cotação atual. Diminui com as compras realizadas.",
        )
        dividends.metric(
            "Proventos anuais projetados",
            money(plan["projected_annual_dividends"]),
            help=(
                "Soma da meta de cotas de cada ativo multiplicada pela média anual de proventos por cota. "
                "Considera a posição-alvo mantida durante um ano. Sem histórico utilizável, aparece N/D."
            ),
        )
        external.metric(
            "Aporte externo anual estimado",
            money(plan["estimated_external_contribution"]),
            help=(
                "Esforço anual total estimado menos os proventos anuais projetados exibidos nesta tela, "
                "com mínimo de zero. Pressupõe reinvestir os proventos da posição-alvo; vendas planejadas "
                "não entram como recursos. Sem alguma estimativa necessária, aparece N/D. "
                "O aporte anual previsto no planejamento de aposentadoria é "
                f"{money(plan['planned_external_contribution'])} (aporte mensal corrigido × 12), "
                "usado para comparar a necessidade destas metas com o planejamento."
            ),
        )
        if plan["exceeds_planned_resources"]:
            st.warning(
                "O aporte externo estimado para estas metas supera o aporte anual previsto no planejamento de aposentadoria. As metas foram mantidas."
            )
        if plan["total_estimated_cost"] is None or plan["total_remaining_cost"] is None:
            st.info(
                "Algumas cotações estão indisponíveis; as estimativas que dependem delas aparecem como N/D."
            )
        st.markdown("---")

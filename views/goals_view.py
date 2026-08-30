import streamlit as st

from core.constants import WIDGET_REINVESTMENT_GOAL_PREFIX, WIDGET_SHARE_QUANTITY_GOAL_PREFIX
from services.goals_service import GoalService
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.components.accumulation_goals import AccumulationGoalPlanningWidget


class GoalsView:
    """Renders goal selection and configuration inside Planning."""

    def render(self) -> None:
        st.subheader("🎯 Metas de investimento")
        st.write("Escolha quais metas deseja acompanhar nesta carteira.")

        active_database = st.session_state.get("active_db", "portfolio.db")
        reinvestment_enabled = self._render_reinvestment_option(active_database)
        share_quantity_enabled = self._render_share_quantity_option(active_database)

        if reinvestment_enabled:
            st.caption(
                "A meta anual do Dashboard inclui os proventos recebidos como valor a reinvestir."
            )
        if share_quantity_enabled:
            AccumulationGoalPlanningWidget().render()

    @staticmethod
    def _render_reinvestment_option(active_database: str) -> bool:
        stored_enabled = GoalService.get_reinvestment_goal_enabled()
        enabled = st.checkbox(
            "Reinvestir dividendos",
            value=stored_enabled,
            help="Inclui os proventos recebidos na meta anual exibida no Dashboard.",
            key=f"{WIDGET_REINVESTMENT_GOAL_PREFIX}{active_database}",
        )
        if enabled != stored_enabled:
            GoalService.set_reinvestment_goal_enabled(enabled)
        return enabled

    @staticmethod
    def _render_share_quantity_option(active_database: str) -> bool:
        stored_enabled = ShareQuantityGoalService.get_goal_enabled()
        enabled = st.checkbox(
            "Meta por quantidade de ações",
            value=stored_enabled,
            help="Distribui os proventos planejados e calcula uma meta de cotas por ativo.",
            key=f"{WIDGET_SHARE_QUANTITY_GOAL_PREFIX}{active_database}",
        )
        if enabled != stored_enabled:
            ShareQuantityGoalService.set_goal_enabled(enabled)
        return enabled

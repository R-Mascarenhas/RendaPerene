import math
import sqlite3

import streamlit as st

from core.constants import WIDGET_ASSET_ANNUAL_GOAL_PREFIX
from core.utils.formatter import Formatter
from services.share_quantity_goal_service import ShareQuantityGoalService
from views.components.goal_editor_state import invalidate_goal_editor_state


class AssetAnnualGoalWidget:
    """Edit one ticker's target through the shared annual portfolio plan."""

    @staticmethod
    def _on_change(plan, ticker, target_mode, context, input_key) -> None:
        """Save a confirmed edit and rebuild both controls from persisted targets."""
        error_key = f"{context}_error"
        try:
            ShareQuantityGoalService.save_asset_goal(
                plan, ticker, target_mode, st.session_state[input_key]
            )
        except ValueError as error:
            st.session_state[error_key] = str(error)
        except (RuntimeError, sqlite3.Error):
            st.session_state[error_key] = "Não foi possível salvar a meta. Tente novamente."
        else:
            st.session_state.pop(error_key, None)
            invalidate_goal_editor_state()
        revision_key = f"{context}_revision"
        st.session_state[revision_key] = st.session_state.get(revision_key, 0) + 1

    def render(self, ticker: str) -> None:
        st.subheader("Meta anual deste ativo")
        service = ShareQuantityGoalService
        try:
            plan = service.get_portfolio_goal_plan(ticker=ticker)
        except (ValueError, RuntimeError, sqlite3.Error):
            st.error("Não foi possível carregar a meta. Tente novamente.")
            return
        rows = plan["rows"]
        if rows.empty:
            return
        selected = rows.loc[rows[service.PLAN_TICKER] == ticker]
        if selected.empty:
            return
        row = selected.iloc[0]
        baseline = float(row[service.PLAN_YEAR_START_QUANTITY])
        target = float(row[service.PLAN_TARGET_QUANTITY])
        current = float(row[service.PLAN_CURRENT_QUANTITY])
        st.caption(f"Ativo: {ticker} · Base em 01/01: {baseline:g} cotas")
        database = st.session_state.get("active_db", "portfolio.db")
        context = f"{WIDGET_ASSET_ANNUAL_GOAL_PREFIX}{database}_{ticker}"
        revision = st.session_state.get(f"{context}_revision", 0)
        widget_context = f"{context}_{baseline}_{target}_{revision}"
        quantity_key = f"{widget_context}_quantity"
        percentage_key = f"{widget_context}_percentage"
        quantity_column, percentage_column = st.columns(2)
        with quantity_column:
            st.number_input(
                "Quantidade-alvo de cotas",
                min_value=0,
                value=int(target),
                step=1,
                key=quantity_key,
                on_change=self._on_change,
                args=(plan, ticker, service.MODE_QUANTITY, context, quantity_key),
            )
        with percentage_column:
            st.number_input(
                "Crescimento sobre a posição de 01/01 (%)",
                min_value=-100.0,
                value=float(row[service.PLAN_GROWTH_PERCENTAGE]) if baseline > 0 else 0.0,
                step=1.0,
                disabled=baseline <= 0,
                help="O percentual é calculado sobre a posição de 01/01; sem essa base, use cotas.",
                key=percentage_key,
                on_change=self._on_change,
                args=(plan, ticker, service.MODE_PERCENTAGE, context, percentage_key),
            )
        st.caption("Alterações são salvas automaticamente ao confirmar com Enter ou sair do campo.")
        if baseline > 0:
            st.caption("0% mantém a posição; percentuais negativos reduzem e −100% zera a meta.")
        else:
            st.info(
                "Crescimento percentual indisponível: não há posição em 01/01. Defina a meta por cotas."
            )
        if error := st.session_state.get(f"{context}_error"):
            st.error(error)
        if service.get_goal_enabled():
            goals = service.list_goals_with_progress(ticker=ticker)
            goal = next((item for item in goals if item["ticker"] == ticker), None)
            if goal is not None:
                progress = float(goal["progress_percentage"])
                st.metric("Progresso anual", f"{progress:.1f}%".replace(".", ","))
                st.progress(max(0.0, min(1.0, progress / 100)))
            remaining = float(row[service.PLAN_REMAINING_COST])
            st.metric(
                "Valor estimado para concluir",
                Formatter.format_currency(remaining) if math.isfinite(remaining) else "N/D",
            )
            st.caption(f"Posição atual: {current:g} · Meta: {target:g} cotas")
        if row[service.PLAN_HISTORY_NOTE]:
            st.caption(str(row[service.PLAN_HISTORY_NOTE]))

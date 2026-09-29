import datetime
import logging

import pandas as pd
import streamlit as st

from core.constants import (
    SESSION_ACTIVE_DATABASE_GENERATION,
    SESSION_ASSETS_NAVIGATION_TARGET,
    WIDGET_MAIN_NAVIGATION,
)
from core.performance import measure_navigation
from core.strings import TAB_ASSETS, TAB_IMPORT_LAUNCH
from core.utils.formatter import Formatter
from services.assets_service import AssetService
from views.components.chart_theme import ChartThemeAdapter

logger = logging.getLogger(__name__)


def style_activity_row(row: pd.Series) -> list[str]:
    """Apply shared theme colors to every cell in an activity row."""
    color, font_color = ChartThemeAdapter.activity_row_colors(row["Evento"])
    return [f"background-color: {color}; color: {font_color}"] * len(row)


def open_operations_history():
    """Request the operations route before Streamlit recreates its navigation widgets."""
    st.session_state[WIDGET_MAIN_NAVIGATION] = TAB_ASSETS
    st.session_state[SESSION_ASSETS_NAVIGATION_TARGET] = TAB_IMPORT_LAUNCH


class PortfolioActivityWidget:
    """Render recent events and a database-paginated history with shared formatting."""

    def render(self, limit: int | None = 10):
        if limit is None:
            self._render_history()
            return
        st.subheader("Últimas movimentações")
        st.button(
            "Ver histórico completo em Ativos → Operações",
            key="open_operations_history",
            on_click=open_operations_history,
        )
        try:
            activity = AssetService.get_portfolio_activity(limit=limit)
        except Exception:
            logger.warning("portfolio.activity_read_failed")
            st.error("Não foi possível carregar as movimentações. Tente novamente.")
            return
        if activity.empty:
            st.info("Nenhuma movimentação registrada nesta carteira.")
            return
        self._render_table(activity)

    @st.fragment
    def render_history(self):
        """Rerun only the history when the user changes filters or pages."""
        with measure_navigation("ativos.operacoes", "activity_history"):
            self._render_history()

    @staticmethod
    def _change_page(delta):
        key = "activity_history_page"
        st.session_state[key] = max(1, st.session_state.get(key, 1) + delta)

    def _render_history(self):
        st.subheader("Histórico de movimentações")
        prefix = "activity_history_"
        portfolio = (
            st.session_state.get("active_db", "portfolio.db"),
            st.session_state.get(SESSION_ACTIVE_DATABASE_GENERATION),
        )
        if st.session_state.get(prefix + "portfolio") != portfolio:
            for suffix in ("start", "end", "event", "ticker", "filters", "page"):
                st.session_state.pop(prefix + suffix, None)
            st.session_state[prefix + "portfolio"] = portfolio
        try:
            options = AssetService.get_activity_filter_options()
        except Exception:
            logger.warning("portfolio.activity_read_failed")
            st.error("Não foi possível carregar as movimentações. Tente novamente.")
            return
        # A full rerun may follow deletion or restoration of the active portfolio.
        for suffix, available in (("event", options["events"]), ("ticker", options["tickers"])):
            if st.session_state.get(prefix + suffix) not in (None, *available):
                st.session_state[prefix + suffix] = None
        columns = st.columns(4)
        with columns[0]:
            start = st.date_input(
                "Data inicial",
                value=None,
                format="DD/MM/YYYY",
                key=prefix + "start",
                min_value=datetime.date(1000, 1, 1),
                max_value=datetime.date.max,
            )
        with columns[1]:
            end = st.date_input(
                "Data final",
                value=None,
                format="DD/MM/YYYY",
                key=prefix + "end",
                min_value=datetime.date(1000, 1, 1),
                max_value=datetime.date.max,
            )
        with columns[2]:
            event = st.selectbox(
                "Evento",
                [None, *options["events"]],
                key=prefix + "event",
                format_func=lambda value: value or "Todos os eventos",
            )
        with columns[3]:
            ticker = st.selectbox(
                "Ticker",
                [None, *options["tickers"]],
                key=prefix + "ticker",
                format_func=lambda value: value or "Todos os tickers",
            )
        filters = (start, end, event, ticker)
        if st.session_state.get(prefix + "filters") != filters:
            st.session_state[prefix + "page"] = 1
            st.session_state[prefix + "filters"] = filters
        try:
            result = AssetService.get_activity_page(
                page=st.session_state.get(prefix + "page", 1),
                start_date=start,
                end_date=end,
                event=event,
                ticker=ticker,
            )
        except ValueError as error:
            st.warning(str(error))
            return
        except Exception:
            logger.warning("portfolio.activity_read_failed")
            st.error("Não foi possível carregar as movimentações. Tente novamente.")
            return
        st.session_state[prefix + "page"] = result["page"]
        if result["activity"].empty:
            st.info(
                "Nenhuma movimentação encontrada para os filtros selecionados."
                if any(value is not None for value in filters)
                else "Nenhuma movimentação registrada nesta carteira."
            )
            return
        self._render_table(result["activity"])
        st.caption(
            f"Página {result['page']} de {result['pages']} · {result['total']} movimentações · "
            "25 por página"
        )
        previous, following = st.columns(2)
        with previous:
            st.button(
                "Anterior",
                key=prefix + "previous",
                disabled=result["page"] <= 1,
                on_click=self._change_page,
                args=(-1,),
            )
        with following:
            st.button(
                "Próxima",
                key=prefix + "next",
                disabled=result["page"] >= result["pages"],
                on_click=self._change_page,
                args=(1,),
            )

    @staticmethod
    def _render_table(activity):
        display = []
        for row in activity.to_dict("records"):
            date = pd.to_datetime(row["date"], errors="coerce")
            if row["value_status"] == "pending":
                value = "Custo pendente"
            elif row["value_status"] == "not_applicable":
                value = "—"
            else:
                value = Formatter.format_currency(row["value"])
            quantity = "—"
            if pd.notna(row["quantity"]):
                quantity = f"{row['quantity']:.10f}".rstrip("0").rstrip(".").replace(".", ",")
                if row["quantity_status"] == "estimated":
                    quantity += " (estimada)"
            display.append(
                {
                    "Data": date.strftime("%d/%m/%Y") if pd.notna(date) else "Data indisponível",
                    "Evento": row["event"],
                    "Ticker": row["ticker"],
                    "Quantidade": quantity,
                    "Valor": value,
                }
            )
        table = pd.DataFrame(display).style.apply(style_activity_row, axis=1)
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            height="content",
            column_config={
                "Quantidade": st.column_config.TextColumn(
                    "Quantidade",
                    help=(
                        "Proventos usam a quantidade informada pela B3. Sem ela, a quantidade "
                        "estimada é Total ÷ Unitário, sem arredondamento prévio. O unitário "
                        "antigo usa a posição na data do pagamento, que pode diferir da "
                        "quantidade remunerada. Sem dados suficientes, mostramos —."
                    ),
                )
            },
        )
        st.caption(
            "Compras incluem taxas; vendas descontam taxas. Eventos societários não têm valor "
            "financeiro; em grupamentos, a quantidade indica o total final. Transferências de "
            "custódia não representam entrada de dinheiro."
        )

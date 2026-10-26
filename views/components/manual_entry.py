import datetime
import sqlite3

import pandas as pd
import streamlit as st

from core.constants import SESSION_ACTIVE_DATABASE_GENERATION, WIDGET_MANUAL_ENTRY_PREFIX
from core.performance import measure_navigation
from core.strings import (
    HELP_OPS_SEARCH,
    MSG_INVALID_ASSET_SELECTION,
    MSG_MANUAL_ENTRY_SUCCESS_DIV,
    MSG_MANUAL_ENTRY_SUCCESS_TX,
    MSG_MANUAL_ENTRY_TITLE,
)
from core.utils.formatter import Formatter
from services.assets_service import AssetService
from views.cached_market_data import StreamlitCachedMarketData as MarketData
from views.components.goal_editor_state import invalidate_goal_editor_state


class ManualEntryWidget:
    """Render the shared manual entry flow, optionally bound to one ticker."""

    @staticmethod
    def _get_available_tickers(entry_type: str, catalog: pd.DataFrame) -> list[str]:
        """Return catalog tickers valid for the selected manual operation."""
        is_sale = "Venda" in entry_type
        is_earning = "Dividendo" in entry_type or "JCP" in entry_type or "Rendimento" in entry_type
        is_corp_event = "Desdobro" in entry_type or "Grupamento" in entry_type

        if is_sale or is_earning or is_corp_event:
            try:
                owned_tickers = AssetService.get_owned_tickers()
                return sorted(owned_tickers)
            except Exception:
                pass
            return []

        return sorted(catalog.index.tolist()) if not catalog.empty else []

    def render(self, ticker: str | None = None):
        with measure_navigation("ativos.operacoes", "manual_catalog"):
            catalog = MarketData.load_assets_catalog() if ticker is None else pd.DataFrame()
        st.fragment(run_every=2)(self._render)(ticker, catalog)

    @staticmethod
    def _mark_price_edited(context_key):
        st.session_state[f"{context_key}_price_edited"] = True

    @staticmethod
    def _show_error(context_key, message):
        st.session_state[f"{context_key}_error"] = message
        st.error(message)

    def _render_price(self, context_key, ticker, day, entry_type):
        price_key = f"{context_key}_price"
        edited_key = f"{context_key}_price_edited"
        applied_key = f"{context_key}_price_applied"
        selection_key = f"{context_key}_price_selection"
        selection = (ticker, day.isoformat(), entry_type)
        if st.session_state.get(selection_key) != selection or price_key not in st.session_state:
            st.session_state[selection_key] = selection
            st.session_state[price_key] = None
            st.session_state[edited_key] = False
            st.session_state[applied_key] = False
            st.session_state.pop(f"{context_key}_error", None)

        reference = None
        if ticker and day <= datetime.date.today():
            reference = MarketData.get_price_on_date(ticker, day)
            status = MarketData.get_price_on_date_status(ticker, day)
            if (
                reference is not None
                and round(reference, 2) >= 0.01
                and not status.stale
                and not st.session_state[edited_key]
                and not st.session_state[applied_key]
            ):
                st.session_state[price_key] = round(reference, 2)
                st.session_state[applied_key] = True

        price = st.number_input(
            "Preço Unitário (R$)",
            min_value=0.01,
            value=None,
            step=0.01,
            key=price_key,
            on_change=self._mark_price_edited,
            args=(context_key,),
            help="Referência de fechamento do Yahoo Finance, editável para o preço da sua negociação. Preços antigos podem ser revistos pelo Yahoo após desdobramentos.",
        )
        if not ticker:
            st.caption("Selecione um ativo para buscar o preço de referência.")
        elif day > datetime.date.today():
            st.caption("Não há cotação para datas futuras. Informe o preço manualmente.")
        elif status.updating:
            st.caption(
                "Buscando preço no Yahoo Finance. Você já pode informar o preço manualmente."
            )
        elif status.failed:
            st.caption("Não foi possível consultar o Yahoo Finance. Informe o preço manualmente.")
        elif reference is None:
            st.caption("Sem cotação para esta data no Yahoo Finance. Informe o preço manualmente.")
        else:
            st.caption(
                f"Referência do Yahoo Finance em {day:%d/%m/%Y}: "
                f"{Formatter.format_currency(reference)}. Confirme o preço da sua negociação."
            )
            if day == datetime.date.today():
                st.caption("O preço de hoje pode ser provisório enquanto o pregão estiver aberto.")
        return price

    def _render(self, ticker, catalog):
        st.subheader("Registrar movimentação" if ticker else MSG_MANUAL_ENTRY_TITLE)
        database = st.session_state.get("active_db", "portfolio.db")
        generation = st.session_state.get(SESSION_ACTIVE_DATABASE_GENERATION, "")
        context_key = (
            f"{WIDGET_MANUAL_ENTRY_PREFIX}{database}_{generation}_{ticker or 'operations'}"
        )
        if st.session_state.pop(f"{context_key}_reset", False):
            for key in list(st.session_state):
                if key.startswith(f"{context_key}_") and key != f"{context_key}_type":
                    del st.session_state[key]

        entry_type = st.selectbox(
            "Tipo de Lançamento",
            [
                "Compra (Aporte)",
                "Venda (Resgate)",
                "Desdobro / Bonificação",
                "Grupamento",
                "Dividendo (Recebimento)",
                "JCP (Recebimento)",
                "Rendimento (FII/Outros)",
            ],
            key=f"{context_key}_type",
        )

        is_sale = "Venda" in entry_type
        is_earning = "Dividendo" in entry_type or "JCP" in entry_type or "Rendimento" in entry_type
        is_corp_event = "Desdobro" in entry_type or "Grupamento" in entry_type
        requires_owned_ticker = is_sale or is_earning or is_corp_event
        with measure_navigation("ativos.operacoes", "manual_ticker_options"):
            available_tickers = (
                self._get_available_tickers(entry_type, catalog)
                if ticker is None or requires_owned_ticker
                else [ticker]
            )
            options = ["--- Selecione ---"]
            if ticker is None:
                catalog_names = dict(AssetService.get_asset_catalog_entries(catalog))
                options.extend(
                    f"{available_ticker} - "
                    f"{catalog_names.get(available_ticker, 'Ativo não catalogado')}"
                    for available_ticker in dict.fromkeys(available_tickers)
                )

        with measure_navigation("ativos.operacoes", "manual_controls"):
            date = st.date_input(
                "Data do Negócio/Pagamento",
                datetime.date.today(),
                format="DD/MM/YYYY",
                key=f"{context_key}_date",
            )

            if ticker is None:
                ticker_selection = st.selectbox(
                    "Selecione o Ativo",
                    options=options,
                    index=0,
                    help=HELP_OPS_SEARCH,
                    accept_new_options=not (is_sale or is_earning or is_corp_event),
                    key=f"{context_key}_ticker",
                )
            else:
                st.caption(f"Ativo: {ticker}")
                ticker_selection = ticker

            if (is_sale or is_earning or is_corp_event) and not available_tickers:
                st.warning(
                    "⚠️ Você não possui nenhum ativo em carteira para realizar essa operação."
                )

            if "Compra" in entry_type or "Venda" in entry_type:
                qty = st.number_input(
                    "Quantidade", min_value=1, value=100, step=1, key=f"{context_key}_qty"
                )
                selected_ticker = (
                    ticker_selection.split(" - ")[0].strip().upper()
                    if ticker_selection != "--- Selecione ---"
                    else ""
                )
                price = self._render_price(context_key, selected_ticker, date, entry_type)
                fees = st.number_input(
                    "Taxas/Corretagem (R$)",
                    min_value=0.0,
                    value=0.0,
                    step=0.1,
                    key=f"{context_key}_fees",
                )
                total_val = 0.0
            elif "Desdobro" in entry_type:
                qty = st.number_input(
                    "Quantidade de Novas Ações Recebidas",
                    min_value=1,
                    value=10,
                    step=1,
                    key=f"{context_key}_split_qty",
                )
                price = 0.0
                fees = 0.0
                total_val = 0.0
            elif "Grupamento" in entry_type:
                qty = st.number_input(
                    "Nova Quantidade Total (Ações Finais)",
                    min_value=1,
                    value=10,
                    step=1,
                    key=f"{context_key}_group_qty",
                )
                price = 0.0
                fees = 0.0
                total_val = 0.0
            else:
                qty = 0
                price = 0.0
                fees = 0.0
                total_val = st.number_input(
                    "Valor Total Recebido (R$)",
                    min_value=0.01,
                    value=10.00,
                    step=0.1,
                    key=f"{context_key}_income",
                )

            submit = st.button("Registrar Lançamento", key=f"{context_key}_submit")
            if not submit and (error := st.session_state.get(f"{context_key}_error")):
                st.error(error)

            if submit:
                st.session_state.pop(f"{context_key}_error", None)
                if (
                    ticker is not None
                    and (is_sale or is_earning or is_corp_event)
                    and ticker not in available_tickers
                ):
                    self._show_error(
                        context_key,
                        "Este ativo não está disponível em carteira para essa operação.",
                    )
                elif ticker_selection == "--- Selecione ---":
                    self._show_error(context_key, MSG_INVALID_ASSET_SELECTION)
                elif ("Compra" in entry_type or "Venda" in entry_type) and price is None:
                    self._show_error(
                        context_key, "Informe o preço unitário antes de registrar o lançamento."
                    )
                else:
                    # Extract the pure ticker from the custom selected string
                    ticker_input = (
                        ticker if ticker is not None else ticker_selection.split(" - ")[0]
                    )

                    if (
                        "Compra" in entry_type
                        or "Venda" in entry_type
                        or "Desdobro" in entry_type
                        or "Grupamento" in entry_type
                    ):
                        if "Compra" in entry_type:
                            tx_type = "Compra"
                        elif "Venda" in entry_type:
                            tx_type = "Venda"
                        elif "Desdobro" in entry_type:
                            tx_type = (
                                "Compra"  # Desdobro/Bonificação maps to BUY with unit_price = 0.0
                            )
                        elif "Grupamento" in entry_type:
                            tx_type = "Grupamento"  # Maps to GROUP in service

                        try:
                            success = AssetService.add_transaction(
                                ticker_input,
                                date.strftime("%Y-%m-%d"),
                                tx_type,
                                qty,
                                price,
                                fees,
                            )
                        except ValueError as error:
                            self._show_error(context_key, str(error))
                            return
                        except (sqlite3.Error, RuntimeError):
                            self._show_error(
                                context_key,
                                "Não foi possível salvar a movimentação. Tente novamente.",
                            )
                            return
                        if success:
                            if "Compra" in entry_type:
                                success_msg = MSG_MANUAL_ENTRY_SUCCESS_TX.format(
                                    tx_type="Compra", qty=qty, ticker=ticker_input
                                )
                            elif "Venda" in entry_type:
                                success_msg = MSG_MANUAL_ENTRY_SUCCESS_TX.format(
                                    tx_type="Venda", qty=qty, ticker=ticker_input
                                )
                            elif "Desdobro" in entry_type:
                                success_msg = f"Desdobro / Bonificação de {qty} ações de {ticker_input} registrado com sucesso!"
                            elif "Grupamento" in entry_type:
                                success_msg = f"Grupamento de {ticker_input} para nova quantidade de {qty} ações registrado com sucesso!"
                            st.success(success_msg)
                        else:
                            self._show_error(
                                context_key,
                                "Erro ao registrar a movimentação ou lançamento duplicado.",
                            )
                            return
                    else:
                        div_type = (
                            "Dividendo"
                            if "Dividendo" in entry_type
                            else ("JCP" if "JCP" in entry_type else "Rendimento")
                        )
                        try:
                            success = AssetService.add_dividend(
                                ticker_input, date.strftime("%Y-%m-%d"), div_type, total_val
                            )
                        except ValueError as error:
                            self._show_error(context_key, str(error))
                            return
                        except (sqlite3.Error, RuntimeError):
                            self._show_error(
                                context_key, "Não foi possível salvar o provento. Tente novamente."
                            )
                            return
                        if success:
                            st.success(
                                MSG_MANUAL_ENTRY_SUCCESS_DIV.format(
                                    value=Formatter.format_currency(total_val),
                                    div_type=div_type,
                                    ticker=ticker_input,
                                )
                            )
                        else:
                            self._show_error(
                                context_key, "Erro ao registrar o provento ou lançamento duplicado."
                            )
                            return

                    invalidate_goal_editor_state()
                    st.session_state[f"{context_key}_reset"] = True
                    st.rerun()

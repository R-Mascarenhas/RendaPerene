import datetime
import sqlite3

import pandas as pd
import streamlit as st

from core.constants import WIDGET_MANUAL_ENTRY_PREFIX
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
        st.subheader("Registrar movimentação" if ticker else MSG_MANUAL_ENTRY_TITLE)
        database = st.session_state.get("active_db", "portfolio.db")
        context_key = f"{WIDGET_MANUAL_ENTRY_PREFIX}{database}_{ticker or 'operations'}"

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

        # Load the assets catalog dynamically to construct the autocompleting ticker + name options
        with measure_navigation("ativos.operacoes", "manual_catalog"):
            catalog = MarketData.load_assets_catalog()

        is_sale = "Venda" in entry_type
        is_earning = "Dividendo" in entry_type or "JCP" in entry_type or "Rendimento" in entry_type
        is_corp_event = "Desdobro" in entry_type or "Grupamento" in entry_type
        with measure_navigation("ativos.operacoes", "manual_ticker_options"):
            available_tickers = self._get_available_tickers(entry_type, catalog)

            options = ["--- Selecione ---"]
            for available_ticker in available_tickers:
                if not catalog.empty and available_ticker in catalog.index:
                    catalog_row = catalog.loc[available_ticker]
                    if isinstance(catalog_row, pd.DataFrame):
                        catalog_row = catalog_row.iloc[0]
                    name = catalog_row.get("NOME", "Nome não disponível")
                else:
                    name = "Ativo não catalogado"
                options.append(f"{available_ticker} - {name}")

        with (
            measure_navigation("ativos.operacoes", "manual_controls"),
            st.form(context_key, clear_on_submit=True),
        ):
            date = st.date_input(
                "Data do Negócio/Pagamento", datetime.date.today(), format="DD/MM/YYYY"
            )

            if ticker is None:
                ticker_selection = st.selectbox(
                    "Selecione o Ativo",
                    options=options,
                    index=0,
                    help=HELP_OPS_SEARCH,
                    accept_new_options=not (is_sale or is_earning or is_corp_event),
                )
            else:
                st.caption(f"Ativo: {ticker}")
                ticker_selection = ticker

            if (is_sale or is_earning or is_corp_event) and not available_tickers:
                st.warning(
                    "⚠️ Você não possui nenhum ativo em carteira para realizar essa operação."
                )

            if "Compra" in entry_type or "Venda" in entry_type:
                qty = st.number_input("Quantidade", min_value=1, value=100, step=1)
                price = st.number_input(
                    "Preço Unitário (R$)", min_value=0.01, value=10.00, step=0.1
                )
                fees = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, value=0.0, step=0.1)
                total_val = 0.0
            elif "Desdobro" in entry_type:
                qty = st.number_input(
                    "Quantidade de Novas Ações Recebidas", min_value=1, value=10, step=1
                )
                price = 0.0
                fees = 0.0
                total_val = 0.0
            elif "Grupamento" in entry_type:
                qty = st.number_input(
                    "Nova Quantidade Total (Ações Finais)", min_value=1, value=10, step=1
                )
                price = 0.0
                fees = 0.0
                total_val = 0.0
            else:
                qty = 0
                price = 0.0
                fees = 0.0
                total_val = st.number_input(
                    "Valor Total Recebido (R$)", min_value=0.01, value=10.00, step=0.1
                )

            submit = st.form_submit_button("Registrar Lançamento")

            if submit:
                if (
                    ticker is not None
                    and (is_sale or is_earning or is_corp_event)
                    and ticker not in available_tickers
                ):
                    st.error("Este ativo não está disponível em carteira para essa operação.")
                elif ticker_selection == "--- Selecione ---":
                    st.error(MSG_INVALID_ASSET_SELECTION)
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
                            st.error(str(error))
                            return
                        except (sqlite3.Error, RuntimeError):
                            st.error("Não foi possível salvar a movimentação. Tente novamente.")
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
                            st.error("Erro ao registrar a movimentação ou lançamento duplicado.")
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
                            st.error(str(error))
                            return
                        except (sqlite3.Error, RuntimeError):
                            st.error("Não foi possível salvar o provento. Tente novamente.")
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
                            st.error("Erro ao registrar o provento ou lançamento duplicado.")
                            return

                    invalidate_goal_editor_state()
                    st.rerun()

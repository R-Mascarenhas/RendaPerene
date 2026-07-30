import streamlit as st

import datetime
import pandas as pd
from services.assets_service import AssetService
from core.utils.market_data import MarketData
from core.strings import (
    MSG_INVALID_ASSET_SELECTION, MSG_MANUAL_ENTRY_TITLE, MSG_MANUAL_ENTRY_SUCCESS_TX,
    MSG_MANUAL_ENTRY_SUCCESS_DIV, MSG_SMART_IMPORTER_TITLE, MSG_SMART_IMPORTER_DESC,
    MSG_SMART_IMPORTER_SUCCESS, MSG_SMART_IMPORTER_ERROR, HELP_OPS_SEARCH,
)

class OperationsView:
    """Class responsible for rendering the manual transactions and B3 uploader forms."""

    def render(self):
        st.header("Gestão de Movimentações")
        col1, col2 = st.columns(2)

        with col1:
            self._render_unified_manual_form()

        with col2:
            self._render_b3_import_zone()

    def _render_unified_manual_form(self):
        st.subheader(MSG_MANUAL_ENTRY_TITLE)

        entry_type = st.selectbox(
            "Tipo de Lançamento",
            [
                "Compra (Aporte)",
                "Venda (Resgate)",
                "Desdobro / Bonificação",
                "Grupamento",
                "Dividendo (Recebimento)",
                "JCP (Recebimento)",
                "Rendimento (FII/Outros)"
            ]
        )

        # Load the assets catalog dynamically to construct the autocompleting ticker + name options
        catalog = MarketData.load_assets_catalog()

        is_earning = "Dividendo" in entry_type or "JCP" in entry_type or "Rendimento" in entry_type
        is_corp_event = "Desdobro" in entry_type or "Grupamento" in entry_type

        if is_earning or is_corp_event:
            try:
                df_positions = AssetService.calculate_positions()
                if not df_positions.empty and "ticker" in df_positions.columns:
                    owned_tickers = df_positions["ticker"].tolist()
                    available_tickers = sorted([t for t in owned_tickers if t in catalog.index])
                else:
                    available_tickers = []
            except Exception:
                available_tickers = []
        else:
            available_tickers = sorted(catalog.index.tolist()) if not catalog.empty else []

        options = ["--- Selecione ---"] + [f"{t} - {catalog.loc[t, 'NOME']}" for t in available_tickers if t in catalog.index]

        with st.form("form_unified_entry", clear_on_submit=True):
            date = st.date_input("Data do Negócio/Pagamento", datetime.date.today(), format="DD/MM/YYYY")

            # Premium autocomplete select box enabling searching by either ticker or company name!
            ticker_selection = st.selectbox(
                "Selecione o Ativo",
                options=options,
                index=0,
                help=HELP_OPS_SEARCH
            )

            if (is_earning or is_corp_event) and not available_tickers:
                st.warning("⚠️ Você não possui nenhum ativo em carteira para realizar essa operação.")

            if "Compra" in entry_type or "Venda" in entry_type:
                qty = st.number_input("Quantidade", min_value=1, value=100, step=1)
                price = st.number_input("Preço Unitário (R$)", min_value=0.01, value=10.00, step=0.1)
                fees = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, value=0.0, step=0.1)
                total_val = 0.0
            elif "Desdobro" in entry_type:
                qty = st.number_input("Quantidade de Novas Ações Recebidas", min_value=1, value=10, step=1)
                price = 0.0
                fees = 0.0
                total_val = 0.0
            elif "Grupamento" in entry_type:
                qty = st.number_input("Nova Quantidade Total (Ações Finais)", min_value=1, value=10, step=1)
                price = 0.0
                fees = 0.0
                total_val = 0.0
            else:
                qty = 0
                price = 0.0
                fees = 0.0
                total_val = st.number_input("Valor Total Recebido (R$)", min_value=0.01, value=10.00, step=0.1)

            submit = st.form_submit_button("Registrar Lançamento")

            if submit:
                if ticker_selection == "--- Selecione ---":
                    st.error(MSG_INVALID_ASSET_SELECTION)
                else:
                    # Extract the pure ticker from the custom selected string
                    ticker_input = ticker_selection.split(" - ")[0]

                    if "Compra" in entry_type or "Venda" in entry_type or "Desdobro" in entry_type or "Grupamento" in entry_type:
                        if "Compra" in entry_type:
                            tx_type = "Compra"
                        elif "Venda" in entry_type:
                            tx_type = "Venda"
                        elif "Desdobro" in entry_type:
                            tx_type = "Compra" # Desdobro/Bonificação maps to BUY with unit_price = 0.0
                        elif "Grupamento" in entry_type:
                            tx_type = "Grupamento" # Maps to GROUP in service

                        success = AssetService.add_transaction(
                            ticker_input,
                            date.strftime("%Y-%m-%d"),
                            tx_type,
                            qty,
                            price,
                            fees
                        )
                        if success:
                            if "Compra" in entry_type:
                                success_msg = MSG_MANUAL_ENTRY_SUCCESS_TX.format(tx_type="Compra", qty=qty, ticker=ticker_input)
                            elif "Venda" in entry_type:
                                success_msg = MSG_MANUAL_ENTRY_SUCCESS_TX.format(tx_type="Venda", qty=qty, ticker=ticker_input)
                            elif "Desdobro" in entry_type:
                                success_msg = f"Desdobro / Bonificação de {qty} ações de {ticker_input} registrado com sucesso!"
                            elif "Grupamento" in entry_type:
                                success_msg = f"Grupamento de {ticker_input} para nova quantidade de {qty} ações registrado com sucesso!"
                            st.success(success_msg)
                        else:
                            st.error("Erro ao registrar a movimentação ou lançamento duplicado.")
                    else:
                        div_type = "Dividendo" if "Dividendo" in entry_type else ("JCP" if "JCP" in entry_type else "Rendimento")
                        success = AssetService.add_dividend(
                            ticker_input,
                            date.strftime("%Y-%m-%d"),
                            div_type,
                            total_val
                        )
                        if success:
                            st.success(MSG_MANUAL_ENTRY_SUCCESS_DIV.format(value=f'{total_val:.2f}', div_type=div_type, ticker=ticker_input))
                        else:
                            st.error("Erro ao registrar o provento ou lançamento duplicado.")

                    st.cache_data.clear()
                    st.rerun()

    def _render_b3_import_zone(self):
        st.subheader(MSG_SMART_IMPORTER_TITLE)
        st.write(MSG_SMART_IMPORTER_DESC)

        b3_file = st.file_uploader("Arraste o arquivo .xlsx da B3 aqui", type=["xlsx"])
        if b3_file is not None:
            file_key = f"{b3_file.name}_{b3_file.size}"
            if "processed_files" not in st.session_state:
                st.session_state.processed_files = set()

            if file_key not in st.session_state.processed_files:
                try:
                    with st.spinner("Processando e importando planilha B3..."):
                        df_excel = pd.read_excel(b3_file)
                        processed_tx, processed_div = AssetService.process_b3_import(df_excel)

                        st.success(MSG_SMART_IMPORTER_SUCCESS.format(tx_count=processed_tx, div_count=processed_div))
                        st.session_state.processed_files.add(file_key)
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(MSG_SMART_IMPORTER_ERROR.format(e=e))
            else:
                pass

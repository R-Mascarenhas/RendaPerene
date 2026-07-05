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
                "Dividendo (Recebimento)",
                "JCP (Recebimento)",
                "Rendimento (FII/Outros)"
            ]
        )

        # Load the assets catalog dynamically to construct the autocompleting ticker + name options
        catalog = MarketData.load_assets_catalog()

        is_earning = "Dividendo" in entry_type or "JCP" in entry_type or "Rendimento" in entry_type

        if is_earning:
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

            if is_earning and not available_tickers:
                st.warning("⚠️ Você não possui nenhum ativo em carteira para receber proventos.")

            if "Compra" in entry_type or "Venda" in entry_type:
                qty = st.number_input("Quantidade", min_value=1, value=100, step=1)
                price = st.number_input("Preço Unitário (R$)", min_value=0.01, value=10.00, step=0.1)
                fees = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, value=0.0, step=0.1)
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

                    if "Compra" in entry_type or "Venda" in entry_type:
                        tx_type = "Compra" if "Compra" in entry_type else "Venda"
                        AssetService.add_transaction(
                            ticker_input,
                            date.strftime("%Y-%m-%d"),
                            tx_type,
                            qty,
                            price,
                            fees
                        )
                        st.success(MSG_MANUAL_ENTRY_SUCCESS_TX.format(tx_type=tx_type, qty=qty, ticker=ticker_input))
                    else:
                        div_type = "Dividendo" if "Dividendo" in entry_type else ("JCP" if "JCP" in entry_type else "Rendimento")
                        AssetService.add_dividend(
                            ticker_input,
                            date.strftime("%Y-%m-%d"),
                            div_type,
                            total_val
                        )
                        st.success(MSG_MANUAL_ENTRY_SUCCESS_DIV.format(value=f'{total_val:.2f}', div_type=div_type, ticker=ticker_input))

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

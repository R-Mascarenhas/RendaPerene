import pandas as pd
import streamlit as st

from core.constants import WIDGET_B3_FILE_UPLOADER_PREFIX
from core.performance import instrument_screen, measure_navigation
from core.strings import (
    MSG_SMART_IMPORTER_DESC,
    MSG_SMART_IMPORTER_ERROR,
    MSG_SMART_IMPORTER_SUCCESS,
    MSG_SMART_IMPORTER_TITLE,
)
from services.assets_service import AssetService
from views.components.manual_entry import ManualEntryWidget
from views.components.portfolio_activity import PortfolioActivityWidget


class OperationsView:
    """Class responsible for rendering the manual transactions and B3 uploader forms."""

    _get_available_tickers = staticmethod(ManualEntryWidget._get_available_tickers)

    @instrument_screen("ativos.operacoes")
    def render(self):
        st.header("Gestão de Movimentações")
        col1, col2 = st.columns(2)

        with col1, measure_navigation("ativos.operacoes", "manual_entry"):
            self._render_unified_manual_form()

        with col2, measure_navigation("ativos.operacoes", "b3_import"):
            self._render_b3_import_zone()

        with measure_navigation("ativos.operacoes", "pending_costs"):
            self._render_pending_costs()

        PortfolioActivityWidget().render_history()

    def _render_pending_costs(self):
        pending = AssetService.get_pending_costs()
        if pending.empty:
            return
        st.subheader("Custos pendentes da B3")
        st.warning(
            "Há entradas sem custo informado. Regularize-as para calcular preço médio e rentabilidade."
        )
        st.info(
            "Consulte o comprovante da oferta, extrato financeiro, nota/comprovante de liquidação "
            "ou declaração de IR para recuperar o custo. Não usamos cotações históricas como custo."
        )
        options = {
            int(row["id"]): f"{row['ticker']} · {row['date']} · {row['quantity']} unidades"
            for row in pending.to_dict("records")
        }
        selected = st.selectbox(
            "Operação pendente",
            list(options),
            format_func=options.get,
            key="pending_cost_operation",
        )
        source = pending.loc[pending["id"] == selected].iloc[0]
        st.caption(f"Origem B3: {source['movement']} · {source['institution']}")
        with st.form(f"regularize_cost_{selected}"):
            mode = st.selectbox(
                "Informar custo por", ["Preço unitário", "Valor total da aquisição"]
            )
            value = st.number_input(
                "Custo da aquisição (R$)", min_value=0.01, value=10.00, format="%.2f"
            )
            fees = st.number_input("Taxas adicionais (R$)", min_value=0.0, value=0.0)
            st.caption("O valor total deve excluir as taxas adicionais informadas acima.")
            submitted = st.form_submit_button("Regularizar custo")
        if submitted:
            try:
                if AssetService.regularize_cost(
                    selected, value, value_is_total=mode == "Valor total da aquisição", fees=fees
                ):
                    st.rerun()
                else:
                    st.warning("Esta operação já foi regularizada. Atualize a página.")
            except ValueError as exc:
                st.error(str(exc))

    def _render_unified_manual_form(self):
        ManualEntryWidget().render()

    def _render_b3_import_zone(self):
        st.subheader(MSG_SMART_IMPORTER_TITLE)
        st.write(MSG_SMART_IMPORTER_DESC)

        if "b3_uploader_key" not in st.session_state:
            st.session_state.b3_uploader_key = 0

        b3_file = st.file_uploader(
            "Arraste o arquivo .xlsx da B3 aqui",
            type=["xlsx"],
            key=f"{WIDGET_B3_FILE_UPLOADER_PREFIX}{st.session_state.b3_uploader_key}",
        )

        # Show persistent success message if present in session_state
        if st.session_state.get("b3_import_success_msg"):
            st.success(st.session_state.b3_import_success_msg)

        if b3_file is not None:
            file_key = f"{b3_file.name}_{b3_file.size}"
            if "processed_files" not in st.session_state:
                st.session_state.processed_files = set()

            if file_key not in st.session_state.processed_files:
                try:
                    st.session_state.b3_import_success_msg = None
                    progress_bar = st.progress(0.0, text="Lendo arquivo Excel da B3...")
                    df_excel = pd.read_excel(b3_file)

                    last_pct = -1.0

                    def update_progress(current: int, total: int):
                        nonlocal last_pct
                        pct = current / total if total > 0 else 0.0
                        clamped_pct = max(0.0, min(1.0, float(pct)))
                        # Throttle updates: only update progress bar if percentage increases by >= 5% or it's the last row
                        if (clamped_pct - last_pct) >= 0.05 or current == total:
                            progress_bar.progress(
                                clamped_pct,
                                text=f"📊 Processando linha {current} de {total}... ({int(clamped_pct * 100)}%)",
                            )
                            last_pct = clamped_pct

                    processed_tx, processed_div = AssetService.process_b3_import(
                        df_excel, progress_callback=update_progress
                    )

                    progress_bar.progress(1.0, text="✅ Importação concluída!")
                    success_text = MSG_SMART_IMPORTER_SUCCESS.format(
                        tx_count=processed_tx, div_count=processed_div
                    )
                    st.session_state.b3_import_success_msg = success_text
                    st.session_state.processed_files.add(file_key)
                    st.session_state.b3_uploader_key += 1
                    st.rerun()
                except Exception as e:
                    st.error(MSG_SMART_IMPORTER_ERROR.format(e=e))
            else:
                pass

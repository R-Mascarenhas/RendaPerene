import hashlib

import pandas as pd
import streamlit as st

from core.constants import SESSION_ACTIVE_DATABASE_GENERATION, WIDGET_B3_FILE_UPLOADER_PREFIX
from core.performance import instrument_screen, measure_navigation
from core.strings import (
    MSG_SMART_IMPORTER_DESC,
    MSG_SMART_IMPORTER_ERROR,
    MSG_SMART_IMPORTER_SUCCESS,
    MSG_SMART_IMPORTER_TITLE,
)
from core.utils.formatter import Formatter
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

    @st.fragment
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
                    preview_context = (
                        file_key,
                        hashlib.sha256(b3_file.getvalue()).hexdigest(),
                        st.session_state.get("active_db"),
                        st.session_state.get(SESSION_ACTIVE_DATABASE_GENERATION),
                        AssetService.get_local_projection_revision(),
                    )
                    preview = st.session_state.get("b3_import_preview")
                    if preview is None or preview["context"] != preview_context:
                        self._discard_b3_preview()
                        df_excel = pd.read_excel(b3_file)
                        reconciliation_candidates = AssetService.find_b3_manual_trade_candidates(
                            df_excel
                        )
                        serial = st.session_state.get("b3_import_preview_serial", 0) + 1
                        st.session_state.b3_import_preview_serial = serial
                        preview = {
                            "context": preview_context,
                            "frame": df_excel,
                            "candidates": reconciliation_candidates,
                            "serial": serial,
                        }
                        st.session_state.b3_import_preview = preview
                    df_excel = preview["frame"]
                    reconciliation_candidates = preview["candidates"]
                    if reconciliation_candidates:
                        st.info(
                            "Encontramos operações manuais que podem corresponder a linhas da B3. "
                            "Confira cada sugestão; a importação só vincula operações que você confirmar."
                        )
                        links = {}
                        choices_complete = True
                        with st.container():
                            for index, candidate in enumerate(reconciliation_candidates):
                                b3 = candidate["b3"]
                                st.markdown(
                                    f"**{b3['ticker']} · "
                                    f"{'Compra' if b3['transaction_type'] == 'BUY' else 'Venda'} · "
                                    f"{b3['quantity']} cotas · "
                                    rf"R\$ {b3['unit_price']:.2f} · "
                                    rf"total R\$ {b3['value']:.2f}**"
                                )
                                st.caption(
                                    f"Data na planilha B3: {pd.Timestamp(b3['date']).strftime('%d/%m/%Y')}"
                                )
                                if b3["institution"]:
                                    st.caption(f"Instituição na B3: {b3['institution']}")
                                options = [
                                    "Importar como nova operação",
                                    *candidate["manual_groups"],
                                ]
                                selected = st.selectbox(
                                    "Lançamento manual correspondente",
                                    options,
                                    index=None,
                                    placeholder="Selecione uma opção",
                                    key=f"b3_match_{preview['serial']}_{index}",
                                    format_func=lambda item: (
                                        item
                                        if isinstance(item, str)
                                        else (
                                            f"{len(item['transactions'])} "
                                            f"{'Lançamento' if len(item['transactions']) == 1 else 'Lançamentos'}: "
                                            f"{pd.Timestamp(item['transactions'][0]['date']).strftime('%d/%m/%Y')} · "
                                            + " + ".join(
                                                f"{tx['quantity']} × "
                                                f"{Formatter.format_currency(tx['unit_price'])}"
                                                + (
                                                    f" + taxa {Formatter.format_currency(tx['fees'])}"
                                                    if tx["fees"] != 0
                                                    else ""
                                                )
                                                for tx in item["transactions"]
                                            )
                                        )
                                    ),
                                )
                                if selected is None:
                                    choices_complete = False
                                elif isinstance(selected, dict):
                                    links[candidate["source_key"]] = selected["ids"]
                            linked_transaction_ids = [
                                transaction_id
                                for transaction_ids in links.values()
                                for transaction_id in transaction_ids
                            ]
                            duplicate_links = len(set(linked_transaction_ids)) != len(
                                linked_transaction_ids
                            )
                            if duplicate_links:
                                st.error(
                                    "Cada lançamento manual pode corresponder a apenas uma linha B3."
                                )
                            submitted = st.button(
                                "Confirmar e importar planilha",
                                key=f"b3_reconciliation_{preview['serial']}",
                                disabled=not choices_complete or duplicate_links,
                            )
                        if submitted and choices_complete and not duplicate_links:
                            self._process_b3_frame(df_excel, file_key, links)
                    else:
                        self._process_b3_frame(df_excel, file_key, {})
                except Exception as e:
                    st.session_state.pop("b3_import_preview", None)
                    st.error(MSG_SMART_IMPORTER_ERROR.format(e=e))
            else:
                self._discard_b3_preview()
        else:
            self._discard_b3_preview()

    @staticmethod
    def _discard_b3_preview():
        st.session_state.pop("b3_import_preview", None)
        for key in list(st.session_state):
            if isinstance(key, str) and key.startswith(("b3_match_", "b3_reconciliation_")):
                st.session_state.pop(key, None)

    @staticmethod
    def _process_b3_frame(df_excel, file_key, manual_trade_links):
        progress_bar = st.progress(0.0, text="Lendo arquivo Excel da B3...")
        last_pct = -1.0

        def update_progress(current: int, total: int):
            nonlocal last_pct
            pct = current / total if total > 0 else 0.0
            clamped_pct = max(0.0, min(1.0, float(pct)))
            if (clamped_pct - last_pct) >= 0.05 or current == total:
                progress_bar.progress(
                    clamped_pct,
                    text=f"📊 Processando linha {current} de {total}... ({int(clamped_pct * 100)}%)",
                )
                last_pct = clamped_pct

        processed_tx, processed_div = AssetService.process_b3_import(
            df_excel,
            progress_callback=update_progress,
            manual_trade_links=manual_trade_links,
        )
        progress_bar.progress(1.0, text="✅ Importação concluída!")
        st.session_state.b3_import_success_msg = MSG_SMART_IMPORTER_SUCCESS.format(
            tx_count=processed_tx, div_count=processed_div
        )
        st.session_state.pop("b3_import_preview", None)
        st.session_state.processed_files.add(file_key)
        st.session_state.b3_uploader_key += 1
        st.rerun()

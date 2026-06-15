import streamlit as st
import datetime
import pandas as pd
from lancamentos.service import TransactionService

class LancamentosView:
    """Class responsible for rendering the Lançamentos (Transactions) Tab GUI."""

    def render(self):
        st.header("Gestão de Movimentações")
        col1, col2 = st.columns(2)
        
        with col1:
            self._render_manual_transaction_form()
            st.markdown("---")
            self._render_manual_dividend_form()
            
        with col2:
            self._render_b3_import_zone()

    def _render_manual_transaction_form(self):
        st.subheader("Submeter Manualmente")
        with st.form("form_manual", clear_on_submit=True):
            transaction_date = st.date_input("Data do Negócio", datetime.date.today(), format="DD/MM/YYYY")
            ticker_input = st.text_input("Ticker do Ativo (ex: BBAS3)").strip().upper()
            transaction_type = st.selectbox("Tipo de Movimentação", ["Compra", "Venda"])
            quantity_input = st.number_input("Quantidade", min_value=1, value=100, step=1)
            price_input = st.number_input("Preço Unitário (R$)", min_value=0.01, value=10.00, step=0.1)
            fees_input = st.number_input("Taxas/Corretagem (R$)", min_value=0.0, value=0.0, step=0.1)
            
            submit = st.form_submit_button("Registrar Transação")
            if submit:
                if len(ticker_input) < 4:
                    st.error("Por favor, digite um Ticker válido (mínimo de 4 letras).")
                else:
                    TransactionService.add_transaction(
                        ticker_input, 
                        transaction_date.strftime("%Y-%m-%d"), 
                        transaction_type, 
                        quantity_input, 
                        price_input, 
                        fees_input
                    )
                    st.success(f"Sucesso! {transaction_type} de {quantity_input}x {ticker_input} salva no banco de dados!")
                    st.cache_data.clear()
                    st.rerun()

    def _render_manual_dividend_form(self):
        st.subheader("Inserção Manual de Dividendo/Provento")
        with st.form("form_dividends", clear_on_submit=True):
            dividend_date = st.date_input("Data de Pagamento", datetime.date.today(), format="DD/MM/YYYY")
            ticker_prov = st.text_input("Ticker do Ativo (ex: TAEE11)").strip().upper()
            dividend_type = st.selectbox("Tipo de Provento", ["Dividendo", "JCP", "Rendimento"])
            total_value = st.number_input("Valor Total Recebido (R$)", min_value=0.01, value=10.00, step=0.1)
            
            submit_prov = st.form_submit_button("Registrar Provento")
            if submit_prov:
                if len(ticker_prov) < 4:
                    st.error("Por favor, digite um Ticker válido.")
                else:
                    TransactionService.add_dividend(
                        ticker_prov, 
                        dividend_date.strftime("%Y-%m-%d"), 
                        dividend_type, 
                        total_value
                    )
                    st.success(f"Sucesso! Recebimento de R$ {total_value:.2f} em {dividend_type} de {ticker_prov} registrado!")
                    st.cache_data.clear()
                    st.rerun()

    def _render_b3_import_zone(self):
        st.subheader("🚀 Importador Inteligente da B3")
        st.write("Exporte o arquivo Excel (`.xlsx`) da sua Área do Investidor B3 (Movimentação) e arraste-o aqui para importar todas as transações e dividendos de uma única vez.")
        
        b3_file = st.file_uploader("Arraste o arquivo .xlsx da B3 aqui", type=["xlsx"])
        if b3_file is not None:
            file_key = f"{b3_file.name}_{b3_file.size}"
            if "processed_files" not in st.session_state:
                st.session_state.processed_files = set()
                
            if file_key not in st.session_state.processed_files:
                try:
                    with st.spinner("Processando e importando planilha B3..."):
                        df_excel = pd.read_excel(b3_file)
                        processed_tx, processed_div = TransactionService.process_b3_import(df_excel)
                        
                        st.success(f"Importação realizada com sucesso! Foram adicionadas {processed_tx} novas transações e {processed_div} registros de proventos no banco de dados local!")
                        st.session_state.processed_files.add(file_key)
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar arquivo B3. Certifique-se de que é o arquivo oficial da Área do Investidor. Detalhes: {e}")
            else:
                st.info("Este arquivo já foi importado e processado nesta sessão. Remova o arquivo para fazer uma nova importação.")

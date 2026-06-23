import streamlit as st
import datetime
import pandas as pd
from services.assets_service import AssetService
from core.utils.market_data import MarketData

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
        st.subheader("Registrar Lançamento Manual")
        
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
        available_tickers = sorted(catalog.index.tolist()) if not catalog.empty else []
        options = ["--- Selecione ---"] + [f"{t} - {catalog.loc[t, 'NOME']}" for t in available_tickers if t in catalog.index]

        with st.form("form_unified_entry", clear_on_submit=True):
            date = st.date_input("Data do Negócio/Pagamento", datetime.date.today(), format="DD/MM/YYYY")
            
            # Premium autocomplete select box enabling searching by either ticker or company name!
            ticker_selection = st.selectbox(
                "Selecione o Ativo",
                options=options,
                index=0,
                help="Digite para buscar pelo ticker ou por qualquer parte do nome da empresa cadastrada no assets.csv"
            )
            
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
                    st.error("Por favor, selecione um ativo válido da lista.")
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
                        st.success(f"Sucesso! {tx_type} de {qty}x {ticker_input} salva no banco de dados!")
                    else:
                        div_type = "Dividendo" if "Dividendo" in entry_type else ("JCP" if "JCP" in entry_type else "Rendimento")
                        AssetService.add_dividend(
                            ticker_input, 
                            date.strftime("%Y-%m-%d"), 
                            div_type, 
                            total_val
                        )
                        st.success(f"Sucesso! Recebimento de R$ {total_val:.2f} em {div_type} de {ticker_input} registrado!")
                        
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
                        processed_tx, processed_div = AssetService.process_b3_import(df_excel)
                        
                        st.success(f"Importação realizada com sucesso! Foram adicionadas {processed_tx} novas transações e {processed_div} registros de proventos no banco de dados local!")
                        st.session_state.processed_files.add(file_key)
                        st.cache_data.clear()
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro ao processar arquivo B3. Certifique-se de que é o arquivo oficial da Área do Investidor. Detalhes: {e}")
            else:
                pass

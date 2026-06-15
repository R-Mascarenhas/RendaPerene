import streamlit as st
from lancamentos.operations.view import OperationsView
from lancamentos.assets.view import AssetsView

class LancamentosView:
    """Class responsible for coordinating the multi-tab layout under 'Lançamentos & B3'."""

    def render(self):
        # Create top-level tabs inside Lançamentos & B3
        tab_ops, tab_assets = st.tabs([
            "📥 Importar & Lançar",
            "📁 Meus Ativos"
        ])

        with tab_ops:
            OperationsView().render()

        with tab_assets:
            AssetsView().render()

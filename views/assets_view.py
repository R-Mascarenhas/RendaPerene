import streamlit as st
from views.operations_view import OperationsView
from views.portfolio_view import PortfolioView
from views.market_view import MarketView

class AssetsView:
    """Class responsible for coordinating the multi-tab layout under 'Assets/Ativos'."""

    def render(self):
        tab_assets, tab_market, tab_ops = st.tabs([
            "📁 Meus Ativos",
            "📈 Mercado",
            "📥 Importar & Lançar"
        ])

        with tab_assets:
            PortfolioView().render()

        with tab_market:
            MarketView().render()

        with tab_ops:
            OperationsView().render()

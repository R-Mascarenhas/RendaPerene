import streamlit as st
from assets.operations.operations_view import OperationsView
from assets.portfolio.portfolio_view import PortfolioView
from assets.market.market_view import MarketView

class AssetsView:
    """Class responsible for coordinating the multi-tab layout under 'Assets/Ativos'."""

    def render(self):
        # Create top-level tabs inside 'Ativos'
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

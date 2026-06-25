import streamlit as st
from views.operations_view import OperationsView
from views.portfolio_view import PortfolioView
from views.market_view import MarketView
from core.strings import TAB_MY_ASSETS, TAB_MARKET, TAB_IMPORT_LAUNCH

class AssetsView:
    """Class responsible for coordinating the multi-tab layout under 'Assets/Ativos'."""

    def render(self):
        selected_subtab = st.segmented_control(
            "Navegação Ativos",
            options=[
                TAB_MY_ASSETS,
                TAB_MARKET,
                TAB_IMPORT_LAUNCH
            ],
            default=TAB_MY_ASSETS,
            label_visibility="collapsed"
        )

        if not selected_subtab:
            selected_subtab = TAB_MY_ASSETS

        if selected_subtab == TAB_MY_ASSETS:
            PortfolioView().render()
        elif selected_subtab == TAB_MARKET:
            MarketView().render()
        elif selected_subtab == TAB_IMPORT_LAUNCH:
            OperationsView().render()

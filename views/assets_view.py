import streamlit as st

from core.constants import SESSION_ASSETS_NAVIGATION_TARGET, WIDGET_ASSETS_NAVIGATION
from core.performance import instrument_screen
from core.strings import TAB_IMPORT_LAUNCH, TAB_MARKET, TAB_MY_ASSETS
from views.market_view import MarketView
from views.operations_view import OperationsView
from views.portfolio_view import PortfolioView


class AssetsView:
    """Class responsible for coordinating the multi-tab layout under 'Assets/Ativos'."""

    @instrument_screen("ativos.rota")
    def render(self):
        target = st.session_state.pop(SESSION_ASSETS_NAVIGATION_TARGET, None)
        if target is not None:
            st.session_state[WIDGET_ASSETS_NAVIGATION] = target
        selected_subtab = st.segmented_control(
            "Navegação Ativos",
            options=[TAB_MY_ASSETS, TAB_MARKET, TAB_IMPORT_LAUNCH],
            default=TAB_MY_ASSETS,
            label_visibility="collapsed",
            key=WIDGET_ASSETS_NAVIGATION,
        )

        if not selected_subtab:
            selected_subtab = TAB_MY_ASSETS

        if selected_subtab == TAB_MY_ASSETS:
            PortfolioView().render()
        elif selected_subtab == TAB_MARKET:
            MarketView().render()
        elif selected_subtab == TAB_IMPORT_LAUNCH:
            OperationsView().render()

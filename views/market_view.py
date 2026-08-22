import streamlit as st

from core.strings import TAB_ASSET_DEEP_DIVE, TAB_MARKET_MONITORING
from views.asset_deep_dive_view import AssetDeepDiveView
from views.market_monitoring_view import MarketMonitoringView


class MarketView:
    """Route the Market sub-navigation to its dedicated tab modules."""

    def render(self):
        """Render only the selected market tab."""
        selected_tab = st.segmented_control(
            "Navegação do Mercado",
            options=[TAB_MARKET_MONITORING, TAB_ASSET_DEEP_DIVE],
            default=TAB_MARKET_MONITORING,
            label_visibility="collapsed",
        )
        if selected_tab == TAB_MARKET_MONITORING:
            MarketMonitoringView().render()
        elif selected_tab == TAB_ASSET_DEEP_DIVE:
            AssetDeepDiveView().render()

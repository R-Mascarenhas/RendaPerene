"""Shared Plotly appearance for the application's charts."""

import plotly.graph_objects as go
import streamlit as st


class ChartThemeAdapter:
    """Applies the RendaPerene dark chart skin to Plotly figures."""

    BLUE = "#1f77b4"
    GREEN = "#2ca02c"
    DARK_GREEN = "#1a5c1a"
    RED = "#b41f1f"
    DARK_RED = "#a02c2c"
    YELLOW = "#f2c41a"
    ORANGE = "#ff7f0e"
    GRAY = "#6c757d"
    DARK_GRAY = "#333333"
    WHITE = "#ffffff"

    TRANSPARENT = "rgba(0, 0, 0, 0)"
    LIGHT_FONT_COLOR = "#31333f"
    DARK_FONT_COLOR = "#fafafa"
    LIGHT_GRID_COLOR = "rgba(49, 51, 63, 0.18)"
    DARK_GRID_COLOR = "rgba(255, 255, 255, 0.12)"
    LIGHT_ANNOTATION_BACKGROUND = "rgba(255, 255, 255, 0.9)"
    DARK_ANNOTATION_BACKGROUND = "rgba(33, 37, 41, 0.95)"
    GREEN_FILL = "rgba(44, 160, 44, 0.15)"
    GREEN_LINE = "rgba(44, 160, 44, 0.8)"
    BLUE_FILL = "rgba(31, 119, 180, 0.25)"
    BLUE_LINE = "rgba(31, 119, 180, 0.8)"
    YELLOW_FILL = "rgba(242, 196, 26, 0.6)"
    CURRENCY_TICK_FORMAT = "R$ ,.2f"
    YIELD_COLOR_SCALE = "Viridis"
    LEGEND = {"orientation": "h", "yanchor": "top", "y": -0.22, "xanchor": "left", "x": 0.0}

    @staticmethod
    def current_theme_type() -> str:
        """Return the active client theme, falling back while its context loads."""
        theme_type = st.context.theme.type
        if theme_type in {"light", "dark"}:
            return theme_type

        configured_theme = st.get_option("theme.base")
        if configured_theme in {"light", "dark"}:
            return configured_theme
        return "light"

    @staticmethod
    def is_dark_theme() -> bool:
        """Return whether the active Streamlit client theme is dark."""
        return ChartThemeAdapter.current_theme_type() == "dark"

    @staticmethod
    def annotation_background() -> str:
        """Return an annotation background that contrasts with the active theme."""
        if ChartThemeAdapter.is_dark_theme():
            return ChartThemeAdapter.DARK_ANNOTATION_BACKGROUND
        return ChartThemeAdapter.LIGHT_ANNOTATION_BACKGROUND

    @staticmethod
    def annotation_font_color() -> str:
        """Return an annotation font color that contrasts with its background."""
        if ChartThemeAdapter.is_dark_theme():
            return ChartThemeAdapter.DARK_FONT_COLOR
        return ChartThemeAdapter.LIGHT_FONT_COLOR

    @staticmethod
    def heatmap_empty_color() -> str:
        """Return a neutral heatmap-cell color compatible with the active theme."""
        return "#2a2f36" if ChartThemeAdapter.is_dark_theme() else "#edf2f7"

    @staticmethod
    def apply_theme(fig: go.Figure) -> go.Figure:
        """Apply shared visual settings for the configured Streamlit theme."""
        is_dark = ChartThemeAdapter.is_dark_theme()
        template = "plotly_dark" if is_dark else "plotly_white"
        font_color = (
            ChartThemeAdapter.DARK_FONT_COLOR if is_dark else ChartThemeAdapter.LIGHT_FONT_COLOR
        )
        grid_color = (
            ChartThemeAdapter.DARK_GRID_COLOR if is_dark else ChartThemeAdapter.LIGHT_GRID_COLOR
        )

        fig.update_layout(
            template=template,
            paper_bgcolor=ChartThemeAdapter.TRANSPARENT,
            plot_bgcolor=ChartThemeAdapter.TRANSPARENT,
            font={"family": "Arial, sans-serif", "size": 12, "color": font_color},
            margin={"l": 20, "r": 20, "t": 70, "b": 90},
            title={"x": 0.0, "xanchor": "left", "y": 0.98, "yanchor": "top"},
            hovermode="x unified",
            hoverlabel={"namelength": -1},
            legend=ChartThemeAdapter.LEGEND,
        )
        fig.update_xaxes(showgrid=True, gridcolor=grid_color)
        fig.update_yaxes(showgrid=True, gridcolor=grid_color)
        return fig

import math

from core.constants import BILLION, MILLION, MONTHS_PT, TRILLION


class Formatter:
    """Utility class for visual data and currency formatting."""

    @staticmethod
    def format_currency(value: float) -> str:
        """Format BRL values, compacting amounts whose magnitude reaches millions."""
        return Formatter._format_compact_value(value, prefix="R$ ", decimal_places=2)

    @staticmethod
    def format_market_value(value, value_type: str) -> str:
        """Format an optional Yahoo Finance value for the market detail screen."""
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return "N/D"

        if not math.isfinite(numeric_value):
            return "N/D"
        if value_type == "currency":
            return Formatter.format_currency(numeric_value)
        if value_type == "percentage":
            return f"{numeric_value * 100:.2f}%"
        if value_type == "percentage_points":
            return f"{numeric_value:.2f}%"
        if value_type == "integer":
            return Formatter.format_integer(numeric_value)
        return f"{numeric_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @staticmethod
    def format_integer(value: float) -> str:
        """Format integer-like values, compacting magnitudes at millions and billions."""
        return Formatter._format_compact_value(value, decimal_places=0)

    @staticmethod
    def _format_compact_value(value: float, *, prefix: str = "", decimal_places: int) -> str:
        """Format a signed value with Brazilian separators and optional compact magnitude suffixes."""
        numeric_value = float(value)
        absolute_value = abs(numeric_value)
        sign = "-" if numeric_value < 0 else ""
        if absolute_value >= TRILLION:
            formatted_value = f"{absolute_value / TRILLION:,.2f} tri"
        elif absolute_value >= BILLION:
            formatted_value = f"{absolute_value / BILLION:,.2f} bi"
        elif absolute_value >= MILLION:
            formatted_value = f"{absolute_value / MILLION:,.2f} mi"
        else:
            formatted_value = f"{absolute_value:,.{decimal_places}f}"
        return (
            f"{sign}{prefix}{formatted_value}".replace(",", "X").replace(".", ",").replace("X", ".")
        )

    @staticmethod
    def format_month_year(month_str: str) -> str:
        """Converts YYYY-MM into PT-BR display month (ex: Jan/2021)."""
        if len(month_str) < 7:
            return month_str
        yr = month_str[:4]
        m_num = month_str[5:7]
        m_pt = MONTHS_PT.get(m_num, m_num)
        return f"{m_pt}/{yr}"

    @staticmethod
    def get_colored_cell_style(price: float, ceiling: float) -> str:
        """Returns the CSS style string for cell coloring based on the Bazin Price-to-Ceiling ratio."""
        if ceiling <= 0:
            bg_color = "transparent"
        elif price <= (ceiling * 0.8):
            bg_color = "rgba(40, 167, 69, 0.25)"
        elif price <= ceiling:
            bg_color = "rgba(255, 193, 7, 0.25)"
        else:
            bg_color = "rgba(220, 53, 69, 0.25)"
        return f"background-color: {bg_color}; font-weight: bold; border-radius: 4px;"

    @staticmethod
    def get_trend_cell_style(value: float) -> str:
        """Returns the CSS style string for cell coloring based on positive, negative, or neutral trends."""
        if value > 0:
            bg_color = "rgba(40, 167, 69, 0.25)"
        elif value < 0:
            bg_color = "rgba(220, 53, 69, 0.25)"
        else:
            bg_color = "transparent"
        return f"background-color: {bg_color}; font-weight: bold; border-radius: 4px;"

from core.constants import MONTHS_PT


class Formatter:
    """Utility class for visual data and currency formatting."""

    @staticmethod
    def format_currency(value: float) -> str:
        """Formats a float to the Brazilian currency string (R$ 1.234,56)."""
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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

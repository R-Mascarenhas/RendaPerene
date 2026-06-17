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

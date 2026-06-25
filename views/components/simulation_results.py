import streamlit as st

from core.utils import Formatter
from core.strings import MSG_SIMULATION_RESULTS_TITLE
from core.constants import (
    SIM_TARGET_MONTHLY_INCOME, SIM_TARGET_EQUITY, SIM_REQUIRED_CONTRIBUTION,
    SIM_UPDATED_CONTRIBUTION, SIM_TOTAL_INVESTED
)

class SimulationResultsWidget:
    """Displays the planning simulation metric cards (PMT outputs)."""

    def render(self, sim, show_updated=True):
        st.subheader(MSG_SIMULATION_RESULTS_TITLE)
        if show_updated:
            res_col1, res_col2, res_col3, res_col4 = st.columns(4)
            res_col1.metric("Renda Mensal Alvo", Formatter.format_currency(sim[SIM_TARGET_MONTHLY_INCOME]))
            res_col2.metric("Meta de Patrimônio (Viver de Juros)", Formatter.format_currency(sim[SIM_TARGET_EQUITY]))
            res_col3.metric("Aporte Mensal Necessário", Formatter.format_currency(sim[SIM_REQUIRED_CONTRIBUTION]))
            res_col4.metric("Aporte Mensal Atualizado", Formatter.format_currency(sim[SIM_UPDATED_CONTRIBUTION]),
                            help = f"Baseado no valor que já foi investido até o momento (R$ {sim[SIM_TOTAL_INVESTED]:,.2f})")
        else:
            res_col1, res_col2, res_col3 = st.columns(3)
            res_col1.metric("Renda Mensal Alvo", Formatter.format_currency(sim[SIM_TARGET_MONTHLY_INCOME]))
            res_col2.metric("Meta de Patrimônio (Viver de Juros)", Formatter.format_currency(sim[SIM_TARGET_EQUITY]))
            res_col3.metric("Aporte Mensal Necessário", Formatter.format_currency(sim[SIM_REQUIRED_CONTRIBUTION]))

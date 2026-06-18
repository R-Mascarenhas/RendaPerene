import streamlit as st
from core.utils import Formatter

class SimulationResultsWidget:
    """Displays the 4 planning simulation metric cards (PMT outputs)."""

    def render(self, sim):
        st.subheader("🎯 Resultados da Simulação")
        res_col1, res_col2, res_col3, res_col4 = st.columns(4)
        res_col1.metric("Renda Mensal Alvo", Formatter.format_currency(sim["target_monthly_income"]))
        res_col2.metric("Meta de Patrimônio (Viver de Juros)", Formatter.format_currency(sim["target_equity"]))
        res_col3.metric("Aporte Mensal Necessário", Formatter.format_currency(sim["required_monthly_contribution"]))
        res_col4.metric("Aporte Mensal Atualizado", Formatter.format_currency(sim["updated_monthly_contribution"]),
                        help = f"Baseado no valor que já foi investido até o momento (R$ {sim['total_invested']:,.2f})")

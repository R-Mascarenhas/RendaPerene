import streamlit as st

class TimeMetricsWidget:
    """Displays total and remaining investment timelines."""

    def render(self, sim):
        st.subheader("⏳ Prazos de Investimentos")
        col_t1, col_t2 = st.columns(2)

        total_time_months = sim["total_time_months"]
        total_time_years = total_time_months // 12
        total_time_months_leftover = total_time_months % 12
        
        remaining_time_months = sim["remaining_time_months"]
        remaining_time_years = remaining_time_months // 12
        remaining_months_leftover = remaining_time_months % 12
        
        start_age_years = int(sim["start_age_years"])
        current_age_years = int(sim["current_age"])

        col_t1.metric("Tempo Total de Investimento", f"{total_time_years} Anos e {total_time_months_leftover} meses ({total_time_months} meses)", f"Planejamento iniciado aos {start_age_years} anos")
        col_t2.metric("Tempo Restante de Aporte", f"{remaining_time_years} Anos e {remaining_months_leftover} meses ({remaining_time_months} meses)", f"Sua idade atual hoje: {current_age_years} anos")

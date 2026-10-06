"""Presentation-only polling; background workers never interact with Streamlit."""

import streamlit as st

from views.cached_market_data import get_market_data_observer


@st.fragment(run_every=2)
def render_market_data_status() -> None:
    poll = get_market_data_observer().poll()
    if poll.changed:
        st.rerun(scope="app")

    updating = sum(status.updating for status in poll.statuses)
    missing = sum(not status.available for status in poll.statuses)
    stale = sum(status.stale for status in poll.statuses)
    failed = any(status.failed for status in poll.statuses)
    if updating:
        st.caption(
            "Atualizando dados de mercado em segundo plano. A carteira local está disponível."
        )
    if missing:
        st.caption(
            "Há dados de mercado indisponíveis. Campos dependentes deles mostram N/D; "
            "indicadores econômicos sem resposta usam referências provisórias."
        )
    if stale:
        st.caption("Dados de mercado desatualizados. O último dado válido foi preservado.")
    if failed:
        st.caption(
            "Não foi possível atualizar os dados de mercado. A carteira local continua disponível."
        )
    ages = [status.age_seconds for status in poll.statuses if status.age_seconds is not None]
    if ages:
        st.caption(f"Idade do dado de mercado mais antigo nesta tela: {int(max(ages) // 60)} min.")

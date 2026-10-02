"""Presentation-only polling; background workers never interact with Streamlit."""

import streamlit as st

from views.cached_market_data import StreamlitCachedMarketData


@st.fragment(run_every=2)
def render_market_data_status() -> None:
    requests = st.session_state.get("market_data_requests", {})
    if not requests:
        return
    StreamlitCachedMarketData.retry_due(set(requests))
    statuses = [(key, StreamlitCachedMarketData.status(key)) for key in requests]
    poll_ready = st.session_state.get("market_data_poll_ready", False)
    st.session_state["market_data_poll_ready"] = True
    changed = [(key, status) for key, status in statuses if status.revision != requests[key]]
    if poll_ready and changed:
        for key, status in changed:
            requests[key] = status.revision
        st.rerun(scope="app")

    updating = sum(status.updating for _, status in statuses)
    missing = sum(not status.available for _, status in statuses)
    stale = sum(status.stale for _, status in statuses)
    failed = any(status.failed for _, status in statuses)
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
    ages = [status.age_seconds for _, status in statuses if status.age_seconds is not None]
    if ages:
        st.caption(f"Idade do dado de mercado mais antigo nesta tela: {int(max(ages) // 60)} min.")

"""Confirmation UI for remote suggestions; portfolio writes stay in AssetService."""

import datetime
import hashlib
import logging

import pandas as pd
import streamlit as st

from core.dividends import DividendPayment
from core.utils.formatter import Formatter
from services.assets_service import AssetService
from views.cached_market_data import market_data_portfolio_context
from views.components.goal_editor_state import invalidate_goal_editor_state

logger = logging.getLogger(__name__)
_KINDS = {"DIVIDEND": "Dividendo", "JCP": "JCP", "YIELD": "Rendimento"}


class DividendSyncWidget:
    def render(self, ticker=None):
        search_session = st.session_state["dividend_search_session"]
        state = search_session.poll(ticker)
        prefix = state.key
        result = state.result
        if state.searching:
            st.caption("Verificando novos proventos em segundo plano...")

            @st.fragment(run_every=1)
            def await_dividend_search():
                current = search_session.poll(ticker)
                if current.key != state.key or not current.searching:
                    st.rerun()

            await_dividend_search()
        pending = result and result["suggestions"]
        if pending:
            tickers = sorted({item["event"].ticker for item in pending})
            st.warning(
                "Foram encontrados proventos para "
                + ", ".join(tickers)
                + ". Confira os valores e informe as datas de pagamento abaixo."
            )
        if result and result["changed"]:
            st.info(
                "O Yahoo alterou valores de eventos já revisados de "
                + ", ".join(result["changed"])
                + ". Seus pagamentos confirmados foram preservados."
            )
        if state.failed:
            st.warning(
                "Não foi possível verificar novos proventos. A carteira continua disponível. "
                "Tente novamente em Buscar proventos no Yahoo Finance."
            )
        if result and result["unavailable"]:
            st.warning(
                "Yahoo Finance indisponível para: "
                + ", ".join(result["unavailable"])
                + ". Você pode continuar usando a carteira offline."
            )
        if not pending and st.button("Buscar proventos no Yahoo Finance", key=prefix + "retry"):
            search_session.poll(ticker, retry=True)
            st.rerun()
        if pending:
            with st.expander("Detectar proventos e informar pagamentos", expanded=bool(pending)):
                st.caption(
                    "Consulte possíveis proventos no Yahoo Finance e confirme os pagamentos antes de "
                    "salvar. A data-ex identifica o evento; ela não é a data do pagamento."
                )
                if st.button("Buscar proventos no Yahoo Finance", key=prefix + "search"):
                    search_session.poll(ticker, retry=True)
                    st.rerun()
                suggestions = result["suggestions"]
                if not suggestions:
                    st.info("Nenhum novo provento disponível para revisão.")
                    return
                selected = st.selectbox(
                    "Provento para revisar",
                    range(len(suggestions)),
                    key=prefix + "event",
                    format_func=lambda index: (
                        f"{suggestions[index]['event'].ticker} · "
                        f"data-ex {suggestions[index]['event'].ex_date} · "
                        f"{Formatter.format_currency(suggestions[index]['event'].unit_value, decimal_places=8)} por ação"
                    ),
                )
                suggestion = suggestions[selected]
                event = suggestion["event"]
                form_key = f"{prefix}{result['revision']}_review_{selected}_"
                st.info(
                    f"Foi identificado um possível provento de {event.ticker} no valor de "
                    f"{Formatter.format_currency(event.unit_value, decimal_places=8)} por ação. "
                    "Confirme o tipo e informe a data de pagamento."
                )
                st.caption(
                    "O Yahoo não distingue JCP de dividendos. Confira a quantidade remunerada e os "
                    "valores líquidos. A quantidade sugerida é histórica e pode exigir correção."
                )
                count = st.number_input(
                    "Número de parcelas",
                    min_value=1,
                    max_value=12,
                    value=1,
                    key=form_key + "count",
                )
                with st.form(form_key + f"payments_{count}"):
                    kind = st.selectbox(
                        "Tipo do provento",
                        list(_KINDS),
                        index=None,
                        format_func=_KINDS.get,
                        key=form_key + "kind",
                    )
                    payments = []
                    for index in range(count):
                        st.markdown(f"**Parcela {index + 1}**")
                        date = st.date_input(
                            "Data de pagamento",
                            value=None,
                            format="DD/MM/YYYY",
                            min_value=datetime.date(1900, 1, 1),
                            max_value=datetime.date.max,
                            key=form_key + f"{index}_date",
                        )
                        quantity = st.number_input(
                            "Quantidade remunerada",
                            min_value=0,
                            value=suggestion["quantity"],
                            key=form_key + f"{index}_quantity",
                        )
                        unit_value = st.number_input(
                            "Valor por ação da parcela (R$)",
                            min_value=0.0,
                            value=float(event.unit_value / count),
                            format="%.8f",
                            key=form_key + f"{index}_value_{count}",
                        )
                        existing = suggestion["existing"]
                        chosen = None
                        if existing:
                            chosen = st.selectbox(
                                "Este pagamento já está cadastrado?",
                                ["new", *[row["id"] for row in existing]],
                                index=None,
                                placeholder="Confira para evitar duplicidade",
                                key=form_key + f"{index}_existing",
                                format_func=lambda item, existing=existing: (
                                    "Cadastrar novo pagamento"
                                    if item == "new"
                                    else self._payment_label(
                                        next(row for row in existing if row["id"] == item)
                                    )
                                ),
                            )
                        payments.append((date, quantity, unit_value, chosen))
                    submitted = st.form_submit_button("Revisar parcelas")
                if submitted:
                    try:
                        if suggestion["existing"] and any(row[3] is None for row in payments):
                            raise ValueError("Confira se cada parcela já está cadastrada.")
                        values = [
                            DividendPayment(
                                date.isoformat() if date else "",
                                quantity,
                                unit_value,
                                chosen if isinstance(chosen, int) else None,
                            )
                            for date, quantity, unit_value, chosen in payments
                        ]
                        rows = AssetService.prepare_dividend_payments(event, kind, values)
                        search_session.draft = {
                            "event": event,
                            "kind": kind,
                            "payments": values,
                            "rows": rows,
                            "selected": selected,
                            "count": count,
                        }
                    except ValueError as error:
                        search_session.draft = None
                        st.error(str(error))
                draft = search_session.draft
                if draft and (draft["selected"] != selected or draft["count"] != count):
                    search_session.draft = None
                    draft = None
                if draft:
                    st.write("Confira os pagamentos antes de confirmar:")
                    display = []
                    for row in draft["rows"]:
                        existing = next(
                            (
                                item
                                for item in suggestion["existing"]
                                if item["id"] == row["existing_id"]
                            ),
                            None,
                        )
                        display.append(
                            {
                                "Data de pagamento": existing["date"] if existing else row["date"],
                                "Tipo": _KINDS[draft["kind"]],
                                "Quantidade": existing["quantity"] if existing else row["quantity"],
                                "Total": Formatter.format_currency(
                                    existing["total_value"] if existing else row["total_value"]
                                ),
                                "Ação": "Associar sem alterar"
                                if existing
                                else "Cadastrar pagamento",
                            }
                        )
                    st.dataframe(pd.DataFrame(display), hide_index=True, width="stretch")
                    st.caption(
                        "Datas futuras aparecem como a receber. Na data informada, o lançamento "
                        "passa automaticamente a recebido; ajuste a data se houver adiamento. "
                        "Pagamentos associados mantêm os valores já cadastrados."
                    )
                    if st.button("Confirmar e salvar pagamentos", key=form_key + "confirm"):
                        self._save(
                            lambda: AssetService.confirm_dividend(
                                draft["event"],
                                draft["kind"],
                                draft["payments"],
                                result["revision"],
                            ),
                        )
                if st.button("Ignorar este evento", key=form_key + "ignore"):
                    self._save(lambda: AssetService.ignore_dividend(event, result["revision"]))

    @staticmethod
    def _payment_label(row):
        return (
            f"{row['date']} · {_KINDS.get(row['dividend_type'], row['dividend_type'])} · "
            f"{Formatter.format_currency(row['total_value'])}"
        )

    @staticmethod
    def _render_reschedule(ticker, prefix):
        expander = st.expander(
            "Ajustar data de pagamento de provento cadastrado",
            key=prefix + "reschedule_expander",
            on_change="rerun",
        )
        if not expander.open:
            return
        with expander:
            try:
                payments = AssetService.get_dividend_payments(ticker)
                revision = AssetService.get_local_projection_revision()
            except Exception:
                logger.warning("dividends.payment_read_failed")
                st.error("Não foi possível carregar os proventos cadastrados.")
                return
            if not payments:
                st.info("Nenhum provento cadastrado.")
                return
            by_id = {row["id"]: row for row in payments}
            selected = st.selectbox(
                "Provento cadastrado",
                list(by_id),
                key=prefix + "reschedule_payment",
                format_func=lambda value: (
                    f"{by_id[value]['ticker']} · " + DividendSyncWidget._payment_label(by_id[value])
                ),
            )
            with st.form(prefix + f"reschedule_{selected}_{revision}"):
                date = st.date_input(
                    "Nova data de pagamento",
                    value=datetime.date.fromisoformat(by_id[selected]["date"]),
                    format="DD/MM/YYYY",
                    min_value=datetime.date(1900, 1, 1),
                    max_value=datetime.date.max,
                )
                st.caption("O ajuste mantém o valor e a quantidade já cadastrados.")
                submitted = st.form_submit_button("Confirmar nova data")
            if submitted:
                DividendSyncWidget._save(
                    lambda: AssetService.reschedule_dividend(
                        selected,
                        date.isoformat(),
                        revision,
                    ),
                )

    def render_reschedule(self):
        context = market_data_portfolio_context()
        identity = hashlib.sha256(repr(context).encode()).hexdigest()[:16]
        self._render_reschedule(None, f"dividend_reschedule_{identity}_")

    @staticmethod
    def _save(action):
        try:
            changed = action()
        except ValueError as error:
            st.error(str(error))
        except Exception:
            logger.warning("dividends.confirm_failed")
            st.error("Não foi possível salvar os pagamentos. Tente novamente.")
        else:
            search_session = st.session_state.get("dividend_search_session")
            if search_session is not None:
                search_session.invalidate()
            invalidate_goal_editor_state()
            st.toast("Revisão salva." if changed else "Este evento já foi revisado.")
            st.rerun()

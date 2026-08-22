import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.constants import (
    SESSION_BAZIN_TARGET_SPREAD,
    SESSION_BAZIN_TARGET_YIELD,
    SESSION_CEILING_MODEL_SELECTION,
)
from core.strings import (
    MODEL_CLASSIC,
    MODEL_IPCA_SPREAD,
    MODEL_SELIC,
    MSG_ASSET_ADD_ERROR,
    MSG_ASSET_ADDED_SUCCESS,
    MSG_ASSET_DEEP_DIVE_DESC,
    MSG_ASSET_DEEP_DIVE_NO_DATA,
    MSG_ASSET_DEEP_DIVE_PRICE_HISTORY,
    MSG_ASSET_DEEP_DIVE_TITLE,
    MSG_ASSET_FAVORITE,
    MSG_ASSET_FAVORITED,
    MSG_ASSET_REMOVED_SUCCESS,
    MSG_ASSET_UNFAVORITE,
)
from core.utils import Formatter
from core.utils.dividend_events import build_dividend_event_heatmap, get_recent_dividend_payments
from core.utils.market_history import get_valid_closing_history
from services.assets_service import AssetService
from services.valuation_service import ValuationService
from views.cached_market_data import StreamlitCachedMarketData as MarketData
from views.components.chart_theme import ChartThemeAdapter


class AssetDeepDiveView:
    """Render the catalog-wide Raio-X market analysis tab."""

    def render(self):
        """Render the Raio-X tab."""
        self._render_asset_deep_dive()

    def _render_asset_deep_dive(self):
        """Render a cached, catalog-wide market analysis for an individual asset."""
        st.subheader(MSG_ASSET_DEEP_DIVE_TITLE)
        st.write(MSG_ASSET_DEEP_DIVE_DESC)

        catalog = MarketData.load_assets_catalog()
        if catalog.empty:
            st.warning("O catálogo de ativos não está disponível no momento.")
            return
        catalog = catalog.loc[~catalog.index.duplicated(keep="first")]

        options = [f"{ticker} - {catalog.loc[ticker, 'NOME']}" for ticker in sorted(catalog.index)]
        selection = st.selectbox(
            "Pesquisar ativo",
            options=options,
            index=None,
            placeholder="Digite o ticker ou o nome da empresa",
            key="asset_deep_dive_ticker",
        )
        if not selection:
            st.info("Selecione um ativo para visualizar sua ficha detalhada.")
            return

        ticker = selection.split(" - ", maxsplit=1)[0]
        target_yield = self._get_current_target_yield()
        with st.spinner("Buscando indicadores e histórico de proventos..."):
            details = AssetService.get_asset_market_analysis(ticker, target_yield)

        if not details or float(details.get("current_price", 0.0) or 0.0) <= 0:
            st.warning(MSG_ASSET_DEEP_DIVE_NO_DATA)
            return

        metadata = details["metadata"]
        st.markdown(f"### {ticker} — {details.get('name') or metadata['name']}")
        if metadata["sector"]:
            st.caption(f"Setor: {metadata['sector']}")
        self._render_favorite_button(ticker)
        self._render_asset_price_history(ticker)
        self._render_quote_snapshot(details.get("quote_snapshot", {}))

        current_price = float(details.get("current_price", 0.0) or 0.0)
        ceiling_price = float(details.get("ceiling_price", 0.0) or 0.0)
        has_bazin_ceiling = ceiling_price > 0
        margin = ((ceiling_price / current_price) - 1) * 100 if has_bazin_ceiling else None

        st.subheader("Análise de dividendos e valuation")
        dividend_columns = st.columns(4)
        dividend_columns[0].metric("Cotação Atual", Formatter.format_currency(current_price))
        dividend_columns[1].metric(
            "Preço Teto de Bazin",
            Formatter.format_currency(ceiling_price) if has_bazin_ceiling else "N/D",
        )
        dividend_columns[2].metric(
            "Margem de Segurança",
            f"{margin:.2f}%" if margin is not None else "N/D",
            delta=f"{margin:+.2f}%" if margin is not None else None,
            delta_color="normal",
        )
        dividend_columns[3].metric(
            "Dividend Yield Médio (5 anos)", f"{details.get('avg_dy_5y', 0.0):.2f}%"
        )

        valuation_columns = st.columns(4)
        valuation_columns[0].metric(
            "P/L", Formatter.format_market_value(details.get("pe"), "number")
        )
        valuation_columns[1].metric(
            "P/VP", Formatter.format_market_value(details.get("pb"), "number")
        )
        valuation_columns[2].metric(
            "ROE", Formatter.format_market_value(details.get("roe"), "percentage_points")
        )
        valuation_columns[3].metric(
            "Margem Líquida",
            Formatter.format_market_value(details.get("net_margin"), "percentage_points"),
        )

        self._render_dividend_event_map(details.get("dividend_events", []))
        self._render_dividend_history(details, current_price, target_yield)
        self._render_market_indicators(details.get("indicators", {}))

    @staticmethod
    def _render_quote_snapshot(snapshot: dict):
        """Render the Yahoo Finance quote snapshot, preserving unavailable fields as N/D."""
        st.subheader("Cotação")
        st.caption("Dados fornecidos pelo Yahoo Finance.")
        metrics = [
            ("Cotação atual", "closing_price", "currency"),
            ("Abertura hoje", "opening_price", "currency"),
            ("Máxima hoje", "day_high", "currency"),
            ("Mínima hoje", "day_low", "currency"),
            ("Máxima em 52 semanas", "high_52w", "currency"),
            ("Mínima em 52 semanas", "low_52w", "currency"),
            ("Cap. de mercado", "market_cap", "currency"),
            ("Ações emitidas", "shares_outstanding", "integer"),
            ("Volume financeiro diário", "daily_financial_volume", "currency"),
            ("Ações negociadas", "daily_volume", "integer"),
        ]
        for start in range(0, len(metrics), 4):
            columns = st.columns(4)
            for column, (label, key, value_type) in zip(
                columns, metrics[start : start + 4], strict=False
            ):
                column.metric(label, Formatter.format_market_value(snapshot.get(key), value_type))

    @staticmethod
    def _render_dividend_history(details: dict, current_price: float, target_yield: float):
        """Render Yahoo payment history, annual chart, and annual dividend-yield table."""
        st.subheader("Proventos")
        dividend_history = details.get("dividends_history", {})
        dividend_events = details.get("dividend_events", [])
        history_column, table_column = st.columns(2)

        with history_column:
            if any(dividend_history.values()):
                years = sorted(dividend_history)
                values = [dividend_history[year] for year in years]
                required_dividend = ValuationService.calculate_required_dividend(
                    current_price, target_yield
                )
                figure = go.Figure(
                    go.Bar(
                        x=years,
                        y=values,
                        name="Proventos por ação",
                        marker_color=ChartThemeAdapter.GREEN,
                        hovertemplate="%{x}: R$ %{y:.2f}<extra></extra>",
                    )
                )
                figure.add_hline(
                    y=required_dividend,
                    line_dash="dash",
                    line_color=ChartThemeAdapter.ORANGE,
                    annotation_text=(
                        f"Mínimo para {target_yield:.2f}%: "
                        f"{Formatter.format_currency(required_dividend)}"
                    ),
                    annotation_position="top left",
                )
                figure.update_layout(
                    title="Histórico anual de proventos",
                    xaxis_title="Ano",
                    yaxis_title="Proventos por ação",
                )
                figure.update_yaxes(tickformat=ChartThemeAdapter.CURRENCY_TICK_FORMAT)
                st.plotly_chart(ChartThemeAdapter.apply_theme(figure), width="stretch")
            else:
                st.info("O Yahoo Finance não possui histórico de proventos para este ativo.")

        with table_column:
            st.markdown("##### Histórico anual")
            annual_rows = [
                {
                    "Ano": year,
                    "Valor por ação": Formatter.format_currency(value),
                    "DY sobre cotação atual": (
                        f"{(value / current_price) * 100:.2f}%" if current_price else "N/D"
                    ),
                }
                for year, value in sorted(dividend_history.items(), reverse=True)
            ]
            st.dataframe(pd.DataFrame(annual_rows), hide_index=True, width="stretch")
            st.markdown("##### Últimos eventos")
            recent_payments = get_recent_dividend_payments(dividend_events)
            payment_rows = [
                {
                    "Data do evento": payment["date"].strftime("%d/%m/%Y"),
                    "Tipo": "Provento",
                    "Valor por ação": Formatter.format_currency(payment["value"]),
                }
                for payment in recent_payments
            ]
            if payment_rows:
                st.dataframe(pd.DataFrame(payment_rows), hide_index=True, width="stretch")
            else:
                st.caption("Nenhum evento de provento disponível no Yahoo Finance.")

    @staticmethod
    def _render_market_indicators(indicators: dict):
        """Render all Yahoo Finance fundamental indicators in AGF-like categories."""
        st.subheader("Indicadores")
        st.caption("Campos não disponibilizados pelo Yahoo Finance são exibidos como N/D.")
        groups = [
            (
                "Indicadores de avaliação",
                [
                    ("P/L", "trailing_pe", "number"),
                    ("P/L projetado", "forward_pe", "number"),
                    ("P/VP", "price_to_book", "number"),
                    ("P/Vendas", "price_to_sales", "number"),
                    ("EV/EBITDA", "enterprise_to_ebitda", "number"),
                    ("EV/Receita", "enterprise_to_revenue", "number"),
                ],
            ),
            (
                "Indicadores de caixa e endividamento",
                [
                    ("Caixa total", "total_cash", "currency"),
                    ("Dívida total", "total_debt", "currency"),
                    ("Dívida/Patrimônio", "debt_to_equity", "percentage_points"),
                    ("Liquidez corrente", "current_ratio", "number"),
                    ("Liquidez seca", "quick_ratio", "number"),
                    ("Fluxo de caixa operacional", "operating_cashflow", "currency"),
                    ("Fluxo de caixa livre", "free_cashflow", "currency"),
                ],
            ),
            (
                "Indicadores de rentabilidade",
                [
                    ("ROA", "return_on_assets", "percentage"),
                    ("ROE", "return_on_equity", "percentage"),
                    ("Margem bruta", "gross_margins", "percentage"),
                    ("Margem operacional", "operating_margins", "percentage"),
                    ("Margem líquida", "profit_margins", "percentage"),
                ],
            ),
            ("Indicadores de eficiência", [("Receita por ação", "revenue_per_share", "currency")]),
            (
                "Indicadores de crescimento",
                [
                    ("Crescimento da receita", "revenue_growth", "percentage"),
                    ("Crescimento dos lucros", "earnings_growth", "percentage"),
                    (
                        "Crescimento trimestral dos lucros",
                        "earnings_quarterly_growth",
                        "percentage",
                    ),
                ],
            ),
            (
                "Indicadores de dividendos",
                [
                    ("Dividendo anual", "dividend_rate", "currency"),
                    ("Dividend yield", "dividend_yield", "percentage_points"),
                    ("Payout", "payout_ratio", "percentage"),
                    ("DY médio de 5 anos", "five_year_avg_dividend_yield", "percentage_points"),
                ],
            ),
            (
                "Indicadores de valores e volumes",
                [
                    ("Volume", "volume", "integer"),
                    ("Volume médio", "average_volume", "integer"),
                    ("Volume médio de 10 dias", "average_volume_10d", "integer"),
                    ("Beta", "beta", "number"),
                ],
            ),
            (
                "Indicadores de retorno de mercado",
                [
                    ("Variação em 52 semanas", "fifty_two_week_change", "percentage"),
                    (
                        "Variação do benchmark em 52 semanas",
                        "benchmark_fifty_two_week_change",
                        "percentage",
                    ),
                ],
            ),
        ]
        columns = st.columns(2)
        for index, (title, fields) in enumerate(groups):
            with columns[index % 2], st.expander(title):
                rows = [
                    {
                        "Indicador": label,
                        "Valor": Formatter.format_market_value(indicators.get(key), value_type),
                    }
                    for label, key, value_type in fields
                ]
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    @staticmethod
    def _render_dividend_event_map(dividend_events: list[dict]):
        """Render a ten-year month map from Yahoo Finance dividend event dates."""
        st.subheader("🗓️ Mapa de calor dos proventos")
        st.caption(
            "Base: data do evento retornada pelo Yahoo Finance. O resumo mostra em quantos dos "
            "últimos 11 anos cada mês teve ao menos um evento."
        )
        if not dividend_events:
            st.info("O Yahoo Finance não possui eventos de proventos para este ativo.")
            return

        month_labels = [
            "JAN",
            "FEV",
            "MAR",
            "ABR",
            "MAI",
            "JUN",
            "JUL",
            "AGO",
            "SET",
            "OUT",
            "NOV",
            "DEZ",
        ]
        heatmap_data = build_dividend_event_heatmap(dividend_events, datetime.date.today().year)
        years = heatmap_data["years"]
        recurrence = heatmap_data["recurrence"]
        event_rows = [heatmap_data["events_by_year"][year] for year in years]
        event_details_by_year = heatmap_data["event_details_by_year"]
        event_presence_rows = [[int(count > 0) for count in event_row] for event_row in event_rows]
        heatmap_values = [recurrence] + event_presence_rows
        summary_text = [
            f"{count}<br>{count / len(years):.0%}" if count else "—" for count in recurrence
        ]
        heatmap_text = [summary_text] + [
            ["✓" if count else "" for count in event_row] for event_row in event_presence_rows
        ]
        hover_descriptions = [
            [
                f"{count} de {len(years)} anos com ao menos um evento de provento"
                for count in recurrence
            ]
        ] + [
            [
                AssetDeepDiveView._format_dividend_event_hover(event_details_by_year[year][month])
                for month in range(12)
            ]
            for year in years
        ]
        figure = go.Figure(
            go.Heatmap(
                x=month_labels,
                y=["Resumo"] + [str(year) for year in years],
                z=heatmap_values,
                colorscale=[
                    [0, ChartThemeAdapter.heatmap_empty_color()],
                    [0.35, "#9dd9b5"],
                    [1, ChartThemeAdapter.GREEN],
                ],
                showscale=False,
                text=heatmap_text,
                customdata=hover_descriptions,
                texttemplate="%{text}",
                hovertemplate="<b>%{y} · %{x}</b><br>%{customdata}<extra></extra>",
            )
        )
        figure.update_layout(
            height=520,
            margin={"l": 75, "r": 20, "t": 20, "b": 45},
            yaxis={"autorange": "reversed"},
        )
        figure.update_xaxes(side="top")
        st.plotly_chart(ChartThemeAdapter.apply_theme(figure), width="stretch")

    @staticmethod
    def _format_dividend_event_hover(events: list[dict]) -> str:
        """Format Yahoo Finance dividend event details for a heatmap hover label."""
        if not events:
            return "Nenhum evento de provento registrado pelo Yahoo Finance"

        total_value = sum(float(event["value"]) for event in events)
        return f"Total de proventos no mês: {Formatter.format_currency(total_value)} por ação"

    @staticmethod
    def _render_favorite_button(ticker: str):
        """Add a Raio-X asset to the persistent manual market watchlist."""
        monitored_tickers = set(AssetService.get_tracked_market_assets())
        manually_favorited_tickers = set(
            AssetService.get_tracked_market_assets(include_owned=False)
        )
        is_monitored = ticker in monitored_tickers
        is_manually_favorited = ticker in manually_favorited_tickers
        is_owned = is_monitored and not is_manually_favorited

        if is_owned:
            st.button(
                MSG_ASSET_FAVORITED,
                key=f"asset_deep_dive_favorite_{ticker}",
                disabled=True,
                help="Este ativo é monitorado automaticamente porque está na sua carteira.",
            )
            return

        label = MSG_ASSET_UNFAVORITE if is_manually_favorited else MSG_ASSET_FAVORITE
        if st.button(
            label,
            key=f"asset_deep_dive_favorite_{ticker}",
            help="Ativos favoritados aparecem no Monitoramento Geral.",
        ):
            if is_manually_favorited and AssetService.remove_tracked_market_asset(ticker):
                st.success(MSG_ASSET_REMOVED_SUCCESS.format(ticker=ticker))
                st.rerun()
            elif not is_manually_favorited and AssetService.add_tracked_market_asset(ticker):
                st.success(MSG_ASSET_ADDED_SUCCESS.format(ticker=ticker))
                st.rerun()
            else:
                st.error(MSG_ASSET_ADD_ERROR.format(ticker=ticker))

    @staticmethod
    def _render_asset_price_history(ticker: str):
        """Render cached Yahoo Finance closing-price history for the selected ticker."""
        st.subheader(MSG_ASSET_DEEP_DIVE_PRICE_HISTORY)
        period_map = {
            "1 Dia": "1d",
            "5 Dias": "5d",
            "1 Mês": "1mo",
            "6 Meses": "6mo",
            "No Ano": "ytd",
            "1 Ano": "1y",
            "5 Anos": "5y",
            "Máximo": "max",
        }
        interval_map = {
            "1d": "5m",
            "5d": "30m",
            "1mo": "1d",
            "6mo": "1d",
            "ytd": "1d",
            "1y": "1d",
            "5y": "1wk",
            "max": "1wk",
        }
        selected_label = st.radio(
            "Selecione o período do histórico de fechamento",
            options=list(period_map),
            index=5,
            horizontal=True,
            key=f"asset_deep_dive_period_{ticker}",
            label_visibility="collapsed",
        )
        period = period_map[selected_label]
        with st.spinner(f"Buscando histórico ({selected_label}) para {ticker}..."):
            history = MarketData.get_ticker_history(
                ticker, period=period, interval=interval_map[period]
            )

        if history.empty or "Close" not in history.columns:
            st.info("Dados gráficos de cotações não disponíveis para este ativo no Yahoo Finance.")
            return

        history = get_valid_closing_history(history)
        if history.empty:
            st.info("Dados gráficos de cotações não disponíveis para este ativo no Yahoo Finance.")
            return

        price_current = float(history["Close"].iloc[-1])
        price_initial = float(history["Close"].iloc[0])
        change_pct = ((price_current / price_initial) - 1) * 100 if price_initial else 0.0
        st.metric(
            "Cotação no período", Formatter.format_currency(price_current), f"{change_pct:.2f}%"
        )

        date_format = "%d/%m %H:%M" if period in {"1d", "5d"} else "%d/%m/%Y"
        figure = go.Figure(
            go.Scatter(
                x=history.index.strftime(date_format),
                y=history["Close"],
                name="Preço de Fechamento",
                mode="lines",
                line={"color": ChartThemeAdapter.GREEN, "width": 2.5},
                hovertemplate="Fechamento: R$ %{y:,.2f}<extra></extra>",
            )
        )
        figure.update_layout(title="Evolução da cotação", yaxis_title="Cotação")
        figure.update_xaxes(type="category", tickangle=-45, nticks=8)
        figure.update_yaxes(tickformat=ChartThemeAdapter.CURRENCY_TICK_FORMAT)
        st.plotly_chart(ChartThemeAdapter.apply_theme(figure), width="stretch")

    @staticmethod
    def _get_current_target_yield() -> float:
        """Resolve the active Bazin target without duplicating the valuation formula."""
        model = st.session_state.get(SESSION_CEILING_MODEL_SELECTION, MODEL_CLASSIC)
        if model == MODEL_SELIC:
            return ValuationService.calculate_target_yield(
                model, selic_rate=MarketData.get_current_selic()
            )
        if model == MODEL_IPCA_SPREAD:
            return ValuationService.calculate_target_yield(
                model,
                ipca_rate=MarketData.get_current_ipca_l12m(),
                target_spread=st.session_state.get(SESSION_BAZIN_TARGET_SPREAD, 3.0),
            )
        return ValuationService.calculate_target_yield(
            model,
            classic_target_yield=st.session_state.get(SESSION_BAZIN_TARGET_YIELD, 6.0),
        )

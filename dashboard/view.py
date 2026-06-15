import streamlit as st
import datetime
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.service import DashboardService
from core.utils import Formatter, MarketData

class DashboardView:
    """Class responsible for rendering the Dashboard Tab GUI."""

    def render(self):
        df_positions = DashboardService.calculate_positions()
        today = datetime.date.today()
        current_year = today.year

        ytd_contributions = DashboardService.get_ytd_contributions(current_year)
        ytd_dividends = df_positions['ytd_dividends'].sum() if not df_positions.empty else 0.0

        # Pull planned contribution directly from DB configuration instead of volatile session state cache
        from planning.service import SimulationService
        config = SimulationService.get_configuration()
        if config:
            # We must calculate exact age in months to do the math
            birth_date = datetime.datetime.strptime(config['birth_date'], "%Y-%m-%d").date() if isinstance(config['birth_date'], str) else config['birth_date']
            months_age = (today.year - birth_date.year) * 12 + today.month - birth_date.month - (today.day < birth_date.day)
            
            _, _, _, _, required_monthly_contribution = SimulationService.calculate_simulation_params(
                months_age,
                config['retirement_age'],
                config['desired_income_mw'],
                config['annual_interest_rate'],
                config['mw_value'],
                config['initial_equity_input']
            )
        else:
            required_monthly_contribution = 0.0

        annual_salary_goal = required_monthly_contribution * 12
        total_annual_goal = annual_salary_goal + ytd_dividends

        self._render_annual_planning_widget(current_year, annual_salary_goal, ytd_dividends, total_annual_goal, ytd_contributions)

        st.markdown("---")
        st.header("Resumo Patrimonial")

        if df_positions.empty:
            st.info("Sua carteira está vazia. Vá até a aba 'Lançamentos & B3' para inserir seus ativos ou importar seu extrato da B3!")
        else:
            self._render_patrimony_summary(df_positions)
            self._render_historical_evolution(required_monthly_contribution)

    def _render_annual_planning_widget(self, current_year, annual_salary_goal, ytd_dividends, total_annual_goal, ytd_contributions):
        st.subheader(f"📅 Planejamento Anual de Investimentos ({current_year})")
        plan_col1, plan_col2, plan_col3 = st.columns(3)
        plan_col1.metric("Meta de Aporte do Salário (Ano)", Formatter.format_currency(annual_salary_goal), "Baseado no seu Simulador")
        plan_col2.metric("Proventos a Reinvestir (YTD)", Formatter.format_currency(ytd_dividends), "Soma dos dividendos recebidos")
        plan_col3.metric("Meta Total Corrente (Aporte + Reinvestimento)", Formatter.format_currency(total_annual_goal), "Meta de Compras na B3")

        percent_achieved = (ytd_contributions / total_annual_goal) if total_annual_goal > 0 else 0.0
        remaining_to_buy = max(0.0, total_annual_goal - ytd_contributions)

        st.markdown(f"**Total Comprado (Aportado) este ano na B3:** {Formatter.format_currency(ytd_contributions)} ({percent_achieved*100:.1f}%)")
        if remaining_to_buy > 0:
            st.markdown(f"🔴 **Falta comprar/reinvestir na B3 para bater a meta:** {Formatter.format_currency(remaining_to_buy)}")
        else:
            st.markdown("🎉 **Excelente! Todos os aportes mínimos e proventos do ano foram totalmente investidos e reinvestidos na B3!**")

        st.progress(min(1.0, percent_achieved))

    def _render_patrimony_summary(self, df_positions):
        tickers = df_positions['ticker'].tolist()
        with st.spinner("Buscando cotações em tempo real na B3..."):
            quote_map = MarketData.get_batch_quotes(tickers)

        df_positions['current_price'] = df_positions['ticker'].map(quote_map)
        df_positions['current_value'] = df_positions['quantity'] * df_positions['current_price']
        df_positions['profit_loss'] = df_positions['current_value'] - df_positions['invested_amount']

        df_positions['return_pct'] = (df_positions['profit_loss'] / df_positions['invested_amount']) * 100
        df_positions['total_yoc'] = (df_positions['total_dividends'] / df_positions['invested_amount']) * 100
        df_positions['l12m_yoc'] = (df_positions['l12m_dividends'] / df_positions['invested_amount']) * 100

        total_invested = df_positions['invested_amount'].sum()
        total_equity = df_positions['current_value'].sum()
        st.session_state.calculated_equity_cache = total_equity

        total_dividends = df_positions['total_dividends'].sum()
        l12m_dividends = df_positions['l12m_dividends'].sum()
        ytd_dividends = df_positions['ytd_dividends'].sum()

        total_profit = total_equity - total_invested
        overall_return = (total_profit / total_invested * 100) if total_invested > 0 else 0.0

        overall_yoc = (total_dividends / total_invested * 100) if total_invested > 0 else 0.0
        overall_l12m_yoc = (l12m_dividends / total_invested * 100) if total_invested > 0 else 0.0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Patrimônio Atual", Formatter.format_currency(total_equity), f"Retorno: {overall_return:+.2f}%")
        m2.metric("Proventos Totais", Formatter.format_currency(total_dividends), f"YoC Total: {overall_yoc:.2f}%")
        m3.metric("Proventos 12 Meses (L12M)", Formatter.format_currency(l12m_dividends), f"YoC L12M: {overall_l12m_yoc:.2f}%")
        m4.metric("Proventos Ano Corrente (YTD)", Formatter.format_currency(ytd_dividends))

        st.markdown("---")
        self._render_monthly_contributions_chart()
        self._render_charts(df_positions)
        self._render_detailed_table(df_positions)

    def _render_charts(self, df_positions):
        chart_col1, chart_col2, chart_col3 = st.columns(3)
        with chart_col1:
            fig_sectors = px.pie(
                df_positions,
                names="sector",
                values="current_value",
                title="Divisão do Patrimônio por Setor",
                hole=0.4
            )
            fig_sectors.update_traces(textposition='inside', textinfo='percent+label', hovertemplate="<b>%{label}</b><br>Valor: R$ %{value:,.2f} (%{percent})<extra></extra>")
            st.plotly_chart(fig_sectors, use_container_width=True)

        with chart_col2:
            df_chart_evol = df_positions[['ticker', 'invested_amount', 'current_value']].copy()
            df_chart_evol = df_chart_evol.rename(columns={'invested_amount': 'Investido', 'current_value': 'Atual'})
            df_chart_evol = df_chart_evol.sort_values(by="Investido", ascending=False)

            fig_evol = px.bar(
                df_chart_evol,
                x="ticker",
                y=["Investido", "Atual"],
                barmode="group",
                title="Evolução por ativo",
                labels={"value": "Valores (R$)", "ticker": "Ticker", "variable": "Legenda"},
                color_discrete_sequence=["#1f77b4", "#2ca02c"]
            )
            fig_evol.update_traces(hovertemplate="<b>%{x}</b><br>Valor: R$ %{y:,.2f}<extra></extra>")
            fig_evol.update_layout(yaxis_tickformat="R$ ,.2f")
            st.plotly_chart(fig_evol, use_container_width=True)

        with chart_col3:
            df_chart_prov = df_positions[df_positions["total_dividends"] > 0].sort_values(by="total_dividends", ascending=True)
            if not df_chart_prov.empty:
                fig_proventos = px.bar(
                    df_chart_prov,
                    x="total_dividends",
                    y="ticker",
                    orientation="h",
                    title="Resultado por Ativo (Proventos Recebidos)",
                    labels={"total_dividends": "Proventos (R$)", "ticker": "Ticker"},
                    color="total_dividends",
                    color_continuous_scale="Viridis" # A yellow/green scale fits dividends nicely
                )
                fig_proventos.update_traces(hovertemplate="<b>%{y}</b><br>Proventos: R$ %{x:,.2f}<extra></extra>")
                fig_proventos.update_layout(xaxis_tickformat="R$ ,.2f")
                st.plotly_chart(fig_proventos, use_container_width=True)

    def _render_detailed_table(self, df_positions):
        st.markdown("---")
        st.subheader("Ativos em Custódia (Detalhado)")

        df_display = df_positions[[
            'ticker', 'name', 'asset_type', 'sector', 'quantity',
            'average_price', 'invested_amount', 'current_price',
            'current_value', 'profit_loss', 'return_pct',
            'total_dividends', 'total_yoc',
            'l12m_dividends', 'l12m_yoc', 'ytd_dividends'
        ]].rename(columns={
            'ticker': 'Ticker', 'name': 'Nome', 'asset_type': 'Tipo', 'sector': 'Setor',
            'quantity': 'Quantidade', 'average_price': 'Preço Médio',
            'invested_amount': 'Investido (R$)', 'current_price': 'Cotação Atual',
            'current_value': 'Valor Atual (R$)', 'profit_loss': 'Lucro/Prejuízo (R$)',
            'return_pct': 'Retorno %', 'total_dividends': 'Proventos Recebidos (Total)',
            'total_yoc': 'YoC Total %', 'l12m_dividends': 'Proventos L12M',
            'l12m_yoc': 'YoC L12M %', 'ytd_dividends': 'Proventos YTD'
        })

        fmt_currency = lambda x: Formatter.format_currency(x)

        st.dataframe(df_display.style.format({
            "Preço Médio": fmt_currency,
            "Investido (R$)": fmt_currency,
            "Cotação Atual": fmt_currency,
            "Valor Atual (R$)": fmt_currency,
            "Lucro/Prejuízo (R$)": fmt_currency,
            "Retorno %": "{:+.2f}%",
            "Proventos Recebidos (Total)": fmt_currency,
            "YoC Total %": "{:.2f}%",
            "Proventos L12M": fmt_currency,
            "YoC L12M %": "{:.2f}%",
            "Proventos YTD": fmt_currency
        }), use_container_width=True, hide_index=True)

    def _render_historical_evolution(self, required_monthly_contribution):
        st.markdown("---")
        df_evolution = DashboardService.calculate_historical_evolution()
        if not df_evolution.empty:
            st.subheader("📈 Evolução Patrimonial Histórica & Planejamento")

            df_evolution = df_evolution.sort_values(by="month_str").reset_index(drop=True)
            df_evolution['display_month'] = df_evolution['month_str'].apply(Formatter.format_month_pt)

            planned_cumulative = []
            planned_dividends_cumulative = []

            prev_planned_equity = df_evolution.loc[0, 'cumulative_invested']
            prev_planned_dividends = 0.0

            monthly_interest_rate = (1 + st.session_state.annual_interest_rate / 100) ** (1 / 12) - 1
            monthly_contribution = required_monthly_contribution

            for idx, row in df_evolution.iterrows():
                if idx == 0:
                    planned_cumulative.append(prev_planned_equity)
                    planned_dividends_cumulative.append(prev_planned_dividends)
                else:
                    last_equity = planned_cumulative[-1]
                    last_dividends = planned_dividends_cumulative[-1]

                    period_interest = last_equity * monthly_interest_rate
                    next_equity = last_equity * (1 + monthly_interest_rate) + monthly_contribution
                    next_dividends = last_dividends + period_interest

                    planned_cumulative.append(next_equity)
                    planned_dividends_cumulative.append(next_dividends)

            df_evolution['planned_equity'] = planned_cumulative
            df_evolution['planned_dividends'] = planned_dividends_cumulative

            fig_multi = make_subplots(specs=[[{"secondary_y": True}]])

            fig_multi.add_trace(go.Scatter(
                x=df_evolution['display_month'], y=df_evolution['cumulative_invested'],
                name="Valor Investido", mode="lines+markers",
                line=dict(color="#1f77b4", width=3),
                marker=dict(size=6),
                hovertemplate="Valor Investido: R$ %{y:,.2f}<extra></extra>"
            ), secondary_y=False)

            fig_multi.add_trace(go.Scatter(
                x=df_evolution['display_month'], y=df_evolution['planned_equity'],
                name="Planejado (Meta)", mode="lines",
                line=dict(color="#1f77b4", width=2, dash="dash"),
                hovertemplate="Planejado (Meta): R$ %{y:,.2f}<extra></extra>"
            ), secondary_y=False)

            fig_multi.add_trace(go.Scatter(
                x=df_evolution['display_month'], y=df_evolution['cumulative_dividends'],
                name="Total de Proventos", mode="lines+markers",
                line=dict(color="#2ca02c", width=3),
                marker=dict(size=6),
                hovertemplate="Total de Proventos: R$ %{y:,.2f}<extra></extra>"
            ), secondary_y=False)

            fig_multi.add_trace(go.Scatter(
                x=df_evolution['display_month'], y=df_evolution['planned_dividends'],
                name="Proventos Planejados", mode="lines",
                line=dict(color="#2ca02c", width=2, dash="dash"),
                hovertemplate="Proventos Planejados: R$ %{y:,.2f}<extra></extra>"
            ), secondary_y=False)

            bar_labels = [f"R$ {val:,.0f}".replace(",", ".") if val > 0 else "" for val in df_evolution['monthly_dividend']]

            fig_multi.add_trace(go.Bar(
                x=df_evolution['display_month'], y=df_evolution['monthly_dividend'],
                name="Proventos (Mês)",
                marker_color="rgba(242, 196, 26, 0.6)",
                text=bar_labels,
                textposition="outside",
                hovertemplate="Proventos (Mês): R$ %{y:,.2f}<extra></extra>"
            ), secondary_y=True)

            fig_multi.update_layout(
                title_text="Histórico de Evolução Patrimonial: Real vs. Planejado",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0.01)
            )

            fig_multi.update_yaxes(title_text="Valores Acumulados (R$)", tickformat="R$ ,.2f", secondary_y=False)
            fig_multi.update_yaxes(title_text="Proventos Mensais Recebidos (R$)", tickformat="R$ ,.2f", secondary_y=True)
            fig_multi.update_xaxes(title_text="Linha do Tempo (Mês/Ano)", type="category", tickangle=-45, tickmode="linear")

            st.plotly_chart(fig_multi, use_container_width=True)

    def _render_monthly_contributions_chart(self):
        st.markdown("---")
        df_contribs = DashboardService.get_monthly_contributions_by_year()
        if not df_contribs.empty:
            st.subheader("📊 Histórico de Aportes por Ano e Mês")

            # Formata os meses de numérico para nome em Português usando o dicionário
            from core.constants import MONTHS_PT
            df_contribs['Mês'] = df_contribs['month'].map(MONTHS_PT)

            # Ordena pelo número do mês no dataframe, mas o gráfico usará uma ordem estática
            df_contribs = df_contribs.sort_values(by=['month'])

            # Lista estática com os 12 meses do ano para forçar o eixo X
            meses_completos = list(MONTHS_PT.values())

            # Ordena os anos do menor para o maior para garantir a legenda
            anos_ordenados = sorted(df_contribs['year'].unique().tolist())

            # Gráfico de barras agrupadas (barmode='group') com category_orders para a legenda
            fig_contribs = px.bar(
                df_contribs,
                x="Mês",
                y="amount",
                color="year",
                barmode="group",
                title="Aportes Mensais",
                labels={"amount": "Valor Aportado (R$)", "Mês": "Mês", "year": "Ano"},
                category_orders={"year": anos_ordenados}
            )

            # Formatação do hover e eixos em Reais
            fig_contribs.update_traces(hovertemplate="Ano: %{data.name}<br>Mês: %{x}<br>Aporte: R$ %{y:,.2f}<extra></extra>")

            # Força o eixo X a exibir todos os 12 meses na ordem correta, mesmo sem dados
            fig_contribs.update_xaxes(categoryorder='array', categoryarray=meses_completos)

            fig_contribs.update_layout(yaxis_tickformat="R$ ,.2f")

            st.plotly_chart(fig_contribs, use_container_width=True)

import streamlit as st
from core.utils import Formatter

class DetailedHoldingsWidget:
    """Displays the active asset holdings detailed dataframe grid."""

    def render(self, df_positions):
        st.markdown("---")
        st.subheader("Ativos em Custódia (Detalhado)")
        
        df_table = df_positions[[
            'ticker', 'name', 'asset_type', 'sector', 
            'quantity', 'average_price', 'current_price', 
            'invested_amount', 'current_value', 'profit_loss', 'return_pct',
            'total_dividends', 'total_yoc',
            'l12m_dividends', 'l12m_yoc', 'ytd_dividends'
        ]].rename(columns={
            'ticker': 'Ticker', 'name': 'Nome', 'asset_type': 'Tipo', 'sector': 'Setor',
            'quantity': 'Quantidade', 'average_price': 'Preço Médio', 'current_price': 'Cotação Atual',
            'invested_amount': 'Total Investido', 'current_value': 'Valor Atual', 
            'profit_loss': 'Lucro/Prejuízo', 'return_pct': 'Retorno (%)',
            'total_dividends': 'Proventos Totais', 'total_yoc': 'YoC Total (%)',
            'l12m_dividends': 'Proventos 12M', 'l12m_yoc': 'YoC 12M (%)',
            'ytd_dividends': 'Proventos YTD'
        })

        # Apply localized Brazilian currency formatting to dataframe display
        for col in ['Preço Médio', 'Cotação Atual', 'Total Investido', 'Valor Atual', 'Lucro/Prejuízo', 'Proventos Totais', 'Proventos 12M', 'Proventos YTD']:
            df_table[col] = df_table[col].map(Formatter.format_currency)

        df_table['Retorno (%)'] = df_table['Retorno (%)'].map(lambda x: f"{x:+.2f}%")
        df_table['YoC Total (%)'] = df_table['YoC Total (%)'].map(lambda x: f"{x:.2f}%")
        df_table['YoC 12M (%)'] = df_table['YoC 12M (%)'].map(lambda x: f"{x:.2f}%")

        st.dataframe(df_table, use_container_width=True, hide_index=True)

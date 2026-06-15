import pandas as pd
import datetime
from core.database import db

class DashboardService:
    """Domain Service for aggregating dashboard data and metrics."""

    @staticmethod
    def calculate_positions(today_date=None) -> pd.DataFrame:
        """
        Returns a DataFrame consolidating the current position of each asset in the portfolio,
        calculating the accumulated Quantity, Average Price, Total Dividends, YTD, and L12M.
        """
        conn_pers = db.get_personal_connection()
        conn_assets = db.get_assets_connection()

        if today_date is None:
            today_date = datetime.date.today()

        l12m_limit = (today_date - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        ytd_limit = f"{today_date.year}-01-01"

        df_transactions = pd.read_sql_query(
            "SELECT date, ticker, transaction_type, quantity, unit_price, fees FROM transactions ORDER BY date ASC, id ASC",
            conn_pers
        )

        portfolio_state = {}

        for _, row in df_transactions.iterrows():
            ticker = row['ticker']
            txn_type = row['transaction_type']
            qty = row['quantity']
            price = row['unit_price']
            fees = row['fees']

            if ticker not in portfolio_state:
                portfolio_state[ticker] = {'quantity': 0, 'average_price': 0.0}

            current_state = portfolio_state[ticker]
            old_qty = current_state['quantity']
            old_avg_price = current_state['average_price']

            if txn_type == 'Compra':
                new_qty = old_qty + qty
                new_avg_price = (old_qty * old_avg_price + qty * price + fees) / new_qty if new_qty > 0 else 0.0
                portfolio_state[ticker] = {'quantity': new_qty, 'average_price': new_avg_price}
            elif txn_type == 'Venda':
                new_qty = max(0, old_qty - qty)
                portfolio_state[ticker] = {'quantity': new_qty, 'average_price': old_avg_price if new_qty > 0 else 0.0}

        active_assets = []
        for ticker, info in portfolio_state.items():
            if info['quantity'] > 0:
                cursor_assets = conn_assets.cursor()
                cursor_assets.execute("SELECT name, asset_type, sector, segment FROM assets WHERE ticker = ?", (ticker,))
                res = cursor_assets.fetchone()

                if res:
                    name, asset_type, sector, segment = res
                    asset_type_clean = asset_type.strip().lower() if asset_type else ""

                    if asset_type_clean in ['ação', 'acao']:
                        display_sector = segment if segment else sector
                    elif asset_type_clean == 'etf':
                        display_sector = "-"
                    else:
                        # For FII, BDR and others
                        display_sector = sector
                else:
                    name, asset_type, display_sector = f"Asset {ticker}", "Ação", "Outros"

                cursor_pers = conn_pers.cursor()
                cursor_pers.execute("SELECT SUM(total_value) FROM dividends WHERE ticker = ?", (ticker,))
                div_res = cursor_pers.fetchone()
                total_dividends = div_res[0] if div_res and div_res[0] is not None else 0.0

                cursor_pers.execute("SELECT SUM(total_value) FROM dividends WHERE ticker = ? AND date >= ?", (ticker, l12m_limit))
                l12m_res = cursor_pers.fetchone()
                l12m_dividends = l12m_res[0] if l12m_res and l12m_res[0] is not None else 0.0

                cursor_pers.execute("SELECT SUM(total_value) FROM dividends WHERE ticker = ? AND date >= ?", (ticker, ytd_limit))
                ytd_res = cursor_pers.fetchone()
                ytd_dividends = ytd_res[0] if ytd_res and ytd_res[0] is not None else 0.0

                active_assets.append({
                    'ticker': ticker,
                    'name': name,
                    'asset_type': asset_type,
                    'sector': display_sector,
                    'quantity': info['quantity'],
                    'average_price': info['average_price'],
                    'invested_amount': info['quantity'] * info['average_price'],
                    'total_dividends': total_dividends,
                    'l12m_dividends': l12m_dividends,
                    'ytd_dividends': ytd_dividends
                })

        conn_pers.close()
        conn_assets.close()
        return pd.DataFrame(active_assets)

    @staticmethod
    def calculate_historical_evolution() -> pd.DataFrame:
        """
        Returns the accumulated monthly history of net contributions and dividends for the evolution chart.
        """
        conn = db.get_personal_connection()
        df_t = pd.read_sql_query("SELECT date, transaction_type, quantity, unit_price, fees FROM transactions", conn)
        df_d = pd.read_sql_query("SELECT date, total_value FROM dividends", conn)
        conn.close()

        if df_t.empty and df_d.empty:
            return pd.DataFrame()

        df_t['month_str'] = df_t['date'].str[:7]
        df_d['month_str'] = df_d['date'].str[:7]

        df_t['net_cashflow'] = df_t.apply(
            lambda r: (r['quantity'] * r['unit_price'] + r['fees']) if r['transaction_type'] == 'Compra'
            else -(r['quantity'] * r['unit_price'] - r['fees']),
            axis=1
        )

        monthly_t = df_t.groupby('month_str')['net_cashflow'].sum().reset_index()
        monthly_d = df_d.groupby('month_str')['total_value'].sum().reset_index().rename(columns={'total_value': 'monthly_dividend'})

        all_months = sorted(list(set(monthly_t['month_str'].tolist() + monthly_d['month_str'].tolist())))
        timeline = pd.DataFrame({'month_str': all_months})

        timeline = timeline.merge(monthly_t, on='month_str', how='left').fillna(0.0)
        timeline = timeline.merge(monthly_d, on='month_str', how='left').fillna(0.0)

        timeline['cumulative_invested'] = timeline['net_cashflow'].cumsum()
        timeline['cumulative_dividends'] = timeline['monthly_dividend'].cumsum()

        return timeline

    @staticmethod
    def get_ytd_contributions(current_year: int) -> float:
        """Calculates total net contributions made in the current year."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SUM(quantity * unit_price + fees) FROM transactions WHERE transaction_type = 'Compra' AND date >= ?",
            (f"{current_year}-01-01",)
        )
        res_ytd = cursor.fetchone()
        ytd_contribution = res_ytd[0] if res_ytd and res_ytd[0] is not None else 0.0
        conn.close()
        return ytd_contribution

    @staticmethod
    def get_monthly_contributions_by_year() -> pd.DataFrame:
        """Returns monthly contributions grouped by year for the bar chart."""
        conn = db.get_personal_connection()
        df_t = pd.read_sql_query("SELECT date, quantity, unit_price, fees FROM transactions WHERE transaction_type = 'Compra'", conn)
        conn.close()
        
        if df_t.empty:
            return pd.DataFrame()
            
        df_t['amount'] = df_t['quantity'] * df_t['unit_price'] + df_t['fees']
        df_t['year'] = df_t['date'].str[:4]
        df_t['month'] = df_t['date'].str[5:7]
        
        # Group by year and month
        grouped = df_t.groupby(['year', 'month'])['amount'].sum().reset_index()
        return grouped

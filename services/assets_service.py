import pandas as pd
import datetime
from core.database import db
from core.utils.market_data import MarketData

class AssetService:
    """Domain Service for managing assets, transactions, dividends, and positions (Single Source of Truth)."""

    @staticmethod
    def register_fallback_asset(ticker: str):
        """Appends a fallback asset to assets.csv if not found in the catalog."""
        import os
        import streamlit as st
        
        if os.path.exists("assets.csv"):
            df = pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig")
            df.columns = df.columns.str.strip()
            if ticker not in df['CÓDIGO'].values:
                new_row = pd.DataFrame([{
                    "CÓDIGO": ticker,
                    "NOME": f"Asset {ticker}",
                    "IMAGEM": "",
                    "CNPJ": "",
                    "SETOR ECONÔMICO": "Outros",
                    "SUBSETOR": "",
                    "SEGMENTO / ADM / PAÍS": "",
                    "TIPO": "Ação",
                    "SEGMENTO": ""
                }])
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_csv("assets.csv", index=False, encoding="utf-8-sig")
                st.cache_data.clear()

    @staticmethod
    def add_transaction(ticker: str, date: str, transaction_type: str, quantity: int, unit_price: float, fees: float = 0.0) -> bool:
        """Inserts a Buy (BUY) or Sell (SELL) asset transaction into the personal database, avoiding duplicates."""
        conn_pers = db.get_personal_connection()
        cursor_pers = conn_pers.cursor()
        
        if transaction_type in ('Compra', 'BUY'):
            transaction_type = "BUY"
        elif transaction_type in ('Venda', 'SELL'):
            transaction_type = "SELL"
        
        cursor_pers.execute('''
            SELECT id FROM transactions 
            WHERE date = ? AND ticker = ? AND transaction_type = ? AND quantity = ? AND unit_price = ? AND fees = ?
        ''', (date, ticker, transaction_type, quantity, unit_price, fees))
        
        if cursor_pers.fetchone():
            conn_pers.close()
            return False # Skipped duplicate
            
        catalog = MarketData.load_assets_catalog()
        if catalog.empty or ticker not in catalog.index:
            AssetService.register_fallback_asset(ticker)
            
        cursor_pers.execute('''
            INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (date, ticker, transaction_type, quantity, unit_price, fees))
        
        conn_pers.commit()
        conn_pers.close()
        return True

    @staticmethod
    def add_dividend(ticker: str, date: str, dividend_type: str, total_value: float) -> bool:
        """Inserts a Dividend, JCP, or Yield receipt into the database, avoiding duplicates."""
        conn_pers = db.get_personal_connection()
        cursor_pers = conn_pers.cursor()
        
        if dividend_type in ('Dividendo', 'DIVIDEND'):
            dividend_type = "DIVIDEND"
        elif dividend_type in ('JCP', 'JCP'):
            dividend_type = "JCP"
        elif dividend_type in ('Rendimento', 'YIELD'):
            dividend_type = "YIELD"
        
        cursor_pers.execute('''
            SELECT id FROM dividends 
            WHERE date = ? AND ticker = ? AND dividend_type = ? AND total_value = ?
        ''', (date, ticker, dividend_type, total_value))
        
        if cursor_pers.fetchone():
            conn_pers.close()
            return False
            
        catalog = MarketData.load_assets_catalog()
        if catalog.empty or ticker not in catalog.index:
            AssetService.register_fallback_asset(ticker)
            
        cursor_pers.execute('''
            INSERT INTO dividends (date, ticker, dividend_type, total_value)
            VALUES (?, ?, ?, ?)
        ''', (date, ticker, dividend_type, total_value))
        
        conn_pers.commit()
        conn_pers.close()
        return True

    @staticmethod
    def process_b3_import(df: pd.DataFrame) -> tuple[int, int]:
        """Processes a DataFrame imported from B3, routing and translating row categories to English."""
        df.columns = df.columns.str.strip()
        
        processed_transactions = 0
        processed_dividends = 0
        
        for _, row in df.iterrows():
            try:
                movement = str(row.get('Tipo de Movimentação', row.get('Movimentação', ''))).strip()
                entry_exit = str(row.get('Entrada/Saída', '')).strip().lower()
                date_str = str(row.get('Data do Negócio', row.get('Data', ''))).strip()
                
                date_parts = date_str.split('/')
                if len(date_parts) == 3:
                    date = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"
                else:
                    date = date_str
                    
                raw_product = str(row.get('Código de Negociação', row.get('Produto', ''))).strip()
                ticker = raw_product.split('-')[0].strip()
                
                if not ticker or len(ticker) < 5 or not ticker[:4].isalpha():
                    continue
                    
                quantity = int(row.get('Quantidade', 0))
                raw_price = row.get('Preço', row.get('Preço unitário', 0.0))
                price = 0.0 if raw_price == '-' else float(raw_price)
                
                if ticker == "CXSE3" and date == "2021-04-30" and price == 0.0:
                    price = 9.67
                
                raw_value = row.get('Valor', row.get('Valor da Operação', 0.0))
                total_value = 0.0 if raw_value == '-' else float(raw_value)
                
                transaction_type = None
                if "Compra" in movement:
                    transaction_type = "BUY"
                elif "Venda" in movement:
                    transaction_type = "SELL"
                elif "Transferência - Liquidação" in movement:
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "BUY"
                    elif "debito" in entry_exit or "débito" in entry_exit:
                        transaction_type = "SELL"
                elif "Desdobro" in movement:
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "SPLIT"
                elif "Resgate" in movement:
                    transaction_type = "SELL"
                
                if transaction_type == "BUY":
                    success = AssetService.add_transaction(ticker, date, "BUY", quantity, price)
                    if success: processed_transactions += 1
                elif transaction_type == "SELL":
                    success = AssetService.add_transaction(ticker, date, "SELL", quantity, price)
                    if success: processed_transactions += 1
                elif transaction_type == "SPLIT":
                    success = AssetService.add_transaction(ticker, date, "BUY", quantity, 0.0)
                    if success: processed_transactions += 1
                elif any(term in movement for term in ["Dividendo", "Juros", "Rendimento"]):
                    dividend_type = "DIVIDEND" if "Dividendo" in movement else "JCP"
                    if "Rendimento" in movement:
                        dividend_type = "YIELD"
                    success = AssetService.add_dividend(ticker, date, dividend_type, total_value)
                    if success: processed_dividends += 1
                    
            except Exception:
                continue
                
        return processed_transactions, processed_dividends

    @staticmethod
    def get_quantity_on_date(ticker: str, date_str: str) -> int:
        """Returns the accumulated quantity owned of a specific ticker on a given date."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT SUM(CASE WHEN transaction_type='BUY' THEN quantity ELSE -quantity END)
                FROM transactions 
                WHERE ticker = ? AND date <= ?
            """, (ticker, date_str))
            res = cursor.fetchone()
            return res[0] if res and res[0] is not None else 0
        finally:
            conn.close()

    @staticmethod
    def get_asset_transactions(ticker: str) -> pd.DataFrame:
        """Returns all transactions for a specific asset ordered by date descending."""
        conn = db.get_personal_connection()
        try:
            df = pd.read_sql_query(
                "SELECT date as Data, CASE WHEN transaction_type='BUY' THEN 'Compra' ELSE 'Venda' END as Operação, quantity as Quantidade, unit_price as [Valor Unitário], (quantity * unit_price + fees) as [Valor Total] FROM transactions WHERE ticker = ? ORDER BY date DESC",
                conn, params=(ticker,)
            )
            return df
        finally:
            conn.close()

    @staticmethod
    def get_asset_dividends(ticker: str) -> pd.DataFrame:
        """Returns all dividend receipts for a specific asset."""
        conn = db.get_personal_connection()
        try:
            df = pd.read_sql_query(
                "SELECT date as Data, CASE WHEN dividend_type='DIVIDEND' THEN 'Dividendo' WHEN dividend_type='JCP' THEN 'JCP' ELSE 'Rendimento' END as Tipo, total_value as Total FROM dividends WHERE ticker = ? ORDER BY date DESC",
                conn, params=(ticker,)
            )
            return df
        finally:
            conn.close()

    @staticmethod
    def get_asset_metadata(ticker: str) -> dict:
        """Returns static metadata for a specific ticker from the local assets.csv catalog."""
        catalog = MarketData.load_assets_catalog()
        if not catalog.empty and ticker in catalog.index:
            row = catalog.loc[ticker]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            return {
                "name": str(row.get('NOME', 'Nome não disponível')),
                "image": str(row.get('IMAGEM', '')) if pd.notna(row.get('IMAGEM')) else '',
                "cnpj": str(row.get('CNPJ', 'N/D')) if pd.notna(row.get('CNPJ')) else 'N/D',
                "sector": str(row.get('SETOR ECONÔMICO', 'Outros')) if pd.notna(row.get('SETOR ECONÔMICO')) else 'Outros',
                "sub_sector": str(row.get('SUBSETOR ', '')) if pd.notna(row.get('SUBSETOR ')) else '',
                "segment": str(row.get('SEGMENTO / ADM / PAÍS', '')) if pd.notna(row.get('SEGMENTO / ADM / PAÍS')) else '',
                "asset_type": str(row.get('TIPO', 'Ação')) if pd.notna(row.get('TIPO')) else 'Ação'
            }
        return {
            "name": f"Asset {ticker}",
            "image": "",
            "cnpj": "N/D",
            "sector": "Outros",
            "sub_sector": "",
            "segment": "",
            "asset_type": "Ação"
        }

    @staticmethod
    def get_years_with_dividends() -> list:
        """Returns a sorted list of all unique years available in the dividends database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT strftime('%Y', date) as yr FROM dividends WHERE date IS NOT NULL ORDER BY yr DESC")
            years = [row[0] for row in cursor.fetchall() if row[0] is not None]
            return sorted(years, reverse=True)
        finally:
            conn.close()

    @staticmethod
    def get_asset_years_with_dividends(ticker: str) -> list:
        """Returns a sorted list of unique years in which a specific asset paid dividends."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT strftime('%Y', date) as yr FROM dividends WHERE ticker = ? AND date IS NOT NULL ORDER BY yr DESC", (ticker,))
            years = [row[0] for row in cursor.fetchall() if row[0] is not None]
            return sorted(years, reverse=True)
        finally:
            conn.close()

    @staticmethod
    def get_annual_dividends_pivot(year: str) -> pd.DataFrame:
        """Returns aggregated totals for dividends, JCP, and rendimentos for a specific year."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT dividend_type, SUM(total_value) 
                FROM dividends 
                WHERE strftime('%Y', date) = ? 
                GROUP BY dividend_type
            ''', (year,))
            
            rows = cursor.fetchall()
            
            data = {"DIVIDEND": 0.0, "JCP": 0.0, "YIELD": 0.0}
            for row in rows:
                div_type, total = row
                if div_type in data:
                    data[div_type] = float(total)
                else:
                    data["YIELD"] = data.get("YIELD", 0.0) + float(total)
                    
            total_sum = sum(data.values())
            
            df = pd.DataFrame([
                {"Categoria": "Total de Dividendos", "Valor (R$)": data["DIVIDEND"]},
                {"Categoria": "Total de JCP", "Valor (R$)": data["JCP"]},
                {"Categoria": "Total de Rendimentos", "Valor (R$)": data["YIELD"]},
                {"Categoria": "Total de Proventos (Soma de todos)", "Valor (R$)": total_sum}
            ])
            return df
        finally:
            conn.close()

    @staticmethod
    def get_asset_annual_dividends_pivot(ticker: str, year: str) -> pd.DataFrame:
        """Returns aggregated totals for dividends, JCP, and rendimentos for a specific asset and year."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT dividend_type, SUM(total_value)
                FROM dividends
                WHERE ticker = ? AND strftime('%Y', date) = ?
                GROUP BY dividend_type
            ''', (ticker, year))

            rows = cursor.fetchall()

            data = {"DIVIDEND": 0.0, "JCP": 0.0, "YIELD": 0.0}
            for row in rows:
                div_type, total = row
                if div_type in data:
                    data[div_type] = float(total)
                else:
                    data["YIELD"] = data.get("YIELD", 0.0) + float(total)

            total_sum = sum(data.values())

            df = pd.DataFrame([
                {"Categoria": "Total de Dividendos", "Valor (R$)": data["DIVIDEND"]},
                {"Categoria": "Total de JCP", "Valor (R$)": data["JCP"]},
                {"Categoria": "Total de Rendimentos", "Valor (R$)": data["YIELD"]},
                {"Categoria": "Total de Proventos (Soma de todos)", "Valor (R$)": total_sum}
            ])
            return df
        finally:
            conn.close()

    @staticmethod
    def get_tracked_market_assets() -> list:
        """Returns the list of tracked tickers from the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT ticker FROM tracked_market_assets ORDER BY ticker ASC")
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def add_tracked_market_asset(ticker: str) -> bool:
        """Adds a ticker to the watchlist in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR REPLACE INTO tracked_market_assets (ticker) VALUES (?)", (ticker.upper().strip(),))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def remove_tracked_market_asset(ticker: str) -> bool:
        """Removes a ticker from the watchlist in the database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM tracked_market_assets WHERE ticker = ?", (ticker.upper().strip(),))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def save_dividend_correction(ticker: str, year: int, total_value: float) -> bool:
        """Saves or updates a manual dividend correction inside the SQLite database."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES (?, ?, ?)",
                (ticker.upper().strip(), int(year), float(total_value))
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    @staticmethod
    def get_dividend_corrections(ticker: str) -> dict:
        """Returns all custom dividend corrections registered for a specific ticker."""
        conn = db.get_personal_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT year, total_value FROM dividend_corrections WHERE ticker = ? ORDER BY year DESC", (ticker.upper().strip(),))
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception:
            return {}
        finally:
            conn.close()

    @staticmethod
    def calculate_positions(today_date=None) -> pd.DataFrame:
        """
        Consolidates active portfolio holdings, calculating average price (PM),
        invested totals, and received dividends.
        """
        conn_pers = db.get_personal_connection()
        catalog = MarketData.load_assets_catalog()

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

            if txn_type == 'BUY':
                new_qty = old_qty + qty
                new_avg_price = (old_qty * old_avg_price + qty * price + fees) / new_qty if new_qty > 0 else 0.0
                portfolio_state[ticker] = {'quantity': new_qty, 'average_price': new_avg_price}
            elif txn_type == 'SELL':
                new_qty = max(0, old_qty - qty)
                portfolio_state[ticker] = {'quantity': new_qty, 'average_price': old_avg_price if new_qty > 0 else 0.0}

        active_assets = []
        for ticker, info in portfolio_state.items():
            if info['quantity'] > 0:
                if not catalog.empty and ticker in catalog.index:
                    row = catalog.loc[ticker]
                    if isinstance(row, pd.DataFrame):
                        row = row.iloc[0]
                    name = str(row.get('NOME', f"Asset {ticker}"))
                    asset_type = str(row.get('TIPO', 'Ação'))
                    sector = str(row.get('SETOR ECONÔMICO', 'Outros'))
                    segment = str(row.get('SEGMENTO / ADM / PAÍS', ''))

                    asset_type_clean = asset_type.strip().lower()
                    if asset_type_clean in ['ação', 'acao']:
                        display_sector = segment if segment else sector
                    elif asset_type_clean == 'etf':
                        display_sector = "-"
                    else:
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
        return pd.DataFrame(active_assets)

    @staticmethod
    def calculate_historical_evolution() -> pd.DataFrame:
        """
        Consolidates a month-by-month chronological sequence of your portfolio evolution.
        Ensures a seamless monthly series without gaps since the first transaction.
        """
        conn = db.get_personal_connection()
        df_transactions = pd.read_sql_query("SELECT date, transaction_type, quantity, unit_price, fees FROM transactions", conn)
        df_dividends = pd.read_sql_query("SELECT date, dividend_type, total_value FROM dividends", conn)
        conn.close()

        if df_transactions.empty and df_dividends.empty:
            return pd.DataFrame()

        df_transactions['month_str'] = df_transactions['date'].str[:7]
        df_dividends['month_str'] = df_dividends['date'].str[:7]

        df_transactions['net_cashflow'] = df_transactions.apply(
            lambda r: (r['quantity'] * r['unit_price'] + r['fees']) if r['transaction_type'] == 'BUY'
            else -(r['quantity'] * r['unit_price'] - r['fees']),
            axis=1
        )

        monthly_t = df_transactions.groupby('month_str')['net_cashflow'].sum().reset_index()
        monthly_d = df_dividends.groupby('month_str')['total_value'].sum().reset_index().rename(columns={'total_value': 'monthly_dividend'})

        min_date_transactions = df_transactions['date'].min() if not df_transactions.empty else None
        min_date_dividends = df_dividends['date'].min() if not df_dividends.empty else None

        dates = [d for d in [min_date_transactions, min_date_dividends] if d is not None]
        if not dates:
            return pd.DataFrame()

        start_date_str = min(dates)
        start_date = pd.to_datetime(start_date_str).replace(day=1)
        today = datetime.date.today()

        date_range = pd.date_range(start=start_date, end=today, freq='MS')
        all_months = date_range.strftime('%Y-%m').tolist()

        if not all_months:
            all_months = [start_date.strftime('%Y-%m')]

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
            "SELECT SUM(quantity * unit_price + fees) FROM transactions WHERE transaction_type = 'BUY' AND date >= ?", 
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
        df_transactions = pd.read_sql_query("SELECT date, quantity, unit_price, fees FROM transactions WHERE transaction_type = 'BUY'", conn)
        conn.close()

        if df_transactions.empty:
            return pd.DataFrame()

        df_transactions['amount'] = df_transactions['quantity'] * df_transactions['unit_price'] + df_transactions['fees']
        df_transactions['year'] = df_transactions['date'].str[:4]
        df_transactions['month'] = df_transactions['date'].str[5:7]

        grouped = df_transactions.groupby(['year', 'month'])['amount'].sum().reset_index()
        return grouped

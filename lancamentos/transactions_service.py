import pandas as pd
from core.database import db
from core.utils import MarketData

class TransactionService:
    """Domain Service for managing transactions, dividends, and B3 integrations."""

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
        """Inserts a Buy or Sell asset transaction into the personal database, avoiding duplicates."""
        conn_pers = db.get_personal_connection()
        cursor_pers = conn_pers.cursor()
        
        cursor_pers.execute('''
            SELECT id FROM transactions 
            WHERE date = ? AND ticker = ? AND transaction_type = ? AND quantity = ? AND unit_price = ? AND fees = ?
        ''', (date, ticker, transaction_type, quantity, unit_price, fees))
        
        if cursor_pers.fetchone():
            conn_pers.close()
            return False # Skipped duplicate
            
        # Ensure the asset exists in the assets CSV catalog
        catalog = MarketData.load_assets_catalog()
        if catalog.empty or ticker not in catalog.index:
            TransactionService.register_fallback_asset(ticker)
            
        cursor_pers.execute('''
            INSERT INTO transactions (date, ticker, transaction_type, quantity, unit_price, fees)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (date, ticker, transaction_type, quantity, unit_price, fees))
        
        conn_pers.commit()
        conn_pers.close()
        return True

    @staticmethod
    def add_dividend(ticker: str, date: str, dividend_type: str, total_value: float) -> bool:
        """Inserts a Dividend or JCP receipt into the database, avoiding duplicates."""
        conn_pers = db.get_personal_connection()
        cursor_pers = conn_pers.cursor()
        
        cursor_pers.execute('''
            SELECT id FROM dividends 
            WHERE date = ? AND ticker = ? AND dividend_type = ? AND total_value = ?
        ''', (date, ticker, dividend_type, total_value))
        
        if cursor_pers.fetchone():
            conn_pers.close()
            return False
            
        # Ensure the asset exists in the assets CSV catalog
        catalog = MarketData.load_assets_catalog()
        if catalog.empty or ticker not in catalog.index:
            TransactionService.register_fallback_asset(ticker)
            
        cursor_pers.execute('''
            INSERT INTO dividends (date, ticker, dividend_type, total_value)
            VALUES (?, ?, ?, ?)
        ''', (date, ticker, dividend_type, total_value))
        
        conn_pers.commit()
        conn_pers.close()
        return True

    @staticmethod
    def process_b3_import(df: pd.DataFrame) -> tuple[int, int]:
        """Processes a DataFrame imported from B3, routing the actions to the database."""
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
                
                # Dynamic safeguard: CXSE3 IPO price on April 30, 2021 was 9.67 per share,
                # but B3 exports it as '-' (blank) because it occurred out-of-broker.
                if ticker == "CXSE3" and date == "2021-04-30" and price == 0.0:
                    price = 9.67
                
                raw_value = row.get('Valor', row.get('Valor da Operação', 0.0))
                total_value = 0.0 if raw_value == '-' else float(raw_value)
                
                transaction_type = None
                if "Compra" in movement:
                    transaction_type = "Compra"
                elif "Venda" in movement:
                    transaction_type = "Venda"
                elif "Transferência - Liquidação" in movement:
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "Compra"
                    elif "debito" in entry_exit or "débito" in entry_exit:
                        transaction_type = "Venda"
                elif "Desdobro" in movement:
                    if "credito" in entry_exit or "crédito" in entry_exit:
                        transaction_type = "Desdobro_Credito"
                elif "Resgate" in movement:
                    transaction_type = "Venda"
                
                if transaction_type == "Compra":
                    success = TransactionService.add_transaction(ticker, date, "Compra", quantity, price)
                    if success: processed_transactions += 1
                elif transaction_type == "Venda":
                    success = TransactionService.add_transaction(ticker, date, "Venda", quantity, price)
                    if success: processed_transactions += 1
                elif transaction_type == "Desdobro_Credito":
                    success = TransactionService.add_transaction(ticker, date, "Compra", quantity, 0.0)
                    if success: processed_transactions += 1
                elif any(term in movement for term in ["Dividendo", "Juros", "Rendimento"]):
                    dividend_type = "Dividendo" if "Dividendo" in movement else "JCP"
                    success = TransactionService.add_dividend(ticker, date, dividend_type, total_value)
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
                SELECT SUM(CASE WHEN transaction_type='Compra' THEN quantity ELSE -quantity END)
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
                "SELECT date as Data, transaction_type as Operação, quantity as Quantidade, unit_price as [Valor Unitário], (quantity * unit_price + fees) as [Valor Total] FROM transactions WHERE ticker = ? ORDER BY date DESC",
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
                "SELECT date as Data, dividend_type as Tipo, total_value as Total FROM dividends WHERE ticker = ? ORDER BY date DESC",
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
            # Group by dividend_type for the chosen year
            cursor.execute('''
                SELECT dividend_type, SUM(total_value) 
                FROM dividends 
                WHERE strftime('%Y', date) = ? 
                GROUP BY dividend_type
            ''', (year,))
            
            rows = cursor.fetchall()
            
            # Map into a clean structured dictionary
            data = {"Dividendo": 0.0, "JCP": 0.0, "Rendimento": 0.0}
            for row in rows:
                div_type, total = row
                if div_type in data:
                    data[div_type] = float(total)
                else:
                    data["Rendimento"] = data.get("Rendimento", 0.0) + float(total)
                    
            total_sum = sum(data.values())
            
            # Form into a neat DataFrame for display
            df = pd.DataFrame([
                {"Categoria": "Total de Dividendos", "Valor (R$)": data["Dividendo"]},
                {"Categoria": "Total de JCP", "Valor (R$)": data["JCP"]},
                {"Categoria": "Total de Rendimentos", "Valor (R$)": data["Rendimento"]},
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

            data = {"Dividendo": 0.0, "JCP": 0.0, "Rendimento": 0.0}
            for row in rows:
                div_type, total = row
                if div_type in data:
                    data[div_type] = float(total)
                else:
                    data["Rendimento"] = data.get("Rendimento", 0.0) + float(total)

            total_sum = sum(data.values())

            df = pd.DataFrame([
                {"Categoria": "Total de Dividendos", "Valor (R$)": data["Dividendo"]},
                {"Categoria": "Total de JCP", "Valor (R$)": data["JCP"]},
                {"Categoria": "Total de Rendimentos", "Valor (R$)": data["Rendimento"]},
                {"Categoria": "Total de Proventos (Soma de todos)", "Valor (R$)": total_sum}
            ])
            return df
        finally:
            conn.close()

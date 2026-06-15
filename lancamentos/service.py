import pandas as pd
from core.database import db

class TransactionService:
    """Domain Service for managing transactions, dividends, and B3 integrations."""

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
            
        # Ensure the asset exists in the assets database
        conn_assets = db.get_assets_connection()
        cursor_assets = conn_assets.cursor()
        cursor_assets.execute("SELECT ticker FROM assets WHERE ticker = ?", (ticker,))
        if not cursor_assets.fetchone():
            cursor_assets.execute(
                "INSERT INTO assets (ticker, name, image, cnpj, sector, sub_sector, segment, asset_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, f"Asset {ticker}", "", "", "Outros", "", "", "Ação")
            )
            conn_assets.commit()
        conn_assets.close()
            
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
            
        # Ensure the asset exists in the assets database
        conn_assets = db.get_assets_connection()
        cursor_assets = conn_assets.cursor()
        cursor_assets.execute("SELECT ticker FROM assets WHERE ticker = ?", (ticker,))
        if not cursor_assets.fetchone():
            cursor_assets.execute(
                "INSERT INTO assets (ticker, name, image, cnpj, sector, sub_sector, segment, asset_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, f"Asset {ticker}", "", "", "Outros", "", "", "Ação")
            )
            conn_assets.commit()
        conn_assets.close()
            
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

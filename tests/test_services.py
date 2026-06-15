import pytest
import sqlite3
import os
import datetime
import pandas as pd
from core.database import db, DatabaseManager
from lancamentos.service import TransactionService
from dashboard.service import DashboardService

TEST_PERSONAL_DB = "test_carteira.db"
TEST_ASSETS_DB = "test_assets.db"

# Fixture to safely create and remove the test databases
@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    for test_db_file in [TEST_PERSONAL_DB, TEST_ASSETS_DB]:
        if os.path.exists(test_db_file):
            try:
                os.remove(test_db_file)
            except PermissionError:
                pass
        
    test_db = DatabaseManager(TEST_PERSONAL_DB, TEST_ASSETS_DB)
    test_db.init_assets_db()
    test_db.init_personal_db()

    # Redirect global db instance to use the test databases
    monkeypatch.setattr(db, "get_personal_connection", test_db.get_personal_connection)
    monkeypatch.setattr(db, "get_assets_connection", test_db.get_assets_connection)
    
    yield
    
    for test_db_file in [TEST_PERSONAL_DB, TEST_ASSETS_DB]:
        if os.path.exists(test_db_file):
            try:
                os.remove(test_db_file)
            except PermissionError:
                pass

def test_add_transaction_and_assets_creation():
    """Ensures that the transaction creates the asset using the fallback metadata in the assets db."""
    TransactionService.add_transaction("BBAS3", "2021-04-30", "Compra", 100, 20.00, 5.0)
    
    conn = db.get_assets_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticker, name, sector FROM assets")
    asset = cursor.fetchone()
    assert asset == ("BBAS3", "Asset BBAS3", "Outros")
    conn.close()

def test_average_price_calculation():
    """Ensures chronologically weighted average price math works perfectly."""
    TransactionService.add_transaction("BBAS3", "2021-04-30", "Compra", 100, 20.00)
    
    df = DashboardService.calculate_positions()
    assert len(df) == 1
    assert df.loc[0, "quantity"] == 100
    assert df.loc[0, "average_price"] == 20.00
    
    TransactionService.add_transaction("BBAS3", "2021-05-15", "Compra", 100, 30.00)
    df = DashboardService.calculate_positions()
    assert df.loc[0, "quantity"] == 200
    assert df.loc[0, "average_price"] == 25.00 
    
    TransactionService.add_transaction("BBAS3", "2021-06-01", "Venda", 50, 40.00)
    df = DashboardService.calculate_positions()
    assert df.loc[0, "quantity"] == 150
    assert df.loc[0, "average_price"] == 25.00 
    
    TransactionService.add_transaction("BBAS3", "2021-07-01", "Compra", 50, 15.00)
    df = DashboardService.calculate_positions()
    assert df.loc[0, "quantity"] == 200
    assert df.loc[0, "average_price"] == 22.50

def test_b3_excel_importer_logic():
    """Ensures Pandas import logic maps B3 columns and handles liquidations correctly."""
    data_example = {
        "Entrada/Saída": ["Credito", "Credito", "Debito", "Credito"],
        "Movimentação": ["Transferência - Liquidação", "Dividendo", "Transferência - Liquidação", "Transferência"],
        "Data": ["30/04/2021", "15/05/2021", "01/06/2021", "10/06/2021"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A"],
        "Quantidade": [100, 0, 50, 100],
        "Preço unitário": [20.00, 0.0, 30.00, "-"], 
        "Valor da Operação": [2000.00, 50.00, 1500.00, "-"]
    }
    df_excel = pd.DataFrame(data_example)
    
    trans_count, prov_count = TransactionService.process_b3_import(df_excel)
    
    assert trans_count == 2 
    assert prov_count == 1  
    
    df_positions = DashboardService.calculate_positions()
    assert len(df_positions) == 1
    assert df_positions.loc[0, "quantity"] == 50
    assert df_positions.loc[0, "average_price"] == 20.00 
    assert df_positions.loc[0, "total_dividends"] == 50.00

def test_b3_importer_deduplication():
    """Ensures running imports consecutively does not duplicate data in SQLite."""
    data_example = {
        "Entrada/Saída": ["Credito", "Credito"],
        "Movimentação": ["Transferência - Liquidação", "Dividendo"],
        "Data": ["30/04/2021", "15/05/2021"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A", "BBAS3 - BANCO DO BRASIL S/A"],
        "Quantidade": [100, 0],
        "Preço unitário": [20.00, 0.0],
        "Valor da Operação": [2000.00, 50.00]
    }
    df_excel = pd.DataFrame(data_example)
    
    t1, p1 = TransactionService.process_b3_import(df_excel)
    assert t1 == 1
    assert p1 == 1
    
    t2, p2 = TransactionService.process_b3_import(df_excel)
    assert t2 == 0
    assert p2 == 0
    
    df_positions = DashboardService.calculate_positions()
    assert len(df_positions) == 1
    assert df_positions.loc[0, "quantity"] == 100
    assert df_positions.loc[0, "total_dividends"] == 50.00

def test_dividends_time_windows():
    """Ensures the engine calculates total, YTD, and L12M accumulated dividends properly."""
    TransactionService.add_transaction("BBAS3", "2021-04-30", "Compra", 100, 20.00)
    TransactionService.add_dividend("BBAS3", "2026-06-11", "Dividendo", 100.00)
    TransactionService.add_dividend("BBAS3", "2025-11-15", "Dividendo", 50.00)
    TransactionService.add_dividend("BBAS3", "2024-11-15", "Dividendo", 30.00)
    
    df_positions = DashboardService.calculate_positions(today_date=datetime.date(2026, 6, 13))
    
    assert len(df_positions) == 1
    assert df_positions.loc[0, "total_dividends"] == 180.00 
    assert df_positions.loc[0, "l12m_dividends"] == 150.00     
    assert df_positions.loc[0, "ytd_dividends"] == 100.00      

def test_historical_evolution_calculation():
    """Ensures monthly accumulated history for cashflow and dividends is correct."""
    TransactionService.add_transaction("BBAS3", "2025-01-10", "Compra", 10, 20.00) 
    TransactionService.add_transaction("BBAS3", "2025-02-15", "Compra", 10, 30.00) 
    TransactionService.add_dividend("BBAS3", "2025-02-28", "Dividendo", 50.00)       
    
    df_ev = DashboardService.calculate_historical_evolution()
    
    assert len(df_ev) == 2 
    assert df_ev.loc[0, "month_str"] == "2025-01"
    assert df_ev.loc[0, "cumulative_invested"] == 200.00
    assert df_ev.loc[0, "cumulative_dividends"] == 0.00
    
    assert df_ev.loc[1, "month_str"] == "2025-02"
    assert df_ev.loc[1, "cumulative_invested"] == 500.00 
    assert df_ev.loc[1, "cumulative_dividends"] == 50.00        

def test_b3_split_logic():
    """Ensures 'Desdobro' events are imported as zero-cost buys, halving average price."""
    TransactionService.add_transaction("BBAS3", "2021-04-30", "Compra", 100, 20.00)
    
    data_example = {
        "Entrada/Saída": ["Credito"],
        "Movimentação": ["Desdobro"],
        "Data": ["17/04/2024"],
        "Produto": ["BBAS3 - BANCO DO BRASIL S/A"],
        "Quantidade": [100],
        "Preço unitário": ["-"],
        "Valor da Operação": ["-"]
    }
    df_excel = pd.DataFrame(data_example)
    
    trans, prov = TransactionService.process_b3_import(df_excel)
    assert trans == 1
    assert prov == 0
    
    df_pos = DashboardService.calculate_positions()
    assert len(df_pos) == 1
    assert df_pos.loc[0, "quantity"] == 200
    assert df_pos.loc[0, "average_price"] == 10.00 

def test_b3_resgate_logic():
    """Ensures 'Resgate' events are imported as Sells, bringing quantity to zero."""
    TransactionService.add_transaction("NUBR33", "2021-12-10", "Compra", 239, 8.36)
    
    data_example = {
        "Entrada/Saída": ["Debito", "Credito"],
        "Movimentação": ["Transferência - Liquidação", "Resgate"],
        "Data": ["14/12/2021", "15/09/2023"],
        "Produto": ["NUBR33 - NU HOLDINGS LTD.", "NUBR33 - NU HOLDINGS LTD."],
        "Quantidade": [1, 238],
        "Preço unitário": [10.50, 5.981],
        "Valor da Operação": [10.50, 1423.42]
    }
    df_excel = pd.DataFrame(data_example)
    
    trans, prov = TransactionService.process_b3_import(df_excel)
    assert trans == 2
    assert prov == 0
    
    # Position should be 0 and therefore not returned by calculate_positions
    df_pos = DashboardService.calculate_positions()
    assert len(df_pos) == 0

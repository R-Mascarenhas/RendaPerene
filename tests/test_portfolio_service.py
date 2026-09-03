import pytest
import datetime
import pandas as pd
from services.assets_service import AssetService

def test_average_price_calculation():
    """Ensures chronologically weighted average price math works perfectly."""
    AssetService.add_transaction("BBAS3", "2021-04-30", "BUY", 100, 20.00)

    df = AssetService.calculate_positions()
    assert len(df) == 1
    assert df.loc[0, "quantity"] == 100
    assert df.loc[0, "average_price"] == 20.00

    AssetService.add_transaction("BBAS3", "2021-05-15", "BUY", 100, 30.00)
    df = AssetService.calculate_positions()
    assert df.loc[0, "quantity"] == 200
    assert df.loc[0, "average_price"] == 25.00

    AssetService.add_transaction("BBAS3", "2021-06-01", "SELL", 50, 40.00)
    df = AssetService.calculate_positions()
    assert df.loc[0, "quantity"] == 150
    assert df.loc[0, "average_price"] == 25.00

    AssetService.add_transaction("BBAS3", "2021-07-01", "BUY", 50, 15.00)
    df = AssetService.calculate_positions()
    assert df.loc[0, "quantity"] == 200
    assert df.loc[0, "average_price"] == 22.50

def test_dividends_time_windows():
    """Ensures the engine calculates total, YTD, and L12M accumulated dividends properly."""
    AssetService.add_transaction("BBAS3", "2021-04-30", "BUY", 100, 20.00)
    AssetService.add_dividend("BBAS3", "2026-06-11", "DIVIDEND", 100.00)
    AssetService.add_dividend("BBAS3", "2025-11-15", "DIVIDEND", 50.00)
    AssetService.add_dividend("BBAS3", "2024-11-15", "DIVIDEND", 30.00)

    df_positions = AssetService.calculate_positions(today_date=datetime.date(2026, 6, 13))

    assert len(df_positions) == 1
    assert df_positions.loc[0, "total_dividends"] == 180.00
    assert df_positions.loc[0, "l12m_dividends"] == 150.00
    assert df_positions.loc[0, "ytd_dividends"] == 100.00

def test_historical_evolution_calculation():
    """Ensures monthly accumulated history for cashflow and dividends is correct."""
    AssetService.add_transaction("BBAS3", "2025-01-10", "BUY", 10, 20.00)
    AssetService.add_transaction("BBAS3", "2025-02-15", "BUY", 10, 30.00)
    AssetService.add_dividend("BBAS3", "2025-02-28", "DIVIDEND", 50.00)

    df_ev = AssetService.calculate_historical_evolution()

    assert len(df_ev) >= 2
    assert df_ev.loc[0, "month_str"] == "2025-01"
    assert df_ev.loc[0, "cumulative_invested"] == 200.00
    assert df_ev.loc[0, "cumulative_dividends"] == 0.00

    assert df_ev.loc[1, "month_str"] == "2025-02"
    assert df_ev.loc[1, "cumulative_invested"] == 500.00
    assert df_ev.loc[1, "cumulative_dividends"] == 50.00

def test_get_quantity_on_date():
    """Verifies retro-calculating the owned quantity of an asset at specific historical cut dates."""
    AssetService.add_transaction("BBAS3", "2025-01-01", "BUY", 100, 20.00)
    AssetService.add_transaction("BBAS3", "2025-03-01", "BUY", 100, 22.00)
    AssetService.add_transaction("BBAS3", "2025-05-01", "SELL", 50, 25.00)

    qty_before = AssetService.get_quantity_on_date("BBAS3", "2024-12-31")
    qty_jan = AssetService.get_quantity_on_date("BBAS3", "2025-01-15")
    qty_feb = AssetService.get_quantity_on_date("BBAS3", "2025-02-15")
    qty_mar = AssetService.get_quantity_on_date("BBAS3", "2025-03-15")
    qty_jun = AssetService.get_quantity_on_date("BBAS3", "2025-06-01")

    assert qty_before == 0
    assert qty_jan == 100
    assert qty_feb == 100
    assert qty_mar == 200
    assert qty_jun == 150

def test_asset_annual_dividends_pivot():
    """Verifies that the pivot queries group and sum dividend categories correctly for specific assets and years."""
    AssetService.add_dividend("BBAS3", "2025-05-15", "DIVIDEND", 50.00)
    AssetService.add_dividend("BBAS3", "2025-08-15", "JCP", 30.00)
    AssetService.add_dividend("CXSE3", "2025-05-15", "DIVIDEND", 100.00)
    AssetService.add_dividend("BBAS3", "2024-05-15", "DIVIDEND", 15.00)

    df_pivot_bb = AssetService.get_asset_annual_dividends_pivot("BBAS3", "2025")

    val_div = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de Dividendos', 'Valor (R$)'].values[0]
    val_jcp = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de JCP', 'Valor (R$)'].values[0]
    val_rend = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de Rendimentos', 'Valor (R$)'].values[0]
    val_total = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de Proventos (Soma de todos)', 'Valor (R$)'].values[0]

    assert val_div == 50.00
    assert val_jcp == 30.00
    assert val_rend == 0.00
    assert val_total == 80.00

def test_sell_all_shares_retains_monitoring_but_allows_removal():
    """
    Verifies that when a stock is owned (and therefore automatically monitored),
    selling it completely (bringing its position quantity to 0):
    1. Keeps the stock monitored in get_tracked_market_assets(include_owned=True).
    2. Allows the user to manually remove it (by listing it in get_tracked_market_assets(include_owned=False)).
    """
    AssetService.add_transaction("BBAS3", "2021-12-15", "BUY", 10, 10.00)

    # Verify initially BBAS3 is NOT in manual removal list
    assert "BBAS3" not in AssetService.get_tracked_market_assets(include_owned=False)

    # Sell all 10 shares of BBAS3
    AssetService.add_transaction("BBAS3", "2021-12-16", "SELL", 10, 12.00)

    # Position must be 0
    positions = AssetService.calculate_positions()
    assert positions.empty or "BBAS3" not in positions["ticker"].values

    # It should STILL be monitored
    combined = AssetService.get_tracked_market_assets(include_owned=True)
    assert "BBAS3" in combined

    # But it should NOW be available in the manual removal list since it is no longer owned!
    manual_only = AssetService.get_tracked_market_assets(include_owned=False)
    assert "BBAS3" in manual_only


def test_sale_transaction_total_subtracts_fees():
    """The displayed proceeds of a sale must be net of brokerage fees."""
    AssetService.add_transaction("BBAS3", "2021-12-15", "BUY", 100, 10.00)
    AssetService.add_transaction("BBAS3", "2021-12-16", "SELL", 100, 10.00, 5.00)

    transactions = AssetService.get_asset_transactions("BBAS3")

    sale = transactions[transactions["Operação"] == "Venda"].iloc[0]
    assert sale["Valor Total"] == 995.00


def test_instantiable_portfolio_contexts_isolation(tmp_path):
    """Proves that two independent AssetService instances are completely isolated physically and logically."""
    from core.database import DatabaseManager
    from core.daos.portfolio_dao import PortfolioDAO
    from services.assets_service import AssetService

    # 1. Create two independent database files using temporary paths
    db_file1 = str(tmp_path / "portfolio1.db")
    db_file2 = str(tmp_path / "portfolio2.db")

    db_manager1 = DatabaseManager(personal_db=db_file1)
    db_manager2 = DatabaseManager(personal_db=db_file2)

    db_manager1.init_personal_db()
    db_manager2.init_personal_db()

    # 2. Instantiate two custom Portfolio DAOs
    dao1 = PortfolioDAO(db_manager=db_manager1)
    dao2 = PortfolioDAO(db_manager=db_manager2)

    # 3. Instantiate two custom AssetServices
    service1 = AssetService(portfolio_repo=dao1)
    service2 = AssetService(portfolio_repo=dao2)

    # 4. Perform actions on service1
    service1.add_transaction("WEGE3", "2021-04-30", "BUY", 100, 30.00)

    # 5. Verify service1 has the position, but service2 remains completely empty!
    df1 = service1.calculate_positions()
    df2 = service2.calculate_positions()

    assert len(df1) == 1
    assert df1.loc[0, "ticker"] == "WEGE3"
    assert df1.loc[0, "quantity"] == 100

    assert len(df2) == 0  # Completely isolated!

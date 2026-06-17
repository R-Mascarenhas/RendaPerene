import pytest
import sqlite3
import os
import datetime
import pandas as pd
from core.database import db, DatabaseManager
from lancamentos.transactions_service import TransactionService
from dashboard.dashboard_service import DashboardService
from planning.planning_service import SimulationService
from core.utils import MarketData

TEST_PERSONAL_DB = "test_carteira.db"

# Fixture to safely create and remove the test databases and write mock CSV catalog
@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    if os.path.exists(TEST_PERSONAL_DB):
        try:
            os.remove(TEST_PERSONAL_DB)
        except PermissionError:
            pass

    if os.path.exists("test_assets.csv"):
        os.remove("test_assets.csv")

    # Backup real assets.csv if it exists
    real_csv_exists = os.path.exists("assets.csv")
    if real_csv_exists:
        import shutil
        shutil.copy("assets.csv", "assets.csv.backup")

    test_db = DatabaseManager(TEST_PERSONAL_DB)
    test_db.init_personal_db()

    # Write a clean mock assets.csv for the tests
    test_csv_content = (
        "CÓDIGO,NOME,IMAGEM,CNPJ,SETOR ECONÔMICO,SUBSETOR ,SEGMENTO / ADM / PAÍS,TIPO,SEGMENTO\n"
        "BBAS3,Banco do Brasil,https://...,00.000.000/0001-91,Financeiro,Intermediários,Bancos,Ação,Bancos\n"
        "CXSE3,Caixa Seguridade,https://...,00.000.000/0001-92,Seguridade,Seguros,Seguridade,Ação,Seguros\n"
    )
    with open("test_assets.csv", "w", encoding="utf-8-sig") as f:
        f.write(test_csv_content)

    def mock_load_catalog():
        return pd.read_csv("test_assets.csv", dtype=str, encoding="utf-8-sig").set_index("CÓDIGO")

    # Redirect global db instance to use the test database
    monkeypatch.setattr(db, "get_personal_connection", test_db.get_personal_connection)
    monkeypatch.setattr(MarketData, "load_assets_catalog", mock_load_catalog)

    yield

    if os.path.exists(TEST_PERSONAL_DB):
        try:
            os.remove(TEST_PERSONAL_DB)
        except PermissionError:
            pass

    if os.path.exists("test_assets.csv"):
        os.remove("test_assets.csv")

    # Restore real assets.csv from backup
    if os.path.exists("assets.csv.backup"):
        import shutil
        shutil.copy("assets.csv.backup", "assets.csv")
        os.remove("assets.csv.backup")
    elif os.path.exists("assets.csv"):
        os.remove("assets.csv")

def test_add_transaction_and_assets_creation():
    """Ensures that the transaction creates the asset using the fallback metadata in the assets csv."""
    if os.path.exists("assets_temp.csv"):
        os.remove("assets_temp.csv")
    shutil_copy = "cp test_assets.csv assets.csv"
    import shutil
    shutil.copy("test_assets.csv", "assets.csv")

    TransactionService.add_transaction("MOCK4", "2021-04-30", "Compra", 100, 20.00, 5.0)

    df = pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig").set_index("CÓDIGO")
    assert "MOCK4" in df.index
    assert df.loc["MOCK4", "NOME"] == "Asset MOCK4"

    if os.path.exists("assets.csv"):
        os.remove("assets.csv")

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

    # Timeline is continuous up to current month, so length is >= 2
    assert len(df_ev) >= 2
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

def test_get_quantity_on_date():
    """Verifies retro-calculating the owned quantity of an asset at specific historical cut dates."""
    # 1. Buy 100 on 2025-01-01
    TransactionService.add_transaction("BBAS3", "2025-01-01", "Compra", 100, 20.00)
    # 2. Buy 100 on 2025-03-01
    TransactionService.add_transaction("BBAS3", "2025-03-01", "Compra", 100, 22.00)
    # 3. Sell 50 on 2025-05-01
    TransactionService.add_transaction("BBAS3", "2025-05-01", "Venda", 50, 25.00)

    # Check quantities at specific points in time
    qty_before = TransactionService.get_quantity_on_date("BBAS3", "2024-12-31")
    qty_jan = TransactionService.get_quantity_on_date("BBAS3", "2025-01-15")
    qty_feb = TransactionService.get_quantity_on_date("BBAS3", "2025-02-15")
    qty_mar = TransactionService.get_quantity_on_date("BBAS3", "2025-03-15")
    qty_jun = TransactionService.get_quantity_on_date("BBAS3", "2025-06-01")

    assert qty_before == 0
    assert qty_jan == 100
    assert qty_feb == 100
    assert qty_mar == 200
    assert qty_jun == 150

def test_asset_annual_dividends_pivot():
    """Verifies that the pivot queries group and sum dividend categories correctly for specific assets and years."""
    # 1. Add BBAS3 dividends in 2025
    TransactionService.add_dividend("BBAS3", "2025-05-15", "Dividendo", 50.00)
    TransactionService.add_dividend("BBAS3", "2025-08-15", "JCP", 30.00)

    # 2. Add CXSE3 dividends in 2025 (should NOT leak into BBAS3 sums)
    TransactionService.add_dividend("CXSE3", "2025-05-15", "Dividendo", 100.00)

    # 3. Add BBAS3 dividends in 2024 (should NOT leak into 2025 sums)
    TransactionService.add_dividend("BBAS3", "2024-05-15", "Dividendo", 15.00)

    df_pivot_bb = TransactionService.get_asset_annual_dividends_pivot("BBAS3", "2025")

    val_div = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de Dividendos', 'Valor (R$)'].values[0]
    val_jcp = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de JCP', 'Valor (R$)'].values[0]
    val_rend = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de Rendimentos', 'Valor (R$)'].values[0]
    val_total = df_pivot_bb.loc[df_pivot_bb['Categoria'] == 'Total de Proventos (Soma de todos)', 'Valor (R$)'].values[0]

    assert val_div == 50.00
    assert val_jcp == 30.00
    assert val_rend == 0.00
    assert val_total == 80.00

def test_get_current_simulation_math():
    """Verifies that the core retirement simulation correctly loads DB config and runs the correct PMT Annuity Due math."""
    # Seed planning_configuration table
    SimulationService.save_configuration(
        birth_date="1992-12-15",
        retirement_age=60,
        desired_income_mw=5.0,
        annual_interest_rate=6.0,
        mw_value=1412.0,
        initial_equity_input=0.0
    )

    # Add a mock transaction to establish starting_age for total_time calculation
    TransactionService.add_transaction("BBAS3", "2021-12-15", "Compra", 10, 10.00)

    sim = SimulationService.get_current_simulation()

    assert sim is not None
    assert sim["retirement_age"] == 60
    assert sim["desired_income_mw"] == 5.0
    assert sim["mw_value"] == 1412.0

    # Target monthly income = 5 * 1412 = 7060
    assert sim["target_monthly_income"] == 7060.0

    # Verify that the calculation returns a valid, positive monthly contribution target
    assert sim["required_monthly_contribution"] > 0.0
    assert sim["total_time_months"] > 0

def test_views_and_services_sanity():
    """
    Automated SCM Sanity and View Import/Attribute Verification Test.
    Ensures all split Views, Component Widgets, and Services are correctly imported
    and that no attributes, methods, or dynamic files are broken or missing.
    """
    # 1. Verify Domain Services imports and critical attributes
    from dashboard.dashboard_service import DashboardService
    assert hasattr(DashboardService, "calculate_positions")
    assert hasattr(DashboardService, "calculate_historical_evolution")
    assert hasattr(DashboardService, "get_ytd_contributions")
    assert hasattr(DashboardService, "get_monthly_contributions_by_year")

    from planning.planning_service import SimulationService
    assert hasattr(SimulationService, "get_configuration")
    assert hasattr(SimulationService, "save_configuration")
    assert hasattr(SimulationService, "get_initial_investment_age")
    assert hasattr(SimulationService, "get_current_simulation")
    assert hasattr(SimulationService, "build_projection_dataframe")
    assert hasattr(SimulationService, "get_updated_required_contribution")
    assert hasattr(SimulationService, "get_required_contribution")

    from lancamentos.transactions_service import TransactionService
    assert hasattr(TransactionService, "add_transaction")
    assert hasattr(TransactionService, "add_dividend")
    assert hasattr(TransactionService, "process_b3_import")
    assert hasattr(TransactionService, "get_quantity_on_date")
    assert hasattr(TransactionService, "get_asset_transactions")
    assert hasattr(TransactionService, "get_asset_dividends")
    assert hasattr(TransactionService, "get_asset_metadata")
    assert hasattr(TransactionService, "get_years_with_dividends")
    assert hasattr(TransactionService, "get_asset_years_with_dividends")
    assert hasattr(TransactionService, "get_annual_dividends_pivot")
    assert hasattr(TransactionService, "get_asset_annual_dividends_pivot")
    assert hasattr(TransactionService, "get_tracked_market_assets")
    assert hasattr(TransactionService, "add_tracked_market_asset")
    assert hasattr(TransactionService, "remove_tracked_market_asset")

    # 2. Verify Domain Views and Coordinator Tabs
    from dashboard.dashboard_view import DashboardView
    assert hasattr(DashboardView, "render")

    from planning.planning_view import PlanningView
    assert hasattr(PlanningView, "render")

    from lancamentos.transactions_view import LancamentosView
    assert hasattr(LancamentosView, "render")

    # 3. Verify Sub-tab Views
    from lancamentos.operations.operations_view import OperationsView
    assert hasattr(OperationsView, "render")

    from lancamentos.assets.assets_view import AssetsView
    assert hasattr(AssetsView, "render")

    # 4. Verify SRP Component Widgets
    from dashboard.components.annual_planning import AnnualPlanningWidget
    assert hasattr(AnnualPlanningWidget, "render")

    from dashboard.components.patrimony_summary import PatrimonySummaryWidget
    assert hasattr(PatrimonySummaryWidget, "render")

    from dashboard.components.detailed_holdings import DetailedHoldingsWidget
    assert hasattr(DetailedHoldingsWidget, "render")

    from dashboard.components.charts import DashboardCharts
    assert hasattr(DashboardCharts, "render")

    from planning.components.time_metrics import TimeMetricsWidget
    assert hasattr(TimeMetricsWidget, "render")

    from planning.components.simulation_results import SimulationResultsWidget
    assert hasattr(SimulationResultsWidget, "render")

    from planning.components.projection_chart import ProjectionChartWidget
    assert hasattr(ProjectionChartWidget, "render")

def test_app_py_static_syntax_sanity():
    """
    Statically analyzes app.py as plaintext to ensure no obsolete calls
    or deleted assets database initialization functions are referenced,
    fully protecting the startup flow before Streamlit boot.
    """
    assert os.path.exists("app.py")
    with open("app.py", "r", encoding="utf-8") as f:
        content = f.read()

    assert "init_assets_db" not in content, "FALHA: O arquivo app.py ainda referencia o método obsoleto 'init_assets_db'!"
    assert "get_assets_connection" not in content, "FALHA: O arquivo app.py ainda referencia a conexão obsoleta 'get_assets_connection'!"

import pytest
import sqlite3
import os
import datetime
import pandas as pd
from core.database import db, DatabaseManager
from services.assets_service import AssetService
from services.planning_service import SimulationService
from core.utils.market_data import MarketData

TEST_PERSONAL_DB = "/tmp/test_portfolio.db"

# Fixture to safely create and remove the test databases and write mock CSV catalog
@pytest.fixture(autouse=True)
def mock_db(monkeypatch):
    if os.path.exists(TEST_PERSONAL_DB):
        try:
            os.remove(TEST_PERSONAL_DB)
        except PermissionError:
            pass

    if os.path.exists("test_assets.csv"):
        try:
            os.remove("test_assets.csv")
        except PermissionError:
            pass

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
        try:
            os.remove("test_assets.csv")
        except PermissionError:
            pass

    # Restore real assets.csv from backup
    if os.path.exists("assets.csv.backup"):
        try:
            import shutil
            shutil.copy("assets.csv.backup", "assets.csv")
            os.remove("assets.csv.backup")
        except PermissionError:
            pass
    elif os.path.exists("assets.csv"):
        try:
            os.remove("assets.csv")
        except PermissionError:
            pass

def test_add_transaction_and_assets_creation():
    """Ensures that the transaction creates the asset using the fallback metadata in the assets csv."""
    if os.path.exists("assets_temp.csv"):
        os.remove("assets_temp.csv")
    import shutil
    shutil.copy("test_assets.csv", "assets.csv")

    AssetService.add_transaction("MOCK4", "2021-04-30", "BUY", 100, 20.00, 5.0)

    df = pd.read_csv("assets.csv", dtype=str, encoding="utf-8-sig").set_index("CÓDIGO")
    assert "MOCK4" in df.index
    assert df.loc["MOCK4", "NOME"] == "Asset MOCK4"

    if os.path.exists("assets.csv"):
        os.remove("assets.csv")

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

def test_b3_excel_importer_logic():
    """Ensures Pandas import logic maps B3 columns and handles liquidations correctly."""
    df_excel = pd.read_excel("tests/b3-mock-transactions.xlsx")

    trans_count, prov_count = AssetService.process_b3_import(df_excel)

    # 1 CDB is ignored, 1 Transfer is ignored.
    # Valid: 1 Buy, 1 Sell, 1 Split (Buy @ 0.0), 1 Redemption (Sell). Total = 4.
    # Dividends: 1 Dividendo, 1 JCP. Total = 2.
    assert trans_count == 4
    assert prov_count == 2

    df_positions = AssetService.calculate_positions()
    assert len(df_positions) == 1
    assert df_positions.loc[0, "quantity"] == 150 # 100 buy + 100 split - 50 sell
    assert round(df_positions.loc[0, "average_price"], 2) == 6.67 # (100 * 20.00 - 50 * 20.00) / 150 = 1000 / 150 = 6.67
    assert df_positions.loc[0, "total_dividends"] == 80.00

def test_b3_importer_deduplication():
    """Ensures running imports consecutively does not duplicate data in SQLite."""
    df_excel = pd.read_excel("tests/b3-mock-transactions.xlsx")

    t1, p1 = AssetService.process_b3_import(df_excel)
    assert t1 == 4
    assert p1 == 2

    t2, p2 = AssetService.process_b3_import(df_excel)
    assert t2 == 0
    assert p2 == 0

    df_positions = AssetService.calculate_positions()
    assert len(df_positions) == 1
    assert df_positions.loc[0, "quantity"] == 150
    assert df_positions.loc[0, "total_dividends"] == 80.00

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

def test_b3_split_logic():
    """Ensures 'Desdobro' events are imported as zero-cost buys, halving average price."""
    AssetService.add_transaction("BBAS3", "2021-04-30", "BUY", 100, 20.00)

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

    trans, prov = AssetService.process_b3_import(df_excel)
    assert trans == 1
    assert prov == 0

    df_pos = AssetService.calculate_positions()
    assert len(df_pos) == 1
    assert df_pos.loc[0, "quantity"] == 200
    assert df_pos.loc[0, "average_price"] == 10.00

def test_b3_resgate_logic():
    """Ensures 'Resgate' events are imported as Sells, bringing quantity to zero."""
    AssetService.add_transaction("NUBR33", "2021-12-10", "BUY", 239, 8.36)

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

    trans, prov = AssetService.process_b3_import(df_excel)
    assert trans == 2
    assert prov == 0

    df_pos = AssetService.calculate_positions()
    assert len(df_pos) == 0

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

def test_get_current_simulation_math():
    """Verifies that the core retirement simulation correctly loads DB config and runs the correct PMT math."""
    SimulationService.save_configuration(
        birth_date="1992-12-15",
        retirement_age=60,
        desired_income_mw=5.0,
        annual_interest_rate=6.0,
        mw_value=1412.0,
        initial_equity_input=0.0
    )
    AssetService.add_transaction("BBAS3", "2021-12-15", "BUY", 10, 10.00)
    sim = SimulationService.get_current_simulation()

    assert sim is not None
    assert sim["retirement_age"] == 60
    assert sim["desired_income_mw"] == 5.0
    assert sim["mw_value"] == 1412.0
    assert sim["target_monthly_income"] == 7060.0
    assert sim["required_monthly_contribution"] > 0.0
    assert sim["total_time_months"] > 0

def test_views_and_services_sanity():
    """Automated SCM Sanity and View Import/Attribute Verification Test."""
    from services.assets_service import AssetService
    assert hasattr(AssetService, "calculate_positions")
    assert hasattr(AssetService, "calculate_historical_evolution")
    assert hasattr(AssetService, "get_ytd_contributions")
    assert hasattr(AssetService, "get_monthly_contributions_by_year")

    from services.planning_service import SimulationService
    assert hasattr(SimulationService, "get_configuration")
    assert hasattr(SimulationService, "save_configuration")
    assert hasattr(SimulationService, "get_initial_investment_age")
    assert hasattr(SimulationService, "get_current_simulation")
    assert hasattr(SimulationService, "build_projection_dataframe")
    assert hasattr(SimulationService, "get_updated_required_contribution")
    assert hasattr(SimulationService, "get_required_contribution")

    from services.assets_service import AssetService
    assert hasattr(AssetService, "add_transaction")
    assert hasattr(AssetService, "add_dividend")
    assert hasattr(AssetService, "process_b3_import")
    assert hasattr(AssetService, "get_quantity_on_date")
    assert hasattr(AssetService, "get_asset_transactions")
    assert hasattr(AssetService, "get_asset_dividends")
    assert hasattr(AssetService, "get_asset_metadata")
    assert hasattr(AssetService, "get_years_with_dividends")
    assert hasattr(AssetService, "get_asset_years_with_dividends")
    assert hasattr(AssetService, "get_annual_dividends_pivot")
    assert hasattr(AssetService, "get_asset_annual_dividends_pivot")
    assert hasattr(AssetService, "get_tracked_market_assets")
    assert hasattr(AssetService, "add_tracked_market_asset")
    assert hasattr(AssetService, "remove_tracked_market_asset")

    from views.dashboard_view import DashboardView
    assert hasattr(DashboardView, "render")

    from views.planning_view import PlanningView
    assert hasattr(PlanningView, "render")

    from views.assets_view import AssetsView
    assert hasattr(AssetsView, "render")

    from views.operations_view import OperationsView
    assert hasattr(OperationsView, "render")

    from views.portfolio_view import PortfolioView
    assert hasattr(PortfolioView, "render")

    from views.market_view import MarketView
    assert hasattr(MarketView, "render")

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

def test_views_static_db_imports_sanity():
    """
    Statically analyzes all visual view files inside views/ directory.
    Ensures that if 'db' is referenced in a file, 'from core.database import db'
    must also be imported in that file, preventing dynamic NameErrors.
    """
    views_dir = "views"
    assert os.path.exists(views_dir)

    # Loop through view files
    for file_name in os.listdir(views_dir):
        file_path = os.path.join(views_dir, file_name)
        if os.path.isfile(file_path) and file_name.endswith(".py"):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # If 'db' is used (e.g. calling db.get_personal_connection() or db.X),
            # verify that the database connection object was imported
            if " db." in content or "=db." in content:
                assert "from core.database import db" in content, (
                    f"FALHA: O arquivo {file_path} referencia o objeto de banco 'db', "
                    f"mas não importa 'from core.database import db'!"
                )

def test_views_no_duplicate_widget_keys_sanity():
    """
    Statically analyzes all visual view files inside views/ directory and sub-directories.
    Extracts all occurrences of key="..." or key='...' and asserts that within
    any single file, there are absolutely zero duplicate Streamlit widget keys,
    completely preventing StreamlitDuplicateElementKey exceptions.
    """
    import re
    views_dir = "views"
    assert os.path.exists(views_dir)

    # Simple regex to extract widget keys like key="my_key" or key='my_key'
    key_pattern = re.compile(r"key\s*=\s*['\"]([^'\"]+)['\"]")

    # Recursively traverse views/ directory
    for root, dirs, files in os.walk(views_dir):
        for file_name in files:
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                found_keys = key_pattern.findall(content)

                # Check for duplicates inside this file
                seen_keys = set()
                duplicates = []
                for k in found_keys:
                    if k in seen_keys:
                        duplicates.append(k)
                    seen_keys.add(k)

                assert len(duplicates) == 0, (
                    f"FALHA: O arquivo {file_path} possui chaves de widgets duplicadas: {duplicates}! "
                    f"Cada widget Streamlit em um mesmo arquivo deve possuir uma chave 'key' única."
                )

def test_views_session_state_persistent_keys_sanity():
    """
    Statically analyzes views/planning_view.py to ensure that unmountable, toggled
    widgets (like desired_income_mw and desired_income_fixed) do not bind directly
    as widget keys in st.session_state (which Streamlit deletes upon unmounting).
    Verifies that they utilize protected '_val' keys as their source of truth.
    """
    assert os.path.exists("views/planning_view.py")
    with open("views/planning_view.py", "r", encoding="utf-8") as f:
        content = f.read()

    assert "key=\"desired_income_mw\"" not in content, (
        "FALHA: O arquivo views/planning_view.py ainda vincula diretamente a chave 'desired_income_mw' como chave de widget! "
        "Use 'desired_income_mw_input' e salve o valor dinamicamente para evitar exclusões do Streamlit no unmount."
    )
    assert "key=\"desired_income_fixed\"" not in content, (
        "FALHA: O arquivo views/planning_view.py ainda vincula diretamente a chave 'desired_income_fixed' como chave de widget! "
        "Use 'desired_income_fixed_input' e salve o valor dinamicamente para evitar exclusões do Streamlit no unmount."
    )

def test_formatter_colored_cell_style_dry_sanity():
    """
    Verifies that Formatter.get_colored_cell_style and Formatter.get_trend_cell_style
    return the correct high-contrast CSS color tags depending on Bazin price-to-ceiling margins
    and positive/negative trends (DRY contract sanity).
    """
    from core.utils.formatter import Formatter

    # 1. Price is cheap/muy barato (<= 80% of ceiling) -> Green
    style_green = Formatter.get_colored_cell_style(price=30.0, ceiling=50.0)
    assert "rgba(40, 167, 69, 0.25)" in style_green
    assert "font-weight: bold" in style_green

    # 2. Price is fair/abaixo (<= 100% of ceiling) -> Yellow
    style_yellow = Formatter.get_colored_cell_style(price=45.0, ceiling=50.0)
    assert "rgba(255, 193, 7, 0.25)" in style_yellow

    # 3. Price is expensive (> ceiling) -> Red
    style_red = Formatter.get_colored_cell_style(price=55.0, ceiling=50.0)
    assert "rgba(220, 53, 69, 0.25)" in style_red

    # 4. Ceiling is invalid (<= 0.0) -> Transparent
    style_trans = Formatter.get_colored_cell_style(price=30.0, ceiling=0.0)
    assert "transparent" in style_trans

    # 5. Trend is positive -> Green
    trend_green = Formatter.get_trend_cell_style(15.5)
    assert "rgba(40, 167, 69, 0.25)" in trend_green

    # 6. Trend is negative -> Red
    trend_red = Formatter.get_trend_cell_style(-3.2)
    assert "rgba(220, 53, 69, 0.25)" in trend_red

    # 7. Trend is neutral -> Transparent
    trend_neutral = Formatter.get_trend_cell_style(0.0)
    assert "transparent" in trend_neutral

def test_get_ticker_market_analysis(monkeypatch):
    """
    Verifies that get_ticker_market_analysis correctly parses and calculates market data.
    In particular, checks that the dividend yield (dy) is NOT multiplied by 100 if yfinance
    already returns it as a percentage (e.g. 1.2 for BBAS3 instead of 0.012).
    """
    import pandas as pd
    from core.utils.market_data import MarketData

    class MockTicker:
        def __init__(self, ticker_name):
            self.info = {
                "longName": "Banco do Brasil S.A.",
                "priceToBook": 0.85,
                "trailingPE": 4.5,
                "dividendYield": 1.2,  # Already percentage (1.2%)
                "returnOnEquity": 0.09224  # Decimal fraction (9.224%)
            }
            self.fast_info = {
                "yearLow": 15.0,
                "yearHigh": 30.0,
                "lastPrice": 19.86
            }
            self.dividends = pd.Series(dtype=float)

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # Call get_ticker_market_analysis for a mock ticker
    analysis = MarketData.get_ticker_market_analysis("BBAS3")

    # Assertions
    assert analysis["name"] == "Banco do Brasil S.A."
    assert analysis["current_price"] == 19.86
    assert analysis["pb"] == 0.85
    assert analysis["pe"] == 4.5
    assert analysis["roe"] == 9.224  # Should be multiplied by 100 since ROE is a decimal fraction
    assert analysis["dy"] == 1.2      # Should be exactly 1.2, NOT 120.0

def test_get_ticker_market_analysis_normalization(monkeypatch):
    """
    Verifies that get_ticker_market_analysis correctly normalizes the ticker parameter
    (converting to uppercase and stripping whitespace) before performing any database queries.
    """
    import pandas as pd
    from core.utils.market_data import MarketData
    from core.database import db

    class MockTicker:
        def __init__(self, ticker_name):
            assert "BBAS3.SA" in ticker_name
            self.info = {
                "longName": "Banco do Brasil S.A.",
                "priceToBook": 0.85,
                "trailingPE": 4.5,
                "dividendYield": 1.2,
                "returnOnEquity": 0.09224
            }
            self.fast_info = {
                "yearLow": 15.0,
                "yearHigh": 30.0,
                "lastPrice": 19.86
            }
            s = pd.Series({
                pd.Timestamp("2024-01-01"): 1.50
            })
            s.index.name = "Date"
            s.name = "Dividends"
            self.dividends = s

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", MockTicker)

    # Pre-seed a specific correction for BBAS3 in the database
    conn = db.get_personal_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO dividend_corrections (ticker, year, total_value) VALUES ('BBAS3', 2024, 2.50)")
    conn.commit()
    conn.close()

    # Clear cache to avoid hits from previous tests
    MarketData.get_ticker_market_analysis.clear()

    # Call with unnormalized ticker: lowercase and with spaces
    analysis = MarketData.get_ticker_market_analysis("  bbas3   ")

    # Assertions
    assert analysis["dividends_5y"][2024] == 2.50  # Should be the corrected value, not the yfinance one (1.50)

def test_market_data_bcb_indicators_sanity():
    """
    Verifies that MarketData SGS API integration methods (for IPCA and SELIC)
    compile, handle cache clearings, and return valid positive financial indicators.
    """
    from core.utils.market_data import MarketData
    
    MarketData.get_current_ipca_l12m.clear()
    ipca_val = MarketData.get_current_ipca_l12m()
    assert isinstance(ipca_val, float)
    assert ipca_val > 0.0

    MarketData.get_current_selic.clear()
    selic_val = MarketData.get_current_selic()
    assert isinstance(selic_val, float)
    assert selic_val > 0.0

def test_views_static_market_data_methods_sanity():
    """
    Statically analyzes all files inside views/ (including sub-folders) to ensure
    any referenced 'MarketData.[method]' call corresponds to an actual, valid method
    inside the core MarketData class. Completely prevents dynamic AttributeErrors.
    """
    import re
    from core.utils.market_data import MarketData
    
    # 1. Dynamically retrieve all public/callable method names from MarketData
    valid_methods = {name for name in dir(MarketData) if not name.startswith("_")}
    
    # 2. Setup regex to capture 'MarketData.some_method' calls
    call_pattern = re.compile(r"MarketData\.([a-zA-Z0-9_]+)")
    
    views_dir = "views"
    assert os.path.exists(views_dir)
    
    # Traverse views directory
    for root, dirs, files in os.walk(views_dir):
        for file_name in files:
            if file_name.endswith(".py"):
                file_path = os.path.join(root, file_name)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                matches = call_pattern.findall(content)
                for called_method in matches:
                    assert called_method in valid_methods, (
                        f"FALHA: O arquivo {file_path} tenta chamar 'MarketData.{called_method}()', "
                        f"mas esse método não existe na classe MarketData! Métodos válidos: {valid_methods}"
                    )


def test_get_app_version_sanity(monkeypatch, tmp_path):
    """
    Verifies that get_app_version() correctly reads version.txt from either
    the standard folder or the PyInstaller sys._MEIPASS temporary directory.
    """
    from core.utils.session import get_app_version
    import sys
    import os

    # Test 1: Standard environment (dev)
    # Ensure it reads 'version.txt' from current directory
    assert get_app_version() == "1.0.0"

    # Test 2: PyInstaller environment (sys._MEIPASS mocked)
    mock_meipass = str(tmp_path)
    version_file = tmp_path / "version.txt"
    version_file.write_text("2.3.4.5", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", mock_meipass, raising=False)
    assert get_app_version() == "2.3.4.5"


def test_monitor_active_sessions_stop_trigger(monkeypatch):
    """
    Verifies that monitor_active_sessions() cleanly stops the Streamlit runtime
    when the active session count drops from positive to zero.
    """
    from core.utils.session import monitor_active_sessions
    import time

    # Mock time.sleep to return immediately so the test runs instantly
    monkeypatch.setattr(time, "sleep", lambda x: None)

    # Mock Streamlit Runtime and session manager
    class MockSession:
        def __init__(self, session_id):
            self.id = session_id

    class MockSessionManager:
        def __init__(self):
            # Start with 1 session, then drop to 0 on the second call
            self.call_count = 0

        def list_sessions(self):
            self.call_count += 1
            if self.call_count == 1:
                return [MockSession("session_1")]
            return [] # 0 sessions

    class MockRuntime:
        def __init__(self):
            self._session_mgr = MockSessionManager()
            self.stopped = False

        def stop(self):
            self.stopped = True

    mock_runtime = MockRuntime()

    # Mock get_instance to return our mocked Runtime
    monkeypatch.setattr("streamlit.runtime.get_instance", lambda: mock_runtime)

    # Run the monitor loop (it will terminate because runtime.stop() is called, breaking the loop)
    monitor_active_sessions()

    assert mock_runtime.stopped is True

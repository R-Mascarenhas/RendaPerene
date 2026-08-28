import pytest
import os
import pandas as pd
from core.database import db, DatabaseManager
from core.daos.planning_dao import PlanningDAO
from core.utils.market_data import MarketData

TEST_PERSONAL_DB = "/tmp/test_portfolio.db"

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

    # Wire default test adapters at the test environment composition edge
    from services.assets_service import AssetService
    from services.goals_service import GoalService
    from services.planning_service import SimulationService
    from services.share_quantity_goal_service import ShareQuantityGoalService
    from core.utils.b3_parser import B3ExcelParserAdapter
    AssetService.set_adapters(
        portfolio_repo=None,
        catalog_repo=None,
        market_data_api=MarketData,
        excel_parser=B3ExcelParserAdapter(),
        planning_provider=SimulationService.get_default(),
    )
    SimulationService.set_adapters(portfolio_provider=AssetService.get_default())
    GoalService.set_adapters(
        settings_repo=PlanningDAO(),
        portfolio_provider=AssetService.get_default(),
        planning_provider=SimulationService.get_default(),
    )
    ShareQuantityGoalService.set_adapters(
        goal_repo=PlanningDAO(),
        settings_repo=PlanningDAO(),
        portfolio_provider=AssetService.get_default(),
        market_data_api=MarketData,
        planning_provider=SimulationService.get_default(),
    )

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

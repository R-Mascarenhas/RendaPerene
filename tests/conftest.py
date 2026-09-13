import pytest

from core.daos.assets_catalog_dao import AssetsCatalogDAO
from core.daos.planning_dao import PlanningDAO
from core.daos.portfolio_dao import PortfolioDAO
from core.database import DatabaseManager, db
from core.utils.market_data import MarketData


@pytest.fixture(autouse=True)
def mock_db(monkeypatch, tmp_path):
    test_database = tmp_path / "test_portfolio.db"
    test_catalog = tmp_path / "test_assets.csv"
    test_db = DatabaseManager(test_database)
    test_db.init_personal_db()

    # Write a clean mock assets.csv for the tests
    test_csv_content = (
        "CÓDIGO,NOME,IMAGEM,CNPJ,SETOR ECONÔMICO,SUBSETOR ,SEGMENTO / ADM / PAÍS,TIPO,SEGMENTO\n"
        "BBAS3,Banco do Brasil,https://...,00.000.000/0001-91,Financeiro,Intermediários,Bancos,Ação,Bancos\n"
        "CXSE3,Caixa Seguridade,https://...,00.000.000/0001-92,Seguridade,Seguros,Seguridade,Ação,Seguros\n"
    )
    test_catalog.write_text(test_csv_content, encoding="utf-8-sig")
    catalog_repo = AssetsCatalogDAO(test_catalog)

    def mock_load_catalog():
        return catalog_repo.load_catalog()

    # Redirect global db instance to use the test database
    monkeypatch.setattr(db, "get_personal_connection", test_db.get_personal_connection)
    monkeypatch.setattr(MarketData, "load_assets_catalog", mock_load_catalog)

    # Wire default test adapters at the test environment composition edge
    from services.assets_service import AssetService
    from services.goals_service import GoalService
    from services.market_analysis_service import MarketAnalysisService
    from services.planning_service import SimulationService
    from services.share_quantity_goal_service import ShareQuantityGoalService
    from core.utils.b3_parser import B3ExcelParserAdapter

    monkeypatch.setattr("services.assets_service.AssetsCatalogDAO", lambda: catalog_repo)
    portfolio_repo = PortfolioDAO()
    market_analysis = MarketAnalysisService(MarketData, portfolio_repo)
    AssetService.set_adapters(
        portfolio_repo=portfolio_repo,
        catalog_repo=catalog_repo,
        market_data_api=MarketData,
        market_analysis_api=market_analysis,
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
        market_analysis_api=market_analysis,
        planning_provider=SimulationService.get_default(),
    )

    yield {"catalog_path": test_catalog, "database_path": test_database}

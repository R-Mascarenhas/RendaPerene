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
    original_load_assets_catalog = MarketData.load_assets_catalog

    def mock_load_catalog():
        return catalog_repo.load_catalog()

    # Redirect global db instance to use the test database
    monkeypatch.setattr(db, "get_personal_connection", test_db.get_personal_connection)
    monkeypatch.setattr(db, "get_personal_database_path", test_db.get_personal_database_path)
    monkeypatch.setattr(MarketData, "load_assets_catalog", mock_load_catalog)

    # Wire default test adapters at the test environment composition edge
    from services.assets_service import AssetService
    from services.goals_service import GoalService
    from services.market_analysis_service import MarketAnalysisService
    from services.planning_service import SimulationService
    from services.share_quantity_goal_service import ShareQuantityGoalService
    from core.utils.b3_parser import B3ExcelParserAdapter

    portfolio_repo = PortfolioDAO()
    market_analysis = MarketAnalysisService(MarketData, portfolio_repo)
    AssetService.set_adapters(
        portfolio_repo=portfolio_repo,
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

    # Each test owns its background cache; no job may outlive monkeypatched sources.
    from core.background_market_data import BackgroundMarketData
    from core.market_data_cache import MarketDataCache
    import views.cached_market_data as cached_market_data

    monkeypatch.setitem(cached_market_data._cache_configuration, "path", None)

    background_instances = []

    def get_test_background_market_data():
        if not background_instances:
            background_instances.append(BackgroundMarketData(MarketData, MarketDataCache()))
        return background_instances[0]

    monkeypatch.setattr(cached_market_data, "get_background_market_data", get_test_background_market_data)

    yield {
        "catalog_path": test_catalog,
        "database_path": test_database,
        "original_load_assets_catalog": original_load_assets_catalog,
    }
    for background in background_instances:
        try:
            assert background.cache.wait_idle(10), "Background source did not finish before test teardown"
        finally:
            background.cache.close()

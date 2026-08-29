import sqlite3
from contextvars import ContextVar
from pathlib import Path

from core.application_paths import ApplicationPaths
from core.daos.assets_catalog_dao import AssetsCatalogDAO
from core.database import DatabaseManager
from core.utils.market_data import MarketData


def create_database(path: Path, value: str = "original") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def write_catalog(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "CÓDIGO,NOME,IMAGEM,CNPJ,SETOR ECONÔMICO,SUBSETOR ,"
        "SEGMENTO / ADM / PAÍS,TIPO,SEGMENTO\n"
    )
    contents = header + "".join(
        f"{ticker},{name},,,,Outros,,Ação,\n" for ticker, name in rows
    )
    path.write_text(contents, encoding="utf-8-sig")


def test_discovers_linux_xdg_data_directory(monkeypatch, tmp_path):
    xdg_data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))

    paths = ApplicationPaths.discover(system="linux")

    assert paths.data_root == xdg_data_home / "RendaPerene"
    assert paths.database_dir == xdg_data_home / "RendaPerene" / "database"
    assert paths.catalog_file == xdg_data_home / "RendaPerene" / "catalog" / "assets.csv"
    assert paths.logs_dir == xdg_data_home / "RendaPerene" / "logs"
    assert paths.backups_dir == xdg_data_home / "RendaPerene" / "backups"


def test_discovers_linux_home_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    paths = ApplicationPaths.discover(system="linux")

    assert paths.data_root == tmp_path / ".local" / "share" / "RendaPerene"


def test_discovers_windows_local_app_data_directory(monkeypatch, tmp_path):
    local_app_data = tmp_path / "AppData" / "Local"
    monkeypatch.setattr(
        "platformdirs.windows.get_win_folder", lambda _name: str(local_app_data)
    )

    paths = ApplicationPaths.discover(system="win32")

    assert paths.data_root == local_app_data / "RendaPerene"
    assert paths.database_dir == local_app_data / "RendaPerene" / "database"


def test_successful_legacy_migration_is_copy_only_backed_up_and_idempotent(tmp_path):
    resource_root = tmp_path / "application"
    data_root = tmp_path / "user-data"
    source = resource_root / "database" / "portfolio_family.db"
    create_database(source)
    paths = ApplicationPaths(resource_root, data_root, resource_root)
    paths.prepare()

    result = paths.migrate_legacy_database(source)

    assert result.migrated is True
    assert source.exists()
    assert result.destination.exists()
    assert result.backup is not None
    assert result.backup.exists()
    assert source.read_bytes() == result.destination.read_bytes() == result.backup.read_bytes()
    assert paths.inspect_portfolios().valid == (result.destination,)

    repeated = paths.migrate_legacy_database(source)

    assert repeated.migrated is False
    assert "já foi importada" in repeated.message
    assert source.read_bytes() == result.destination.read_bytes()


def test_invalid_legacy_database_is_rejected_before_copy(tmp_path):
    resource_root = tmp_path / "application"
    data_root = tmp_path / "user-data"
    source = resource_root / "database" / "portfolio_broken.db"
    source.parent.mkdir(parents=True)
    source.write_text("not sqlite", encoding="utf-8")
    paths = ApplicationPaths(resource_root, data_root, resource_root)
    paths.prepare()

    result = paths.migrate_legacy_database(source)

    assert result.migrated is False
    assert "não é um banco SQLite válido" in result.message
    assert source.exists()
    assert not result.destination.exists()
    assert result.backup is None


def test_migration_refuses_to_overwrite_a_different_portfolio(tmp_path):
    resource_root = tmp_path / "application"
    data_root = tmp_path / "user-data"
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths = ApplicationPaths(resource_root, data_root, resource_root)
    paths.prepare()
    destination = paths.portfolio_database("portfolio.db")
    create_database(destination, "current")
    original_destination = destination.read_bytes()

    result = paths.migrate_legacy_database(source)

    assert result.migrated is False
    assert "nenhum arquivo foi sobrescrito" in result.message
    assert destination.read_bytes() == original_destination
    assert result.backup is None


def test_legacy_main_remains_importable_after_empty_default_database_is_initialized(tmp_path):
    resource_root = tmp_path / "application"
    data_root = tmp_path / "user-data"
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy-main")
    paths = ApplicationPaths(resource_root, data_root, resource_root)
    paths.prepare()
    destination = paths.portfolio_database("portfolio.db")
    DatabaseManager(destination).init_personal_db()

    assert source in paths.migration_candidates()

    result = paths.migrate_legacy_database(source)

    assert result.migrated is True
    assert destination.read_bytes() == source.read_bytes()
    assert result.backup == paths.backups_dir / "legacy-import" / "portfolio.db"
    assert ApplicationPaths.is_valid_sqlite(result.backup)
    assert not (paths.backups_dir / "pre-migration").exists()


def test_legacy_main_cannot_replace_an_initialized_database_with_user_settings(tmp_path):
    resource_root = tmp_path / "application"
    data_root = tmp_path / "user-data"
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy-main")
    paths = ApplicationPaths(resource_root, data_root, resource_root)
    paths.prepare()
    destination = paths.portfolio_database("portfolio.db")
    DatabaseManager(destination).init_personal_db()
    connection = sqlite3.connect(destination)
    try:
        connection.execute("UPDATE goal_settings SET reinvest_dividends_enabled = 0 WHERE id = 1")
        connection.commit()
    finally:
        connection.close()
    current_contents = destination.read_bytes()

    assert source not in paths.migration_candidates()

    result = paths.migrate_legacy_database(source)

    assert result.migrated is False
    assert "nenhum arquivo foi sobrescrito" in result.message
    assert destination.read_bytes() == current_contents


def test_demo_session_uses_an_isolated_seeded_database(tmp_path, monkeypatch):
    resource_root = tmp_path / "application"
    source = resource_root / "database" / "portfolio_demo.db"
    create_database(source, "demo")
    monkeypatch.setattr("core.application_paths.tempfile.gettempdir", lambda: str(tmp_path))
    paths = ApplicationPaths(resource_root, tmp_path / "unused", resource_root)

    demo_paths = paths.for_demo_session("session-123")
    demo_paths.prepare(source)

    destination = demo_paths.portfolio_database("portfolio.db")
    assert demo_paths.data_root == tmp_path / "RendaPerene" / "demo" / "session-123"
    assert destination.exists()
    assert destination.read_bytes() == source.read_bytes()


def test_database_manager_resolves_the_current_session_path_for_each_connection(tmp_path):
    session_database = ContextVar("session_database")
    manager = DatabaseManager(lambda: session_database.get())
    first_database = tmp_path / "first" / "portfolio.db"
    second_database = tmp_path / "second" / "portfolio.db"

    session_database.set(first_database)
    first_connection = manager.get_personal_connection()
    first_connection.execute("CREATE TABLE session_marker (value TEXT NOT NULL)")
    first_connection.execute("INSERT INTO session_marker VALUES ('first')")
    first_connection.commit()
    first_connection.close()

    session_database.set(second_database)
    second_connection = manager.get_personal_connection()
    second_connection.execute("CREATE TABLE session_marker (value TEXT NOT NULL)")
    second_connection.execute("INSERT INTO session_marker VALUES ('second')")
    second_connection.commit()
    second_connection.close()

    session_database.set(first_database)
    first_connection = manager.get_personal_connection()
    try:
        assert first_connection.execute("SELECT value FROM session_marker").fetchone() == (
            "first",
        )
    finally:
        first_connection.close()


def test_catalog_repository_resolves_the_current_demo_session_for_each_operation(tmp_path):
    from views.cached_market_data import StreamlitCachedMarketData

    session_catalog = ContextVar("session_catalog")
    repository = AssetsCatalogDAO(lambda: session_catalog.get())
    first_catalog = tmp_path / "first" / "assets.csv"
    second_catalog = tmp_path / "second" / "assets.csv"
    write_catalog(first_catalog, [("BASE3", "Base")])
    write_catalog(second_catalog, [("BASE3", "Base")])
    original_catalog_path = MarketData._catalog_path
    MarketData.configure_catalog(lambda: session_catalog.get())

    try:
        session_catalog.set(first_catalog)
        repository.add_fallback_asset("FIRST3")
        assert MarketData.resolve_catalog_path() == first_catalog
        session_catalog.set(second_catalog)
        repository.add_fallback_asset("SECOND3")
        assert MarketData.resolve_catalog_path() == second_catalog

        session_catalog.set(first_catalog)
        first_tickers = set(repository.load_catalog().index)
        first_cached_tickers = set(StreamlitCachedMarketData.load_assets_catalog().index)
        session_catalog.set(second_catalog)
        second_tickers = set(repository.load_catalog().index)
        second_cached_tickers = set(StreamlitCachedMarketData.load_assets_catalog().index)
    finally:
        MarketData.configure_catalog(original_catalog_path)

    assert "FIRST3" in first_tickers
    assert "SECOND3" not in first_tickers
    assert "SECOND3" in second_tickers
    assert "FIRST3" not in second_tickers
    assert first_cached_tickers == first_tickers
    assert second_cached_tickers == second_tickers


def test_prepare_merges_new_catalog_baseline_while_preserving_user_rows(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    bundled_catalog = resource_root / "assets.csv"
    write_catalog(bundled_catalog, [("BASE3", "Old metadata")])
    paths.prepare()
    catalog_repository = AssetsCatalogDAO(paths.catalog_file)
    catalog_repository.add_fallback_asset("USER3")

    write_catalog(
        bundled_catalog,
        [("BASE3", "Updated metadata"), ("NEW3", "New bundled asset")],
    )
    paths.prepare()

    catalog = catalog_repository.load_catalog()
    assert catalog.loc["BASE3", "NOME"] == "Updated metadata"
    assert catalog.loc["NEW3", "NOME"] == "New bundled asset"
    assert "USER3" in catalog.index


def test_choose_portfolio_falls_back_to_a_valid_alternative_when_default_is_invalid(tmp_path):
    paths = ApplicationPaths(tmp_path, tmp_path / "user-data", tmp_path)
    paths.prepare()
    paths.portfolio_database("portfolio.db").write_text("invalid", encoding="utf-8")
    alternative = paths.portfolio_database("portfolio_family.db")
    create_database(alternative)
    inventory = paths.inspect_portfolios()

    selected = paths.choose_portfolio("portfolio.db", [path.name for path in inventory.valid])

    assert selected == "portfolio_family.db"

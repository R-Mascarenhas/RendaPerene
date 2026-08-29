import sqlite3
from pathlib import Path

from core.application_paths import ApplicationPaths
from core.database import DatabaseManager


def create_database(path: Path, value: str = "original") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


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

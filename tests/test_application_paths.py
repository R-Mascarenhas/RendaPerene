import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from core.application_paths import ApplicationPaths, portfolio_database_lock
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
        "CÓDIGO,NOME,IMAGEM,CNPJ,SETOR ECONÔMICO,SUBSETOR ,SEGMENTO / ADM / PAÍS,TIPO,SEGMENTO\n"
    )
    contents = header + "".join(f"{ticker},{name},,,,Outros,,Ação,\n" for ticker, name in rows)
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
    monkeypatch.setattr("platformdirs.windows.get_win_folder", lambda _name: str(local_app_data))

    paths = ApplicationPaths.discover(system="win32")

    assert paths.data_root == local_app_data / "RendaPerene"
    assert paths.database_dir == local_app_data / "RendaPerene" / "database"


def test_frozen_windows_discovers_portfolios_in_previous_release_directory(monkeypatch, tmp_path):
    releases_root = tmp_path / "releases"
    previous_release = releases_root / "RendaPerene-v2.0.0"
    current_release = releases_root / "RendaPerene-v2.1.0"
    legacy_database = previous_release / "database" / "portfolio.db"
    create_database(legacy_database, "previous-release")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(current_release / "RendaPerene-v2.1.0.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(
        "platformdirs.windows.get_win_folder",
        lambda _name: str(tmp_path / "AppData" / "Local"),
    )

    paths = ApplicationPaths.discover(system="win32")

    assert legacy_database in paths.legacy_databases()
    assert legacy_database in paths.migration_candidates()


def test_legacy_discovery_prefers_newest_release_for_duplicate_portfolio_names(tmp_path):
    releases_root = tmp_path / "releases"
    older_database = releases_root / "RendaPerene-v2.9.0" / "database" / "portfolio.db"
    newer_database = releases_root / "RendaPerene-v2.10.0" / "database" / "portfolio.db"
    create_database(older_database, "older")
    create_database(newer_database, "newer")
    paths = ApplicationPaths(
        tmp_path / "bundle",
        tmp_path / "user-data",
        releases_root / "RendaPerene-v3.0.0",
    )

    assert paths.legacy_databases() == (newer_database,)


def test_legacy_discovery_uses_older_valid_duplicate_when_newest_is_invalid(tmp_path):
    releases_root = tmp_path / "releases"
    older_database = releases_root / "RendaPerene-v2.9.0" / "database" / "portfolio.db"
    newer_database = releases_root / "RendaPerene-v2.10.0" / "database" / "portfolio.db"
    create_database(older_database, "valid")
    newer_database.parent.mkdir(parents=True)
    newer_database.write_text("invalid", encoding="utf-8")
    paths = ApplicationPaths(
        tmp_path / "bundle",
        tmp_path / "user-data",
        releases_root / "RendaPerene-v3.0.0",
    )

    assert paths.legacy_databases() == (older_database,)


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
    assert ApplicationPaths.is_valid_sqlite(result.destination)
    assert ApplicationPaths.is_valid_sqlite(result.backup)
    assert paths.inspect_portfolios().valid == (result.destination,)

    repeated = paths.migrate_legacy_database(source)

    assert repeated.migrated is False
    assert "já foi importada" in repeated.message


def test_legacy_migration_reuses_logically_equal_backup_after_failed_publication(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_family.db"
    create_database(source)
    paths.prepare()
    backup = paths.backups_dir / "legacy-import" / source.name
    ApplicationPaths._safe_copy(source, backup, validate_sqlite=True)
    connection = sqlite3.connect(backup)
    try:
        connection.execute("INSERT INTO marker VALUES ('temporary')")
        connection.execute("DELETE FROM marker WHERE value = 'temporary'")
        connection.commit()
    finally:
        connection.close()

    assert source.read_bytes() != backup.read_bytes()

    result = paths.migrate_legacy_database(source)

    assert result.migrated is True
    assert result.backup == backup
    assert ApplicationPaths._same_sqlite_contents(source, result.destination)


def test_sqlite_content_comparison_includes_committed_wal_pages(tmp_path):
    source = tmp_path / "portfolio.db"
    backup = tmp_path / "portfolio_backup.db"
    create_database(source)
    writer = sqlite3.connect(source)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        backup.write_bytes(source.read_bytes())
        writer.execute("INSERT INTO marker VALUES ('committed-in-wal')")
        writer.commit()

        assert source.read_bytes() == backup.read_bytes()
        assert Path(f"{source}-wal").exists()
        assert ApplicationPaths._same_sqlite_contents(source, backup) is False
    finally:
        writer.close()


def test_sqlite_content_digest_reuses_unchanged_file_metadata(tmp_path, monkeypatch):
    database = tmp_path / "portfolio.db"
    create_database(database)
    real_connect = sqlite3.connect
    connect_calls = 0

    def counted_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("core.application_paths.sqlite3.connect", counted_connect)
    ApplicationPaths._sqlite_content_digest(database)
    ApplicationPaths._sqlite_content_digest(database)

    assert connect_calls == 1


def test_migration_publication_waits_for_database_connections_and_revalidates(
    tmp_path, monkeypatch
):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths.prepare()
    destination = paths.portfolio_database("portfolio.db")
    manager = DatabaseManager(destination)
    manager.init_personal_db()
    connection = manager.get_personal_connection()
    connection.execute("UPDATE goal_settings SET reinvest_dividends_enabled = 0 WHERE id = 1")
    lock_attempted = threading.Event()
    real_lock = portfolio_database_lock

    @contextmanager
    def observed_lock(database):
        lock_attempted.set()
        with real_lock(database):
            yield

    monkeypatch.setattr("core.application_paths.portfolio_database_lock", observed_lock)
    results = []
    migration = threading.Thread(
        target=lambda: results.append(paths.migrate_legacy_database(source))
    )
    migration.start()
    try:
        assert lock_attempted.wait(timeout=2)
        assert migration.is_alive()
        connection.commit()
    finally:
        connection.close()
    migration.join(timeout=5)

    assert not migration.is_alive()
    assert results[0].migrated is False
    assert "mudou durante a importação" in results[0].message
    verification = sqlite3.connect(destination)
    try:
        assert verification.execute(
            "SELECT reinvest_dividends_enabled FROM goal_settings WHERE id = 1"
        ).fetchone() == (0,)
    finally:
        verification.close()


def test_migration_copy_failures_return_only_localized_user_text(tmp_path, monkeypatch):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_family.db"
    create_database(source)
    paths.prepare()

    def fail_copy(*_args, **_kwargs):
        raise ValueError("The copied file failed SQLite validation.")

    monkeypatch.setattr(ApplicationPaths, "_safe_copy", staticmethod(fail_copy))

    result = paths.migrate_legacy_database(source)

    assert result.migrated is False
    assert result.message == (
        "Não foi possível copiar a carteira. "
        "Verifique as permissões de armazenamento e tente novamente."
    )
    assert "copied file" not in result.message


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
    assert ApplicationPaths.is_valid_sqlite(destination)
    assert not Path(f"{destination}-wal").exists()
    assert not Path(f"{destination}-shm").exists()
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


def test_migrated_pristine_portfolio_is_not_reoffered_after_schema_metadata_changes(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    DatabaseManager(source).init_personal_db()
    paths.prepare()

    result = paths.migrate_legacy_database(source)
    connection = sqlite3.connect(result.destination)
    try:
        connection.execute("PRAGMA user_version = 1")
    finally:
        connection.close()

    assert result.migrated is True
    assert source.read_bytes() != result.destination.read_bytes()
    assert paths._is_pristine_database(result.destination)
    repeated = paths.migrate_legacy_database(source)
    assert repeated.migrated is False
    assert "já foi importada" in repeated.message
    assert source not in paths.migration_candidates()


def test_changed_legacy_source_is_not_hidden_by_an_old_completion_marker(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    DatabaseManager(source).init_personal_db()
    paths.prepare()
    result = paths.migrate_legacy_database(source)
    connection = sqlite3.connect(source)
    try:
        connection.execute("UPDATE goal_settings SET reinvest_dividends_enabled = 0 WHERE id = 1")
        connection.commit()
    finally:
        connection.close()

    assert result.migrated is True
    assert source in paths.migration_candidates()
    repeated = paths.migrate_legacy_database(source)
    assert repeated.migrated is False
    assert "backup diferente" in repeated.message


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
    assert ApplicationPaths.is_valid_sqlite(destination)

    destination.write_text("invalid", encoding="utf-8")
    Path(f"{destination}-wal").write_text("stale", encoding="utf-8")
    Path(f"{destination}-shm").write_text("stale", encoding="utf-8")
    demo_paths.prepare(source)

    connection = sqlite3.connect(destination)
    try:
        assert connection.execute("SELECT value FROM marker").fetchone() == ("demo",)
    finally:
        connection.close()
    assert not Path(f"{destination}-wal").exists()
    assert not Path(f"{destination}-shm").exists()


def test_demo_session_cleanup_removes_only_abandoned_directories(tmp_path, monkeypatch):
    resource_root = tmp_path / "application"
    monkeypatch.setattr("core.application_paths.tempfile.gettempdir", lambda: str(tmp_path))
    paths = ApplicationPaths(resource_root, tmp_path / "unused", resource_root)
    active = paths.for_demo_session("active").data_root
    recent = paths.for_demo_session("recent").data_root
    abandoned = paths.for_demo_session("abandoned").data_root
    for session_root in (active, recent, abandoned):
        session_root.mkdir(parents=True)
        (session_root / "data").write_text("session", encoding="utf-8")
    now = time.time()
    recent.touch()
    abandoned.touch()
    os.utime(recent, (now - 60, now - 60))
    os.utime(abandoned, (now - 101, now - 101))

    paths.cleanup_demo_sessions("active", max_age_seconds=100)

    assert active.exists()
    assert recent.exists()
    assert not abandoned.exists()


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
        assert first_connection.execute("SELECT value FROM session_marker").fetchone() == ("first",)
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


def test_prepare_preserves_legacy_catalog_rows_before_applying_bundled_baseline(tmp_path):
    resource_root = tmp_path / "bundle"
    releases_root = tmp_path / "releases"
    previous_release = releases_root / "RendaPerene-v2.0.0"
    current_release = releases_root / "RendaPerene-v2.1.0"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", current_release)
    write_catalog(
        previous_release / "assets.csv",
        [("BASE3", "Legacy metadata"), ("LEGACY3", "Legacy fallback")],
    )
    write_catalog(
        resource_root / "assets.csv",
        [("BASE3", "Bundled metadata")],
    )

    paths.prepare()

    catalog = AssetsCatalogDAO(paths.catalog_file).load_catalog()
    assert catalog.loc["BASE3", "NOME"] == "Bundled metadata"
    assert catalog.loc["LEGACY3", "NOME"] == "Legacy fallback"


def test_prepare_skips_malformed_legacy_catalog_and_uses_bundled_baseline(tmp_path):
    resource_root = tmp_path / "bundle"
    legacy_root = tmp_path / "legacy-install"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", legacy_root)
    malformed_catalog = legacy_root / "assets.csv"
    malformed_catalog.parent.mkdir(parents=True)
    malformed_catalog.write_text("not,a,catalog\n", encoding="utf-8")
    write_catalog(resource_root / "assets.csv", [("BASE3", "Bundled metadata")])

    paths.prepare()

    catalog = AssetsCatalogDAO(paths.catalog_file).load_catalog()
    assert catalog.loc["BASE3", "NOME"] == "Bundled metadata"
    assert malformed_catalog.read_text(encoding="utf-8") == "not,a,catalog\n"

    paths.catalog_file.write_text("still,not,a,catalog\n", encoding="utf-8")
    paths.prepare()

    recovered_catalog = AssetsCatalogDAO(paths.catalog_file).load_catalog()
    assert recovered_catalog.loc["BASE3", "NOME"] == "Bundled metadata"


def test_prepare_replaces_an_invalid_catalog_while_holding_the_catalog_lock(tmp_path, monkeypatch):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    write_catalog(resource_root / "assets.csv", [("BASE3", "Bundled metadata")])
    paths.catalog_file.parent.mkdir(parents=True)
    paths.catalog_file.write_text("invalid", encoding="utf-8")
    real_merge = ApplicationPaths._merge_catalogs_locked
    merge_was_locked = False

    def checked_merge(sources, destination):
        nonlocal merge_was_locked
        lock = destination.with_name(f".{destination.name}.lock")
        merge_was_locked = lock.exists()
        real_merge(sources, destination)

    monkeypatch.setattr(
        ApplicationPaths,
        "_merge_catalogs_locked",
        staticmethod(checked_merge),
    )

    paths.prepare()

    assert merge_was_locked is True
    assert AssetsCatalogDAO(paths.catalog_file).load_catalog().loc["BASE3", "NOME"] == (
        "Bundled metadata"
    )


def test_prepare_publishes_the_final_legacy_and_bundled_catalog_only_once(tmp_path, monkeypatch):
    resource_root = tmp_path / "bundle"
    legacy_root = tmp_path / "legacy"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", legacy_root)
    write_catalog(legacy_root / "assets.csv", [("BASE3", "Legacy"), ("USER3", "Fallback")])
    write_catalog(resource_root / "assets.csv", [("BASE3", "Bundled")])
    paths.prepare()
    real_replace = os.replace
    replace_count = 0

    def counting_replace(source, destination):
        nonlocal replace_count
        replace_count += 1
        real_replace(source, destination)

    monkeypatch.setattr("core.application_paths.os.replace", counting_replace)

    paths.prepare()

    assert replace_count == 0
    catalog = AssetsCatalogDAO(paths.catalog_file).load_catalog()
    assert catalog.loc["BASE3", "NOME"] == "Bundled"
    assert catalog.loc["USER3", "NOME"] == "Fallback"


def test_sqlite_validation_reuses_result_for_unchanged_file(monkeypatch, tmp_path):
    database = tmp_path / "portfolio.db"
    create_database(database)
    real_connect = sqlite3.connect
    connection_count = 0

    def counting_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("core.application_paths.sqlite3.connect", counting_connect)

    assert ApplicationPaths.is_valid_sqlite(database) is True
    assert ApplicationPaths.is_valid_sqlite(database) is True
    assert connection_count == 1

    database.write_text("invalid", encoding="utf-8")

    assert ApplicationPaths.is_valid_sqlite(database) is False
    assert connection_count == 2


def test_sqlite_validation_cache_changes_when_wal_changes(monkeypatch, tmp_path):
    database = tmp_path / "portfolio.db"
    create_database(database)
    writer = sqlite3.connect(database)
    assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
    writer.execute("INSERT INTO marker VALUES ('first-wal-row')")
    writer.commit()
    real_connect = sqlite3.connect
    connection_count = 0

    def counting_connect(*args, **kwargs):
        nonlocal connection_count
        connection_count += 1
        return real_connect(*args, **kwargs)

    monkeypatch.setattr("core.application_paths.sqlite3.connect", counting_connect)
    try:
        assert ApplicationPaths.is_valid_sqlite(database) is True
        assert ApplicationPaths.is_valid_sqlite(database) is True
        assert connection_count == 1

        writer.execute("INSERT INTO marker VALUES ('second-wal-row')")
        writer.commit()

        assert ApplicationPaths.is_valid_sqlite(database) is True
        assert connection_count == 2
    finally:
        writer.close()


def test_choose_portfolio_falls_back_to_a_valid_alternative_when_default_is_invalid(tmp_path):
    paths = ApplicationPaths(tmp_path, tmp_path / "user-data", tmp_path)
    paths.prepare()
    paths.portfolio_database("portfolio.db").write_text("invalid", encoding="utf-8")
    alternative = paths.portfolio_database("portfolio_family.db")
    create_database(alternative)
    inventory = paths.inspect_portfolios()

    options = paths.portfolio_options(inventory)
    selected = paths.choose_portfolio("portfolio.db", list(options))

    assert options == ("portfolio_family.db",)
    assert selected == "portfolio_family.db"


def test_portfolio_options_do_not_recreate_missing_principal_when_alternative_exists(tmp_path):
    paths = ApplicationPaths(tmp_path, tmp_path / "user-data", tmp_path)
    paths.prepare()
    alternative = paths.portfolio_database("portfolio_family.db")
    create_database(alternative)
    inventory = paths.inspect_portfolios()

    options = paths.portfolio_options(inventory)
    selected = paths.choose_portfolio("portfolio.db", list(options))

    assert options == ("portfolio_family.db",)
    assert selected == "portfolio_family.db"


def test_portfolio_options_offer_recovery_when_only_principal_is_invalid(tmp_path):
    paths = ApplicationPaths(tmp_path, tmp_path / "user-data", tmp_path)
    paths.prepare()
    invalid_principal = paths.portfolio_database("portfolio.db")
    invalid_principal.write_text("invalid", encoding="utf-8")
    inventory = paths.inspect_portfolios()

    options = paths.portfolio_options(inventory)

    assert options == ("portfolio_recovery.db",)
    assert invalid_principal.read_text(encoding="utf-8") == "invalid"

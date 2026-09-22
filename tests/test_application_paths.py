import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import pytest

import core.application_paths as application_paths_module
from core.application_paths import (
    ApplicationPaths,
    PortfolioRestoreBusyError,
    PortfolioRestoreConflictError,
    PortfolioRestoreManualRecoveryError,
    PortfolioRestorePublicationError,
    portfolio_database_lock,
    portfolio_database_reader_lock,
    portfolio_deletion_marker,
)
from core.daos.assets_catalog_dao import AssetsCatalogDAO
from core.database import DatabaseManager
from core.ports import AssetsCatalogPort
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


def read_database_marker(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        connection.close()


def create_portfolio_database(path: Path) -> str:
    DatabaseManager(path).init_personal_db()
    connection = sqlite3.connect(path)
    try:
        return connection.execute(
            "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
        ).fetchone()[0]
    finally:
        connection.close()


def create_restored_portfolio(path: Path, portfolio_id: str, ticker: str) -> None:
    DatabaseManager(path).init_personal_db()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE portfolio_metadata SET portfolio_id = ? WHERE id = 1",
            (portfolio_id,),
        )
        connection.execute("INSERT INTO tracked_market_assets VALUES (?)", (ticker,))
        connection.commit()
    finally:
        connection.close()


def read_tracked_tickers(path: Path) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT ticker FROM tracked_market_assets ORDER BY ticker"
            ).fetchall()
        ]
    finally:
        connection.close()


def write_catalog(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "CÓDIGO,NOME,IMAGEM,CNPJ,SETOR ECONÔMICO,SUBSETOR ,SEGMENTO / ADM / PAÍS,TIPO,SEGMENTO\n"
    )
    contents = header + "".join(f"{ticker},{name},,,,Outros,,Ação,\n" for ticker, name in rows)
    path.write_text(contents, encoding="utf-8-sig")


def test_catalog_file_resolves_the_bundled_resource(tmp_path):
    resource_root = tmp_path / "bundle"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", tmp_path / "legacy")

    assert paths.catalog_file == resource_root / "assets.csv"


def test_prepare_does_not_copy_or_merge_asset_catalogs(tmp_path):
    resource_root = tmp_path / "bundle"
    data_root = tmp_path / "user-data"
    legacy_root = tmp_path / "legacy"
    paths = ApplicationPaths(resource_root, data_root, legacy_root)
    bundled_catalog = resource_root / "assets.csv"
    writable_catalog = data_root / "catalog" / "assets.csv"
    legacy_catalog = legacy_root / "assets.csv"
    write_catalog(bundled_catalog, [("BASE3", "Bundled")])
    write_catalog(writable_catalog, [("USER3", "User fallback")])
    write_catalog(legacy_catalog, [("LEGACY3", "Legacy fallback")])
    before = {
        path: path.read_bytes() for path in (bundled_catalog, writable_catalog, legacy_catalog)
    }

    paths.prepare()

    assert {path: path.read_bytes() for path in before} == before


def test_prepare_leaves_optional_logs_directory_uncreated(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")

    paths.prepare()

    assert paths.database_dir.is_dir()
    assert paths.backups_dir.is_dir()
    assert not paths.logs_dir.exists()


def test_new_release_uses_its_own_bundled_catalog_without_migration(tmp_path):
    data_root = tmp_path / "user-data"
    first_release = tmp_path / "release-1"
    second_release = tmp_path / "release-2"
    write_catalog(first_release / "assets.csv", [("BASE3", "Old metadata")])
    write_catalog(second_release / "assets.csv", [("BASE3", "New metadata")])

    first_paths = ApplicationPaths(first_release, data_root, first_release)
    second_paths = ApplicationPaths(second_release, data_root, second_release)
    first_paths.prepare()
    second_paths.prepare()

    first_catalog = AssetsCatalogDAO(first_paths.catalog_file).load_catalog()
    second_catalog = AssetsCatalogDAO(second_paths.catalog_file).load_catalog()
    assert first_catalog.loc["BASE3", "NOME"] == "Old metadata"
    assert second_catalog.loc["BASE3", "NOME"] == "New metadata"
    assert not (data_root / "catalog" / "assets.csv").exists()


def test_asset_catalog_interface_and_adapter_are_read_only():
    assert not hasattr(AssetsCatalogPort, "add_fallback_asset")
    assert not hasattr(AssetsCatalogDAO, "add_fallback_asset")


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Unix XDG data directories must be exercised on a Unix host",
)
def test_discovers_linux_xdg_data_directory(monkeypatch, tmp_path):
    xdg_data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))

    paths = ApplicationPaths.discover(system="linux")

    assert paths.data_root == xdg_data_home / "RendaPerene"
    assert paths.database_dir == xdg_data_home / "RendaPerene" / "database"
    assert paths.catalog_file == paths.resource_root / "assets.csv"
    assert paths.logs_dir == xdg_data_home / "RendaPerene" / "logs"
    assert paths.backups_dir == xdg_data_home / "RendaPerene" / "backups"


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Unix home expansion must be exercised on a Unix host",
)
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


def test_legacy_discovery_treats_demo_named_database_as_a_local_portfolio(tmp_path):
    legacy_root = tmp_path / "legacy"
    legacy_database = legacy_root / "database" / "portfolio_demo.db"
    create_database(legacy_database)
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", legacy_root)

    assert legacy_database in paths.legacy_databases()


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


def test_legacy_discovery_includes_non_portfolio_database_names(tmp_path):
    resource_root = tmp_path / "application"
    source = resource_root / "database" / "family.db"
    create_database(source, "family")
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)

    assert paths.legacy_databases() == (source,)
    assert source in paths.migration_candidates()


def test_portfolio_inventory_includes_non_portfolio_database_names(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    database = paths.portfolio_database("family.db")
    create_database(database, "family")

    assert database in paths.inspect_portfolios().valid
    assert paths.portfolio_options(paths.inspect_portfolios()) == ("family.db",)


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


def test_legacy_portfolio_can_be_ignored_without_changing_any_database(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy")
    destination = paths.portfolio_database(source.name)
    create_database(destination, "current")
    source_contents = source.read_bytes()
    destination_contents = destination.read_bytes()

    result = paths.ignore_legacy_database(source)

    assert result.changed is True
    assert "não será mais oferecida" in result.message
    assert source not in paths.migration_candidates()
    assert paths.ignored_legacy_databases() == (source,)
    assert source.read_bytes() == source_contents
    assert destination.read_bytes() == destination_contents
    assert not (paths.backups_dir / "legacy-import" / source.name).exists()


def test_changed_ignored_legacy_portfolio_is_reoffered_and_can_be_ignored_again(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy")

    assert paths.ignore_legacy_database(source).changed is True
    connection = sqlite3.connect(source)
    try:
        connection.execute("INSERT INTO marker VALUES ('new-data')")
        connection.commit()
    finally:
        connection.close()

    assert source in paths.migration_candidates()
    assert paths.ignored_legacy_databases() == ()
    assert paths.ignore_legacy_database(source).changed is True
    assert paths.ignored_legacy_databases() == (source,)

    restored = paths.restore_legacy_database_offer(source)

    assert restored.changed is True
    assert "voltará a ser oferecida" in restored.message
    assert source in paths.migration_candidates()
    assert paths.ignored_legacy_databases() == ()


def test_successful_legacy_import_removes_an_outdated_ignore_preference(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy")
    paths.prepare()
    assert paths.ignore_legacy_database(source).changed is True
    connection = sqlite3.connect(source)
    try:
        connection.execute("INSERT INTO marker VALUES ('new-data')")
        connection.commit()
    finally:
        connection.close()

    result = paths.migrate_legacy_database(source)
    restored = paths.restore_legacy_database_offer(source)

    assert result.migrated is True
    assert restored.changed is False
    assert source not in paths.migration_candidates()


def test_successful_legacy_import_reports_ignore_preference_cleanup_failure(
    tmp_path, monkeypatch
):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy")
    paths.prepare()
    assert paths.ignore_legacy_database(source).changed is True
    connection = sqlite3.connect(source)
    try:
        connection.execute("INSERT INTO marker VALUES ('new-data')")
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setattr(
        ApplicationPaths,
        "_clear_ignored_legacy_marker",
        lambda _self, _source: False,
    )

    result = paths.migrate_legacy_database(source)

    assert result.migrated is True
    assert result.warning is not None
    assert "não foi possível remover a preferência antiga" in result.warning


def test_legacy_ignore_write_failure_keeps_the_source_available(tmp_path, monkeypatch):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy")
    real_replace = os.replace

    def fail_ignore_marker(source_path, destination_path):
        if Path(destination_path).suffix == ".ignored":
            raise OSError("simulated preference write failure")
        real_replace(source_path, destination_path)

    monkeypatch.setattr("core.application_paths.os.replace", fail_ignore_marker)

    result = paths.ignore_legacy_database(source)

    assert result.changed is False
    assert "continuará sendo oferecida" in result.message
    assert source in paths.migration_candidates()
    assert paths.ignored_legacy_databases() == ()


def test_invalid_legacy_ignore_marker_keeps_the_source_available(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy")
    marker = paths.backups_dir / "legacy-import" / "portfolio_old.db.ignored"
    marker.parent.mkdir(parents=True)
    marker.write_text("[]\n", encoding="utf-8")

    assert source in paths.migration_candidates()
    assert paths.ignored_legacy_databases() == ()


def test_legacy_preference_rejects_a_source_outside_discovery(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    outside_source = tmp_path / "outside" / "portfolio.db"
    create_database(outside_source, "outside")

    with pytest.raises(ValueError):
        paths.ignore_legacy_database(outside_source)
    with pytest.raises(ValueError):
        paths.restore_legacy_database_offer(outside_source)


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


def test_concurrent_legacy_migrations_with_different_destinations_publish_once(
    tmp_path, monkeypatch
):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_family.db"
    create_database(source, "legacy")
    paths.prepare()
    create_database(paths.portfolio_database(source.name), "current")
    start = threading.Barrier(2)
    write_calls = 0
    write_calls_lock = threading.Lock()
    second_write_reached = threading.Event()
    real_write_marker = ApplicationPaths._write_completion_marker

    def observed_write_marker(cls, marker, imported_source, destination_name):
        nonlocal write_calls
        with write_calls_lock:
            write_calls += 1
            call_number = write_calls
        if call_number == 1:
            second_write_reached.wait(timeout=0.2)
        else:
            second_write_reached.set()
        real_write_marker(marker, imported_source, destination_name)

    monkeypatch.setattr(
        ApplicationPaths,
        "_write_completion_marker",
        classmethod(observed_write_marker),
    )
    results = []

    def migrate(destination_name):
        start.wait(timeout=2)
        results.append(paths.migrate_legacy_database(source, destination_name))

    first = threading.Thread(target=migrate, args=("portfolio_importada.db",))
    second = threading.Thread(target=migrate, args=("portfolio_importada_2.db",))
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert write_calls == 1
    assert sum(result.migrated for result in results) == 1
    successful = next(result for result in results if result.migrated)
    repeated = next(result for result in results if not result.migrated)
    assert repeated.destination == successful.destination
    assert "já foi importada" in repeated.message
    published = tuple(
        path
        for path in paths.database_dir.glob("portfolio_importada*.db")
        if ApplicationPaths.is_valid_sqlite(path)
    )
    assert published == (successful.destination,)
    assert source not in paths.migration_candidates()


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


def test_replaced_ignored_legacy_database_is_reoffered_when_size_and_mtime_match(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_old.db"
    create_database(source, "legacy-a")
    paths.prepare()
    original_metadata = source.stat()
    original_identity = (
        original_metadata.st_dev,
        original_metadata.st_ino,
        original_metadata.st_ctime_ns,
    )

    assert paths.ignore_legacy_database(source).changed is True

    replacement = source.with_name("replacement.db")
    create_database(replacement, "legacy-b")
    assert replacement.stat().st_size == original_metadata.st_size
    os.utime(
        replacement,
        ns=(original_metadata.st_atime_ns, original_metadata.st_mtime_ns),
    )
    os.replace(replacement, source)
    os.utime(source, ns=(original_metadata.st_atime_ns, original_metadata.st_mtime_ns))

    assert source.stat().st_size == original_metadata.st_size
    assert source.stat().st_mtime_ns == original_metadata.st_mtime_ns
    replacement_metadata = source.stat()
    assert (
        replacement_metadata.st_dev,
        replacement_metadata.st_ino,
        replacement_metadata.st_ctime_ns,
    ) != original_identity
    assert read_database_marker(source) == "legacy-b"
    assert source in paths.migration_candidates()
    assert paths.ignored_legacy_databases() == ()


def test_sqlite_validation_rechecks_a_replaced_file_with_matching_size_and_mtime(tmp_path):
    database = tmp_path / "portfolio.db"
    create_database(database, "valid-db")
    original_metadata = database.stat()
    original_identity = (
        original_metadata.st_dev,
        original_metadata.st_ino,
        original_metadata.st_ctime_ns,
    )

    assert ApplicationPaths.is_valid_sqlite(database) is True

    replacement = database.with_name("replacement.db")
    replacement.write_bytes(b"x" * original_metadata.st_size)
    os.utime(
        replacement,
        ns=(original_metadata.st_atime_ns, original_metadata.st_mtime_ns),
    )
    os.replace(replacement, database)
    os.utime(database, ns=(original_metadata.st_atime_ns, original_metadata.st_mtime_ns))

    assert database.stat().st_size == original_metadata.st_size
    assert database.stat().st_mtime_ns == original_metadata.st_mtime_ns
    replacement_metadata = database.stat()
    assert (
        replacement_metadata.st_dev,
        replacement_metadata.st_ino,
        replacement_metadata.st_ctime_ns,
    ) != original_identity
    assert ApplicationPaths.is_valid_sqlite(database) is False


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


def test_file_lock_reuses_stale_lock_file_without_unlinking(tmp_path):
    database = tmp_path / "portfolio.db"
    lock = database.with_name(".portfolio.db.lock")
    lock.write_text("stale-owner", encoding="utf-8")

    with portfolio_database_lock(database):
        assert lock.exists()


def test_reader_marker_is_published_without_a_temporary_file(tmp_path):
    database = tmp_path / "portfolio.db"

    with portfolio_database_reader_lock(database):
        marker_files = tuple(tmp_path.glob(".portfolio.db.lock.reader.*"))
        assert len(marker_files) == 1
        assert tuple(tmp_path.glob(".*.tmp")) == ()


def test_reader_registration_does_not_wait_for_existing_readers(tmp_path):
    database = tmp_path / "portfolio.db"
    first_reader = portfolio_database_reader_lock(database)
    first_reader.__enter__()
    second_entered = threading.Event()

    def second_reader():
        with portfolio_database_reader_lock(database):
            second_entered.set()

    second = threading.Thread(target=second_reader)
    second.start()
    try:
        assert second_entered.wait(timeout=2)
    finally:
        first_reader.__exit__(None, None, None)
        second.join(timeout=2)

    assert not second.is_alive()


def test_file_lock_serializes_active_writers(tmp_path):
    database = tmp_path / "portfolio.db"
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def first_writer():
        with portfolio_database_lock(database):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def second_writer():
        with portfolio_database_lock(database):
            second_entered.set()

    first = threading.Thread(target=first_writer)
    second = threading.Thread(target=second_writer)
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()

    try:
        assert not second_entered.wait(timeout=0.2)
        release_first.set()
        assert second_entered.wait(timeout=2)
    finally:
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()


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


def test_conflicting_legacy_portfolio_can_be_imported_with_a_safe_alternative_name(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths.prepare()
    original_destination = paths.portfolio_database("portfolio.db")
    create_database(original_destination, "current")
    current_contents = original_destination.read_bytes()

    suggested_name = paths.suggest_legacy_migration_filename(source)
    result = paths.migrate_legacy_database(source, suggested_name)

    assert suggested_name == "portfolio_importada.db"
    assert result.migrated is True
    assert result.destination.name == suggested_name
    assert original_destination.read_bytes() == current_contents
    assert read_database_marker(result.destination) == "legacy"
    assert source not in paths.migration_candidates()


def test_alternative_legacy_import_is_idempotent_and_reoffered_after_data_loss(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths.prepare()
    create_database(paths.portfolio_database("portfolio.db"), "current")

    first = paths.migrate_legacy_database(source, "portfolio_importada.db")
    repeated = paths.migrate_legacy_database(source, "unused_name.db")

    assert first.migrated is True
    assert repeated.migrated is False
    assert repeated.destination == first.destination
    assert "já foi importada" in repeated.message

    first.destination.unlink()
    DatabaseManager(first.destination).init_personal_db()

    assert source in paths.migration_candidates()
    recovered = paths.migrate_legacy_database(source, "portfolio_importada.db")
    assert recovered.migrated is True
    assert read_database_marker(recovered.destination) == "legacy"


def test_legacy_import_suggests_a_free_name_and_never_overwrites_that_choice(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths.prepare()
    create_database(paths.portfolio_database("portfolio.db"), "current")
    occupied = paths.portfolio_database("portfolio_importada.db")
    create_database(occupied, "occupied")
    occupied_contents = occupied.read_bytes()

    assert paths.suggest_legacy_migration_filename(source) == "portfolio_importada_2.db"

    result = paths.migrate_legacy_database(source, occupied.name)

    assert result.migrated is False
    assert "nenhum arquivo foi sobrescrito" in result.message
    assert occupied.read_bytes() == occupied_contents


@pytest.mark.parametrize("unsafe_name", ["", "../portfolio.db", "folder/portfolio.db", "notes.txt"])
def test_legacy_import_rejects_unsafe_destination_names(tmp_path, unsafe_name):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths.prepare()

    with pytest.raises(ValueError):
        paths.migrate_legacy_database(source, unsafe_name)


def test_legacy_completion_marker_without_destination_remains_compatible(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy")
    paths.prepare()
    destination = paths.portfolio_database(source.name)
    backup = paths.backups_dir / "legacy-import" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    backup.write_bytes(source.read_bytes())
    backup.with_suffix(backup.suffix + ".done").write_text("completed\n", encoding="ascii")

    assert source not in paths.migration_candidates()
    repeated = paths.migrate_legacy_database(source)
    assert repeated.migrated is False
    assert repeated.destination == destination
    assert "já foi importada" in repeated.message


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

    assert source in paths.migration_candidates()

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


def test_migrated_pristine_legacy_schema_is_not_reoffered_after_schema_upgrade(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_ana.db"
    DatabaseManager(source).init_personal_db()
    connection = sqlite3.connect(source)
    try:
        connection.execute("DROP TABLE b3_import_records")
        connection.execute("DROP TABLE asset_accumulation_goals")
        connection.execute("DROP TABLE goal_settings")
        connection.commit()
    finally:
        connection.close()
    paths.prepare()

    result = paths.migrate_legacy_database(source)
    DatabaseManager(result.destination).init_personal_db()

    assert result.migrated is True
    assert source not in paths.migration_candidates()


def test_migration_is_reoffered_after_a_missing_portfolio_is_recreated_empty(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy-data")
    paths.prepare()

    first_result = paths.migrate_legacy_database(source)
    assert first_result.migrated is True

    first_result.destination.unlink()
    DatabaseManager(first_result.destination).init_personal_db()

    assert source in paths.migration_candidates()
    repeated = paths.migrate_legacy_database(source)
    assert repeated.migrated is True


def test_migration_reports_success_when_generation_bookkeeping_fails(tmp_path, monkeypatch):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    create_database(source, "legacy-data")
    paths.prepare()

    def fail_generation(_database):
        raise OSError("disk full")

    monkeypatch.setattr(
        ApplicationPaths,
        "_write_database_generation",
        staticmethod(fail_generation),
    )

    result = paths.migrate_legacy_database(source)

    assert result.migrated is False
    assert "nenhum dado foi substituído" in result.message
    assert not result.destination.exists()


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


def test_migration_destination_matches_source_but_backup_differs_is_conflict(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio.db"
    DatabaseManager(source).init_personal_db()
    paths.prepare()

    # Destination is identical to source
    destination = paths.portfolio_database("portfolio.db")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())

    # Create a different database for the backup to cause a conflict
    backup = paths.backups_dir / "legacy-import" / "portfolio.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    DatabaseManager(backup).init_personal_db()
    connection = sqlite3.connect(backup)
    try:
        connection.execute("UPDATE goal_settings SET reinvest_dividends_enabled = 0 WHERE id = 1")
        connection.commit()
    finally:
        connection.close()

    assert source in paths.migration_candidates()
    result = paths.migrate_legacy_database(source)
    assert result.migrated is False
    assert "backup diferente" in result.message

    completion_marker = backup.with_suffix(backup.suffix + ".done")
    assert not completion_marker.exists()


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


def test_catalog_repository_resolves_the_current_context_for_each_operation(tmp_path):
    from views.cached_market_data import StreamlitCachedMarketData

    session_catalog = ContextVar("session_catalog")
    repository = AssetsCatalogDAO(lambda: session_catalog.get())
    first_catalog = tmp_path / "first" / "assets.csv"
    second_catalog = tmp_path / "second" / "assets.csv"
    write_catalog(first_catalog, [("FIRST3", "First")])
    write_catalog(second_catalog, [("SECOND3", "Second")])
    original_catalog_path = MarketData._catalog_path
    MarketData.configure_catalog(lambda: session_catalog.get())

    try:
        session_catalog.set(first_catalog)
        assert MarketData.resolve_catalog_path() == first_catalog
        session_catalog.set(second_catalog)
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


def test_portfolio_options_do_not_automatically_reuse_deleted_filenames(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    first_recovery = paths.portfolio_database("portfolio_recovery.db")
    for database in (principal, first_recovery):
        marker = portfolio_deletion_marker(database)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("deleted", encoding="ascii")

    options = paths.portfolio_options(paths.inspect_portfolios())

    assert options == ("portfolio_recovery_2.db",)


def test_delete_inactive_portfolio_moves_it_to_a_unique_recoverable_backup(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal, "principal")
    create_database(family, "family")

    result = paths.delete_portfolio("portfolio_family.db", "portfolio_family.db")

    assert result.deleted is True
    assert result.backup_dir is not None
    assert not family.exists()
    assert principal.exists()
    assert (result.backup_dir / family.name).exists()
    assert ApplicationPaths.is_valid_sqlite(result.backup_dir / family.name)

    create_database(family, "replacement")
    repeated = paths.delete_portfolio("portfolio_family.db", "portfolio_family.db")

    assert repeated.deleted is True
    assert repeated.backup_dir != result.backup_dir
    assert (result.backup_dir / family.name).exists()
    assert (repeated.backup_dir / family.name).exists()


def test_same_name_recreation_publishes_a_new_generation_for_stale_sessions(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    paths.prepare_portfolio_creation(family.name)
    original_generation = Path(f"{family}.generation").read_text(encoding="ascii")
    create_database(family)
    stale_manager = DatabaseManager(family)

    result = paths.delete_portfolio(family.name, family.name)

    assert result.deleted is True
    assert portfolio_deletion_marker(family).exists()
    with pytest.raises(FileNotFoundError, match="was deleted"):
        stale_manager.get_personal_connection()
    assert not family.exists()

    paths.prepare_portfolio_creation(family.name)
    replacement_generation = Path(f"{family}.generation").read_text(encoding="ascii")
    stale_manager.init_personal_db()

    assert family.exists()
    assert not portfolio_deletion_marker(family).exists()
    assert replacement_generation
    assert replacement_generation != original_generation


def test_delete_portfolio_rejects_confirmation_bound_to_an_old_generation(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    paths.prepare_portfolio_creation(family.name)
    create_database(family, "original")
    confirmed_generation = paths.database_generation(family)

    paths.prepare_portfolio_creation(family.name)
    replacement_generation = paths.database_generation(family)
    result = paths.delete_portfolio(
        family.name,
        family.name,
        expected_generation=confirmed_generation,
    )

    assert replacement_generation != confirmed_generation
    assert result.deleted is False
    assert "substituída" in result.message
    assert family.exists()
    assert tuple((paths.backups_dir / "deleted-portfolios").glob("*")) == ()


def test_database_connection_guard_runs_before_sqlite_can_recreate_a_file(tmp_path):
    database = tmp_path / "portfolio_family.db"

    def reject_stale_connection(path):
        assert path == database
        raise RuntimeError("stale portfolio generation")

    manager = DatabaseManager(database, connection_guard=reject_stale_connection)

    with pytest.raises(RuntimeError, match="stale portfolio generation"):
        manager.get_personal_connection()

    assert not database.exists()


def test_explicit_legacy_import_clears_a_deleted_portfolio_tombstone(tmp_path):
    resource_root = tmp_path / "application"
    paths = ApplicationPaths(resource_root, tmp_path / "user-data", resource_root)
    source = resource_root / "database" / "portfolio_family.db"
    create_database(source, "legacy")
    destination = paths.portfolio_database(source.name)
    deletion_marker = portfolio_deletion_marker(destination)
    deletion_marker.parent.mkdir(parents=True, exist_ok=True)
    deletion_marker.write_text("deleted", encoding="ascii")

    result = paths.migrate_legacy_database(source)

    assert result.migrated is True
    assert destination.exists()
    assert not deletion_marker.exists()


def test_delete_portfolio_moves_sqlite_sidecars_and_generation_marker(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    create_database(family)
    related = (
        Path(f"{family}-wal"),
        Path(f"{family}-shm"),
        Path(f"{family}.generation"),
    )
    for path in related:
        path.write_text(path.name, encoding="utf-8")
    monkeypatch.setattr(
        ApplicationPaths,
        "is_valid_sqlite",
        staticmethod(lambda path: Path(path).suffix == ".db" and Path(path).exists()),
    )

    result = paths.delete_portfolio("portfolio_family.db", "portfolio_family.db")

    assert result.deleted is True
    assert result.backup_dir is not None
    for path in related:
        assert not path.exists()
        assert (result.backup_dir / path.name).read_text(encoding="utf-8") == path.name


def test_delete_portfolio_rejects_invalid_confirmation_and_unsafe_names(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    create_database(family)

    wrong_confirmation = paths.delete_portfolio("portfolio_family.db", "family")
    traversal = paths.delete_portfolio("../portfolio_family.db", "../portfolio_family.db")
    absolute = paths.delete_portfolio(str(family.resolve()), str(family.resolve()))

    assert wrong_confirmation.deleted is False
    assert "nome completo do arquivo" in wrong_confirmation.message
    assert traversal.deleted is False
    assert absolute.deleted is False
    assert "nome de carteira válido" in traversal.message
    assert "nome de carteira válido" in absolute.message
    assert family.exists()


def test_delete_portfolio_treats_demo_named_database_as_a_local_portfolio(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    demo_named = paths.portfolio_database("portfolio_demo.db")
    create_database(principal)
    create_database(demo_named)

    result = paths.delete_portfolio("portfolio_demo.db", "portfolio_demo.db")

    assert result.deleted is True
    assert not demo_named.exists()
    assert principal.exists()


def test_delete_portfolio_rejects_last_and_invalid_databases(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    create_database(principal)

    last = paths.delete_portfolio("portfolio.db", "portfolio.db")

    assert last.deleted is False
    assert "última carteira válida" in last.message
    assert principal.exists()

    alternative = paths.portfolio_database("portfolio_family.db")
    create_database(alternative)
    invalid = paths.portfolio_database("portfolio_invalid.db")
    invalid.write_text("invalid", encoding="utf-8")
    invalid_result = paths.delete_portfolio("portfolio_invalid.db", "portfolio_invalid.db")
    assert invalid_result.deleted is False
    assert "SQLite válido" in invalid_result.message
    assert invalid.exists()

def test_delete_portfolio_times_out_without_moving_an_active_reader(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    create_database(family)
    connection = DatabaseManager(family).get_personal_connection()
    monkeypatch.setattr("core.application_paths.FILE_LOCK_TIMEOUT_SECONDS", 0.05)

    try:
        result = paths.delete_portfolio("portfolio_family.db", "portfolio_family.db")
    finally:
        connection.close()

    assert result.deleted is False
    assert "em uso" in result.message
    assert family.exists()
    assert not (paths.backups_dir / "deleted-portfolios").exists()


def test_delete_portfolio_rolls_back_every_moved_file_on_failure(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    create_database(family)
    generation = Path(f"{family}.generation")
    generation.write_text("generation", encoding="ascii")
    real_replace = os.replace

    def fail_generation_move(source, destination):
        if Path(source) == generation:
            raise OSError("simulated move failure")
        real_replace(source, destination)

    monkeypatch.setattr("core.application_paths.os.replace", fail_generation_move)

    result = paths.delete_portfolio("portfolio_family.db", "portfolio_family.db")

    assert result.deleted is False
    assert "nenhum arquivo foi excluído" in result.message
    assert family.exists()
    assert generation.exists()
    assert not portfolio_deletion_marker(family).exists()
    assert tuple((paths.backups_dir / "deleted-portfolios").glob("*")) == ()


def test_failed_deletion_rollback_keeps_tombstone_blocking_partial_portfolio(
    tmp_path, monkeypatch
):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    principal = paths.portfolio_database("portfolio.db")
    family = paths.portfolio_database("portfolio_family.db")
    create_database(principal)
    create_database(family)
    generation = Path(f"{family}.generation")
    generation.write_text("generation", encoding="ascii")
    real_replace = os.replace

    def fail_move_and_rollback(source, destination):
        source = Path(source)
        destination = Path(destination)
        if source == generation or (
            source.parent != paths.database_dir and destination == family
        ):
            raise OSError("simulated filesystem failure")
        real_replace(source, destination)

    monkeypatch.setattr("core.application_paths.os.replace", fail_move_and_rollback)

    result = paths.delete_portfolio(family.name, family.name)

    assert result.deleted is False
    assert "recuperação manual" in result.message
    assert portfolio_deletion_marker(family).exists()
    assert not family.exists()
    assert result.backup_dir is not None
    assert (result.backup_dir / family.name).exists()


def test_restore_target_matches_local_portfolio_identity_and_reports_latest_file_change(
    tmp_path,
):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio_family.db")
    portfolio_id = create_portfolio_database(database)
    Path(f"{database}.generation").write_text("current-generation", encoding="ascii")
    database_timestamp = 1_700_000_000
    wal_timestamp = database_timestamp + 60
    os.utime(database, (database_timestamp, database_timestamp))
    wal = Path(f"{database}-wal")
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute(
            "UPDATE goal_settings SET reinvest_dividends_enabled = 0 WHERE id = 1"
        )
        writer.commit()
        os.utime(database, (database_timestamp, database_timestamp))
        os.utime(wal, (wal_timestamp, wal_timestamp))

        target = paths.plan_portfolio_restore(portfolio_id)
    finally:
        writer.close()

    assert target.filename == database.name
    assert target.expected_generation == "current-generation"
    assert target.replaces_existing is True
    assert target.last_modified_at_utc == "2023-11-14T22:14:20Z"
    assert target.state_token


def test_restore_target_uses_a_new_safe_filename_for_an_unknown_identity(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    portfolio_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"

    target = paths.plan_portfolio_restore(portfolio_id)

    assert target.filename == "portfolio_restored_f4b8d9bf.db"
    assert target.expected_generation is None
    assert target.replaces_existing is False
    assert target.last_modified_at_utc is None
    assert target.state_token


def test_restore_target_uses_a_chosen_name_for_a_new_portfolio_identity(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    principal = paths.portfolio_database("portfolio.db")
    create_portfolio_database(principal)
    colleague_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"

    target = paths.plan_portfolio_restore(colleague_id, requested_name="João")

    assert target.filename == "portfolio_joão.db"
    assert target.replaces_existing is False
    assert principal.exists()


@pytest.mark.parametrize(
    "name", ["", "  ", "../Outra", "João/Outra", "João: Outra", "recovery", "A" * 61]
)
def test_restore_target_rejects_invalid_new_portfolio_names(tmp_path, name):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    colleague_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"

    with pytest.raises(ValueError):
        paths.plan_portfolio_restore(colleague_id, requested_name=name)


@pytest.mark.parametrize(
    "occupied_name",
    (
        "portfolio_joão.db",
        "PORTFOLIO_JOÃO.DB",
        "portfolio_joão.db-wal",
        ".portfolio_joão.db.deleted",
    ),
)
def test_restore_target_refuses_a_chosen_name_already_used_locally(tmp_path, occupied_name):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    (paths.database_dir / occupied_name).write_bytes(b"existing local data")
    colleague_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"

    with pytest.raises(PortfolioRestoreConflictError):
        paths.plan_portfolio_restore(colleague_id, requested_name="João")


def test_restore_publication_refuses_a_chosen_name_taken_after_preview(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    colleague_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"
    target = paths.plan_portfolio_restore(colleague_id, requested_name="João")
    occupied = paths.database_dir / "PORTFOLIO_JOÃO.DB"
    occupied.write_bytes(b"existing local data")
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, colleague_id, "COLL3")

    with pytest.raises(PortfolioRestoreConflictError):
        paths.publish_portfolio_restore(snapshot, target)

    assert occupied.read_bytes() == b"existing local data"
    assert not paths.portfolio_database(target.filename).exists()
    assert snapshot.exists()


def test_restore_publication_replaces_matching_identity_and_preserves_previous_portfolio(
    tmp_path,
):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio_family.db")
    portfolio_id = create_portfolio_database(database)
    current = sqlite3.connect(database)
    current.execute("INSERT INTO tracked_market_assets VALUES ('OLD3')")
    current.commit()
    current.close()
    Path(f"{database}.generation").write_text("old-generation", encoding="ascii")
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, portfolio_id, "NEW4")
    target = paths.plan_portfolio_restore(portfolio_id)

    result = paths.publish_portfolio_restore(snapshot, target)

    assert result.database == database
    assert result.generation != "old-generation"
    assert paths.database_generation(database) == result.generation
    assert read_tracked_tickers(database) == ["NEW4"]
    assert result.recovery_directory is not None
    recovered = result.recovery_directory / database.name
    assert read_tracked_tickers(recovered) == ["OLD3"]
    assert (result.recovery_directory / f"{database.name}.generation").read_text(
        encoding="ascii"
    ) == "old-generation"


def test_restore_publication_refuses_a_portfolio_changed_after_preview(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio_family.db")
    portfolio_id = create_portfolio_database(database)
    target = paths.plan_portfolio_restore(portfolio_id)
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, portfolio_id, "REST3")
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('LATE4')")
    connection.commit()
    connection.close()

    with pytest.raises(PortfolioRestoreConflictError):
        paths.publish_portfolio_restore(snapshot, target)

    assert read_tracked_tickers(database) == ["LATE4"]
    assert snapshot.exists()
    assert not (paths.backups_dir / "pre-restore").exists()


def test_restore_publication_refuses_a_new_duplicate_identity_after_preview(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    portfolio_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"
    target = paths.plan_portfolio_restore(portfolio_id)
    duplicate = paths.portfolio_database("portfolio_other.db")
    create_restored_portfolio(duplicate, portfolio_id, "OTHER3")
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, portfolio_id, "REST3")

    with pytest.raises(PortfolioRestoreConflictError):
        paths.publish_portfolio_restore(snapshot, target)

    assert not paths.portfolio_database(target.filename).exists()
    assert read_tracked_tickers(duplicate) == ["OTHER3"]


def test_restore_publication_adds_an_unknown_identity_without_replacing_a_portfolio(
    tmp_path,
):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    principal = paths.portfolio_database("portfolio.db")
    principal_id = create_portfolio_database(principal)
    restored_id = "f4b8d9bf-3295-4d80-93b1-846095d53c1f"
    assert restored_id != principal_id
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, restored_id, "REST3")
    target = paths.plan_portfolio_restore(restored_id)

    result = paths.publish_portfolio_restore(snapshot, target)

    assert result.database.name == "portfolio_restored_f4b8d9bf.db"
    assert result.recovery_directory is None
    assert read_tracked_tickers(result.database) == ["REST3"]
    assert principal.exists()
    assert paths.database_generation(result.database) == result.generation


def test_restore_publication_waits_for_open_portfolio_readers(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio.db")
    portfolio_id = create_portfolio_database(database)
    target = paths.plan_portfolio_restore(portfolio_id)
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, portfolio_id, "REST3")
    connection = DatabaseManager(database).get_personal_connection()
    monkeypatch.setattr("core.application_paths.FILE_LOCK_TIMEOUT_SECONDS", 0.05)

    try:
        with pytest.raises(PortfolioRestoreBusyError):
            paths.publish_portfolio_restore(snapshot, target)
    finally:
        connection.close()

    assert database.exists()
    assert snapshot.exists()
    assert not (paths.backups_dir / "pre-restore").exists()


def test_restore_publication_rolls_back_when_generation_publication_fails(
    tmp_path, monkeypatch
):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio.db")
    portfolio_id = create_portfolio_database(database)
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('OLD3')")
    connection.commit()
    connection.close()
    Path(f"{database}.generation").write_text("old-generation", encoding="ascii")
    target = paths.plan_portfolio_restore(portfolio_id)
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, portfolio_id, "NEW4")

    def fail_generation(_database):
        raise OSError("simulated generation failure")

    lock_held = False
    real_lock = portfolio_database_lock
    real_replace = os.replace
    rollback_checked = False

    @contextmanager
    def observed_lock(locked_database):
        nonlocal lock_held
        with real_lock(locked_database):
            lock_held = True
            try:
                yield
            finally:
                lock_held = False

    def observed_replace(source, destination):
        nonlocal rollback_checked
        if Path(source).parent.parent == paths.backups_dir / "pre-restore":
            rollback_checked = True
            assert lock_held
        return real_replace(source, destination)

    monkeypatch.setattr(
        ApplicationPaths,
        "_write_database_generation",
        staticmethod(fail_generation),
    )
    monkeypatch.setattr(application_paths_module, "portfolio_database_lock", observed_lock)
    monkeypatch.setattr(application_paths_module.os, "replace", observed_replace)

    with pytest.raises(PortfolioRestorePublicationError):
        paths.publish_portfolio_restore(snapshot, target)

    assert read_tracked_tickers(database) == ["OLD3"]
    assert rollback_checked
    assert paths.database_generation(database) == "old-generation"
    assert not portfolio_deletion_marker(database).exists()
    assert tuple((paths.backups_dir / "pre-restore").glob("*")) == ()


def test_restore_publication_keeps_recovery_copy_when_rollback_fails(
    tmp_path, monkeypatch
):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio.db")
    portfolio_id = create_portfolio_database(database)
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('OLD3')")
    connection.commit()
    connection.close()
    target = paths.plan_portfolio_restore(portfolio_id)
    snapshot = paths.backups_dir / ".restore-staging" / "restored.sqlite3"
    snapshot.parent.mkdir()
    create_restored_portfolio(snapshot, portfolio_id, "NEW4")
    real_replace = os.replace

    def fail_generation(_database):
        raise OSError("simulated generation failure")

    def fail_database_rollback(source, destination):
        source = Path(source)
        destination = Path(destination)
        if source.parent.parent == paths.backups_dir / "pre-restore" and destination == database:
            raise OSError("simulated rollback failure")
        real_replace(source, destination)

    monkeypatch.setattr(
        ApplicationPaths,
        "_write_database_generation",
        staticmethod(fail_generation),
    )
    monkeypatch.setattr("core.application_paths.os.replace", fail_database_rollback)

    with pytest.raises(PortfolioRestoreManualRecoveryError) as raised:
        paths.publish_portfolio_restore(snapshot, target)

    assert not database.exists()
    assert portfolio_deletion_marker(database).exists()
    assert read_tracked_tickers(raised.value.backup_dir / database.name) == ["OLD3"]


def test_concurrent_deletions_cannot_remove_both_remaining_portfolios(tmp_path):
    paths = ApplicationPaths(tmp_path / "application", tmp_path / "user-data", tmp_path)
    first = paths.portfolio_database("portfolio_first.db")
    second = paths.portfolio_database("portfolio_second.db")
    create_database(first, "first")
    create_database(second, "second")
    start = threading.Barrier(2)
    results = []

    def delete(filename):
        start.wait(timeout=2)
        results.append(paths.delete_portfolio(filename, filename))

    first_thread = threading.Thread(target=delete, args=(first.name,))
    second_thread = threading.Thread(target=delete, args=(second.name,))
    first_thread.start()
    second_thread.start()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert sum(result.deleted for result in results) == 1
    assert len(paths.inspect_portfolios().valid) == 1

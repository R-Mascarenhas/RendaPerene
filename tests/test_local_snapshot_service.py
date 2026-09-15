import hashlib
import json
import sqlite3
import uuid
from datetime import datetime

import pytest

from core.application_paths import ApplicationPaths, portfolio_database_lock
from core.database import CURRENT_SCHEMA_VERSION, DatabaseManager
from services.local_snapshot_service import LocalSnapshotService, SnapshotCreationError


def build_snapshot_service(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = paths.portfolio_database("portfolio.db")
    manager = DatabaseManager(database)
    manager.init_personal_db()
    return LocalSnapshotService(manager, paths, "1.2.3"), database, paths


def test_backup_is_consistent_and_independently_verifiable(tmp_path):
    service, database, paths = build_snapshot_service(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT INTO transactions "
            "(date, ticker, transaction_type, quantity, unit_price, fees) "
            "VALUES ('2026-09-14', 'TEST3', 'BUY', 10, 12.5, 1.0)"
        )
        connection.commit()
    finally:
        connection.close()

    result = service.create_snapshot()

    assert result.directory.parent == paths.local_backups_dir
    assert result.database_file == result.directory / "backup.sqlite3"
    assert result.metadata_file == result.directory / "metadata.json"
    assert {path.name for path in result.directory.iterdir()} == {
        "backup.sqlite3",
        "metadata.json",
    }
    assert result.directory.name == result.metadata["backup_id"]
    assert uuid.UUID(result.metadata["backup_id"])
    assert uuid.UUID(result.metadata["portfolio_id"])
    assert uuid.UUID(result.metadata["installation_id"])
    assert result.metadata["format_version"] == 1
    assert result.metadata["app_version"] == "1.2.3"
    assert result.metadata["schema_version"] == CURRENT_SCHEMA_VERSION
    assert result.metadata["encryption_state"] == "unencrypted"
    created_at = datetime.fromisoformat(result.metadata["created_at_utc"].replace("Z", "+00:00"))
    assert created_at.utcoffset().total_seconds() == 0
    assert result.metadata["sha256"] == hashlib.sha256(
        result.database_file.read_bytes()
    ).hexdigest()
    assert json.loads(result.metadata_file.read_text(encoding="utf-8")) == result.metadata

    snapshot = sqlite3.connect(f"{result.database_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        row = snapshot.execute(
            "SELECT ticker, quantity, unit_price, fees FROM transactions"
        ).fetchone()
        assert row == ("TEST3", 10, 12.5, 1.0)
    finally:
        snapshot.close()


def test_backup_identifiers_are_stable_without_using_the_portfolio_filename(tmp_path):
    service, _, paths = build_snapshot_service(tmp_path)

    first = service.create_snapshot()
    second = service.create_snapshot()

    other_database = paths.portfolio_database("portfolio_family.db")
    other_manager = DatabaseManager(other_database)
    other_manager.init_personal_db()
    other = LocalSnapshotService(other_manager, paths, "1.2.3").create_snapshot()

    assert first.metadata["backup_id"] != second.metadata["backup_id"]
    assert first.metadata["portfolio_id"] == second.metadata["portfolio_id"]
    assert first.metadata["portfolio_id"] != other.metadata["portfolio_id"]
    assert first.metadata["installation_id"] == second.metadata["installation_id"]
    assert first.metadata["installation_id"] == other.metadata["installation_id"]
    assert "portfolio" not in first.directory.name
    assert "portfolio" not in other.directory.name


def test_backup_remains_bound_to_the_portfolio_selected_during_composition(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    first_database = paths.portfolio_database("portfolio.db")
    shared_manager = DatabaseManager(first_database)
    shared_manager.init_personal_db()
    service = LocalSnapshotService(shared_manager, paths, "1.2.3")
    first_connection = sqlite3.connect(first_database)
    try:
        first_connection.execute("INSERT INTO tracked_market_assets VALUES ('FIRST3')")
        first_connection.commit()
    finally:
        first_connection.close()

    second_database = paths.portfolio_database("portfolio_second.db")
    second_manager = DatabaseManager(second_database)
    second_manager.init_personal_db()
    second_connection = sqlite3.connect(second_database)
    try:
        second_connection.execute("INSERT INTO tracked_market_assets VALUES ('SECOND4')")
        second_connection.commit()
    finally:
        second_connection.close()

    shared_manager.personal_db = second_database

    result = service.create_snapshot()

    backup = sqlite3.connect(f"{result.database_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert backup.execute("SELECT ticker FROM tracked_market_assets").fetchall() == [
            ("FIRST3",)
        ]
    finally:
        backup.close()


def test_backup_uses_a_complete_committed_state_while_wal_writer_is_open(tmp_path):
    service, database, _ = build_snapshot_service(tmp_path)
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO tracked_market_assets VALUES ('DONE3')")
        writer.commit()
        writer.execute("INSERT INTO tracked_market_assets VALUES ('OPEN4')")

        result = service.create_snapshot()
    finally:
        writer.rollback()
        writer.close()

    assert {path.name for path in result.directory.iterdir()} == {
        "backup.sqlite3",
        "metadata.json",
    }
    snapshot = sqlite3.connect(f"{result.database_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tickers = snapshot.execute(
            "SELECT ticker FROM tracked_market_assets ORDER BY ticker"
        ).fetchall()
        assert tickers == [("DONE3",)]
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        snapshot.close()


def test_integrity_failure_does_not_publish_a_backup_or_leave_temporary_files(tmp_path):
    service, database, paths = build_snapshot_service(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE integrity_marker (value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO integrity_marker VALUES (?)", [(str(index),) for index in range(100)]
        )
        connection.execute("CREATE INDEX integrity_marker_index ON integrity_marker(value)")
        connection.commit()
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute(
            "DELETE FROM sqlite_master WHERE name = 'integrity_marker_index'"
        )
        connection.execute("PRAGMA writable_schema = OFF")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SnapshotCreationError, match="integridade"):
        service.create_snapshot()

    assert database.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_publication_failure_is_mapped_and_cleans_the_complete_staging_directory(
    tmp_path, monkeypatch
):
    service, database, paths = build_snapshot_service(tmp_path)

    def fail_publication(_source, _destination):
        raise OSError("simulated storage failure for portfolio.db")

    monkeypatch.setattr("services.local_snapshot_service.os.replace", fail_publication)

    with pytest.raises(SnapshotCreationError) as captured:
        service.create_snapshot()

    assert "portfolio.db" not in str(captured.value)
    assert "Não foi possível salvar o backup" in str(captured.value)
    assert database.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_missing_active_database_is_not_recreated_by_a_failed_backup(tmp_path):
    service, database, paths = build_snapshot_service(tmp_path)
    database.unlink()

    with pytest.raises(SnapshotCreationError) as captured:
        service.create_snapshot()

    assert "carteira ativa não está disponível" in str(captured.value)
    assert not database.exists()
    assert not paths.local_backups_dir.exists() or list(paths.local_backups_dir.iterdir()) == []


def test_backup_respects_the_portfolio_lifecycle_lock(tmp_path, monkeypatch):
    service, database, paths = build_snapshot_service(tmp_path)
    monkeypatch.setattr("core.application_paths.FILE_LOCK_TIMEOUT_SECONDS", 0.05)

    with portfolio_database_lock(database):
        with pytest.raises(SnapshotCreationError) as captured:
            service.create_snapshot()

    assert "carteira está em uso" in str(captured.value)
    assert database.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_backup_directory_failure_is_reported_without_touching_the_active_database(tmp_path):
    service, database, paths = build_snapshot_service(tmp_path)
    active_contents = database.read_bytes()
    paths.local_backups_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SnapshotCreationError) as captured:
        service.create_snapshot()

    assert "Não foi possível salvar o backup" in str(captured.value)
    assert database.read_bytes() == active_contents
    assert paths.local_backups_dir.read_text(encoding="utf-8") == "not a directory"


def test_invalid_portfolio_identifier_prevents_backup_publication(tmp_path):
    service, database, paths = build_snapshot_service(tmp_path)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE portfolio_metadata SET portfolio_id = 'portfolio.db' WHERE id = 1"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SnapshotCreationError) as captured:
        service.create_snapshot()

    assert "identificação da carteira" in str(captured.value)
    assert list(paths.local_backups_dir.iterdir()) == []

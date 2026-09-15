import hashlib
import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

import pytest

from core.application_paths import ApplicationPaths, portfolio_database_lock
from core.database import CURRENT_SCHEMA_VERSION, DatabaseManager
from core.ports import PortfolioSnapshotIdentity
from core.sqlite_backup import SQLitePortfolioBackupSourceFactory
from services.local_backup_service import (
    BackupCreationError,
    LocalBackupService,
    PortfolioBackupSelection,
)


def create_portfolio(paths: ApplicationPaths, filename: str, ticker: str):
    database = paths.portfolio_database(filename)
    DatabaseManager(database).init_personal_db()
    connection = sqlite3.connect(database)
    try:
        connection.execute("INSERT INTO tracked_market_assets VALUES (?)", (ticker,))
        connection.commit()
    finally:
        connection.close()
    return database


def select_portfolio(paths: ApplicationPaths, filename: str) -> PortfolioBackupSelection:
    database = paths.portfolio_database(filename)
    return PortfolioBackupSelection(
        filename,
        paths.database_generation(database),
        f"Carteira: {filename}",
    )


def build_backup_service(paths: ApplicationPaths) -> LocalBackupService:
    return LocalBackupService(SQLitePortfolioBackupSourceFactory(paths), paths, "1.2.3")


def test_backup_preserves_the_user_visible_portfolio_name(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio_familia.db", "FAMILY4")

    result = build_backup_service(paths).create_backup(
        [
            PortfolioBackupSelection(
                database.name,
                paths.database_generation(database),
                "Carteira: Família",
            )
        ]
    )

    portfolio_entry = result.manifest["portfolios"][0]
    metadata = json.loads(
        (result.directory / portfolio_entry["relative_path"] / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert portfolio_entry["display_name"] == "Carteira: Família"
    assert metadata["display_name"] == "Carteira: Família"


def test_backup_contains_only_the_selected_portfolios(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    create_portfolio(paths, "portfolio.db", "MAIN3")
    selected_database = create_portfolio(paths, "portfolio_family.db", "FAMILY4")
    service = build_backup_service(paths)

    result = service.create_backup(
        [
            PortfolioBackupSelection(
                "portfolio_family.db",
                paths.database_generation(selected_database),
                "Carteira: Família",
            )
        ]
    )

    assert result.directory.parent == paths.local_backups_dir
    assert result.directory.name == result.manifest["backup_id"]
    assert result.portfolio_count == 1
    assert result.manifest_file == result.directory / "manifest.json"
    assert {path.name for path in result.directory.iterdir()} == {
        "carteiras",
        "manifest.json",
    }
    assert result.manifest["format_version"] == 2
    assert result.manifest["portfolio_count"] == 1
    assert result.manifest["app_version"] == "1.2.3"
    assert result.manifest["encryption_state"] == "unencrypted"
    assert uuid.UUID(result.manifest["backup_id"])
    assert uuid.UUID(result.manifest["installation_id"])
    created_at = datetime.fromisoformat(result.manifest["created_at_utc"].replace("Z", "+00:00"))
    assert created_at.utcoffset().total_seconds() == 0
    assert json.loads(result.manifest_file.read_text(encoding="utf-8")) == result.manifest

    portfolio_entry = result.manifest["portfolios"][0]
    portfolio_id = portfolio_entry["portfolio_id"]
    assert uuid.UUID(portfolio_id)
    portfolio_directory = result.directory / "carteiras" / portfolio_id
    assert portfolio_entry["relative_path"] == f"carteiras/{portfolio_id}"
    assert {path.name for path in portfolio_directory.iterdir()} == {
        "backup.sqlite3",
        "metadata.json",
    }
    database_file = portfolio_directory / "backup.sqlite3"
    metadata = json.loads((portfolio_directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["portfolio_id"] == portfolio_id
    assert metadata["schema_version"] == CURRENT_SCHEMA_VERSION
    assert metadata["sha256"] == hashlib.sha256(database_file.read_bytes()).hexdigest()
    assert portfolio_entry["sha256"] == metadata["sha256"]

    connection = sqlite3.connect(f"{database_file.resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert connection.execute("SELECT ticker FROM tracked_market_assets").fetchall() == [
            ("FAMILY4",)
        ]
    finally:
        connection.close()

    serialized_artifacts = "\n".join(
        path.read_text(encoding="utf-8") for path in result.directory.rglob("*.json")
    )
    assert "portfolio.db" not in serialized_artifacts
    assert "portfolio_family.db" not in serialized_artifacts


def test_backup_contains_every_selected_portfolio_in_one_set(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    create_portfolio(paths, "portfolio.db", "MAIN3")
    create_portfolio(paths, "portfolio_family.db", "FAMILY4")
    service = build_backup_service(paths)

    result = service.create_backup(
        [
            select_portfolio(paths, "portfolio.db"),
            select_portfolio(paths, "portfolio_family.db"),
        ]
    )

    assert result.portfolio_count == 2
    assert result.manifest["portfolio_count"] == 2
    assert len(result.manifest["portfolios"]) == 2
    backed_up_tickers = set()
    for entry in result.manifest["portfolios"]:
        database_file = result.directory / entry["relative_path"] / "backup.sqlite3"
        connection = sqlite3.connect(f"{database_file.resolve().as_uri()}?mode=ro", uri=True)
        try:
            backed_up_tickers.update(
                row[0]
                for row in connection.execute("SELECT ticker FROM tracked_market_assets").fetchall()
            )
        finally:
            connection.close()
    assert backed_up_tickers == {"MAIN3", "FAMILY4"}


def test_backup_keeps_every_selected_source_open_until_the_set_is_published(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    first_database = create_portfolio(paths, "portfolio.db", "MAIN3")
    second_database = create_portfolio(paths, "portfolio_family.db", "FAMILY4")

    class TrackingReader:
        def __init__(self, source):
            self.source = source

        def backup_to(self, destination):
            assert all(source.is_open for source in sources.values())
            source_connection = sqlite3.connect(self.source.database)
            destination_connection = sqlite3.connect(destination)
            try:
                source_connection.backup(destination_connection)
                destination_connection.commit()
                portfolio_id = source_connection.execute(
                    "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
                ).fetchone()[0]
                schema_version = source_connection.execute("PRAGMA user_version").fetchone()[0]
            finally:
                destination_connection.close()
                source_connection.close()
            return PortfolioSnapshotIdentity(portfolio_id, schema_version)

    class TrackingSource:
        def __init__(self, database):
            self.database = database
            self.is_open = False

        def prepare(self):
            pass

        @contextmanager
        def open_reader(self):
            self.is_open = True
            try:
                yield TrackingReader(self)
            finally:
                published_sets = [
                    path
                    for path in paths.local_backups_dir.iterdir()
                    if not path.name.startswith(".")
                ]
                assert len(published_sets) == 1
                self.is_open = False

    class TrackingFactory:
        def create(self, filename, _expected_generation):
            return sources[filename]

    sources = {
        first_database.name: TrackingSource(first_database),
        second_database.name: TrackingSource(second_database),
    }
    service = LocalBackupService(TrackingFactory(), paths, "1.2.3")

    result = service.create_backup(
        [
            select_portfolio(paths, first_database.name),
            select_portfolio(paths, second_database.name),
        ]
    )

    assert result.portfolio_count == 2
    assert all(not source.is_open for source in sources.values())


def test_backup_requires_at_least_one_selected_portfolio(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()

    with pytest.raises(BackupCreationError, match="Selecione pelo menos uma carteira"):
        build_backup_service(paths).create_backup([])

    assert not paths.local_backups_dir.exists()


def test_backup_rejects_a_selection_without_a_visible_name(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "MAIN3")

    with pytest.raises(BackupCreationError, match="nome exibido"):
        build_backup_service(paths).create_backup(
            [
                PortfolioBackupSelection(
                    database.name,
                    paths.database_generation(database),
                    "   ",
                )
            ]
        )

    assert not paths.local_backups_dir.exists()


def test_backup_rejects_a_selected_symlink_outside_the_portfolio_directory(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    external_database = tmp_path / "external.db"
    DatabaseManager(external_database).init_personal_db()
    selected_link = paths.portfolio_database("portfolio_link.db")
    try:
        selected_link.symlink_to(external_database)
    except OSError as error:
        pytest.skip(f"Symlinks are unavailable: {error}")

    with pytest.raises(BackupCreationError, match="carteira local inválida"):
        build_backup_service(paths).create_backup(
            [PortfolioBackupSelection(selected_link.name, None, "Carteira externa")]
        )

    assert not paths.local_backups_dir.exists()


def test_backup_rejects_a_portfolio_replaced_after_selection(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "OLD3")
    selection = select_portfolio(paths, "portfolio.db")
    paths.prepare_portfolio_creation("portfolio.db")

    with pytest.raises(BackupCreationError, match="removida ou substituída"):
        build_backup_service(paths).create_backup([selection])

    assert database.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_failure_after_first_snapshot_does_not_publish_a_partial_set(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    first = create_portfolio(paths, "portfolio.db", "MAIN3")
    second = create_portfolio(paths, "portfolio_family.db", "FAMILY4")
    selections = [
        PortfolioBackupSelection(
            first.name,
            paths.database_generation(first),
            "Carteira Principal",
        ),
        PortfolioBackupSelection(
            second.name,
            paths.database_generation(second),
            "Carteira Família",
        ),
    ]
    second.unlink()

    with pytest.raises(BackupCreationError, match="removida ou substituída"):
        build_backup_service(paths).create_backup(selections)

    assert first.exists()
    assert not second.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_backup_rejects_duplicate_portfolio_identities(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    first = create_portfolio(paths, "portfolio.db", "MAIN3")
    duplicate = paths.portfolio_database("portfolio_copy.db")
    shutil.copy2(first, duplicate)

    with pytest.raises(BackupCreationError, match="mesma identificação"):
        build_backup_service(paths).create_backup(
            [
                select_portfolio(paths, first.name),
                select_portfolio(paths, duplicate.name),
            ]
        )

    assert list(paths.local_backups_dir.iterdir()) == []


def test_backup_uses_complete_committed_states_while_wal_writer_is_open(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "BEFORE3")
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO tracked_market_assets VALUES ('DONE4')")
        writer.commit()
        writer.execute("INSERT INTO tracked_market_assets VALUES ('OPEN5')")

        result = build_backup_service(paths).create_backup([select_portfolio(paths, database.name)])
    finally:
        writer.rollback()
        writer.close()

    entry = result.manifest["portfolios"][0]
    portfolio_directory = result.directory / entry["relative_path"]
    assert {path.name for path in portfolio_directory.iterdir()} == {
        "backup.sqlite3",
        "metadata.json",
    }
    snapshot = sqlite3.connect(
        f"{(portfolio_directory / 'backup.sqlite3').resolve().as_uri()}?mode=ro",
        uri=True,
    )
    try:
        assert snapshot.execute(
            "SELECT ticker FROM tracked_market_assets ORDER BY ticker"
        ).fetchall() == [("BEFORE3",), ("DONE4",)]
        assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        snapshot.close()


def test_backup_initializes_existing_schema_metadata_for_an_unopened_portfolio(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio_old.db", "OLD3")
    connection = sqlite3.connect(database)
    try:
        connection.execute("DROP TABLE portfolio_metadata")
        connection.execute("PRAGMA user_version = 0")
        connection.commit()
    finally:
        connection.close()

    result = build_backup_service(paths).create_backup([select_portfolio(paths, database.name)])

    source = sqlite3.connect(database)
    try:
        source_portfolio_id = source.execute(
            "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
        ).fetchone()[0]
        assert source.execute("PRAGMA user_version").fetchone() == (CURRENT_SCHEMA_VERSION,)
    finally:
        source.close()
    assert result.manifest["portfolios"][0]["portfolio_id"] == source_portfolio_id


def test_backup_respects_each_portfolio_lifecycle_lock(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "MAIN3")
    monkeypatch.setattr("core.application_paths.FILE_LOCK_TIMEOUT_SECONDS", 0.05)

    with portfolio_database_lock(database):
        with pytest.raises(BackupCreationError, match="carteiras está em uso"):
            build_backup_service(paths).create_backup([select_portfolio(paths, database.name)])

    assert database.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_integrity_failure_does_not_publish_a_backup_set(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "MAIN3")
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE integrity_marker (value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO integrity_marker VALUES (?)", [(str(index),) for index in range(100)]
        )
        connection.execute("CREATE INDEX integrity_marker_index ON integrity_marker(value)")
        connection.commit()
        connection.execute("PRAGMA writable_schema = ON")
        connection.execute("DELETE FROM sqlite_master WHERE name = 'integrity_marker_index'")
        connection.execute("PRAGMA writable_schema = OFF")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(BackupCreationError, match="integridade"):
        build_backup_service(paths).create_backup([select_portfolio(paths, database.name)])

    assert database.exists()
    assert list(paths.local_backups_dir.iterdir()) == []


def test_invalid_portfolio_identifier_prevents_backup_publication(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "MAIN3")
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE portfolio_metadata SET portfolio_id = 'portfolio.db' WHERE id = 1"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(BackupCreationError, match="identificação inválida"):
        build_backup_service(paths).create_backup([select_portfolio(paths, database.name)])

    assert list(paths.local_backups_dir.iterdir()) == []


def test_backup_directory_failure_does_not_modify_a_selected_portfolio(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database = create_portfolio(paths, "portfolio.db", "MAIN3")
    original_contents = database.read_bytes()
    paths.local_backups_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(BackupCreationError, match="armazenamento local"):
        build_backup_service(paths).create_backup([select_portfolio(paths, database.name)])

    assert database.read_bytes() == original_contents
    assert paths.local_backups_dir.read_text(encoding="utf-8") == "not a directory"

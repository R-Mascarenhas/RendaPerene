import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

import pytest

import core.encrypted_backup_package as package_module
from core.application_paths import ApplicationPaths, PortfolioRestoreConflictError
from core.database import CURRENT_SCHEMA_VERSION, DatabaseManager
from core.encrypted_backup_package import EncryptedBackupPackageService
from core.sqlite_backup import SQLitePortfolioBackupSourceFactory
from services.local_backup_service import (
    LocalBackupService,
    PortfolioBackupSelection,
)
from services.local_restore_service import (
    BackupRestoreError,
    BackupRestoreCorruptedError,
    BackupRestoreConflictError,
    BackupRestoreCredentialError,
    BackupRestoreIncompatibleError,
    LocalRestoreService,
    RestoreCredential,
)


@pytest.fixture(autouse=True)
def fast_password_derivation(monkeypatch):
    monkeypatch.setattr(package_module, "ARGON2_MEMORY_COST_KIB", 8)
    monkeypatch.setattr(package_module, "ARGON2_ITERATIONS", 1)
    monkeypatch.setattr(package_module, "ARGON2_LANES", 1)


def create_portfolio(paths: ApplicationPaths, filename: str, ticker: str) -> tuple[Path, str]:
    database = paths.portfolio_database(filename)
    DatabaseManager(database).init_personal_db()
    connection = sqlite3.connect(database)
    try:
        connection.execute("INSERT INTO tracked_market_assets VALUES (?)", (ticker,))
        portfolio_id = connection.execute(
            "SELECT portfolio_id FROM portfolio_metadata WHERE id = 1"
        ).fetchone()[0]
        connection.commit()
    finally:
        connection.close()
    return database, portfolio_id


def tracked_tickers(database: Path) -> list[str]:
    connection = sqlite3.connect(database)
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT ticker FROM tracked_market_assets ORDER BY ticker"
            ).fetchall()
        ]
    finally:
        connection.close()


def create_package(
    paths: ApplicationPaths,
    database: Path,
    password: str = "senha segura",
):
    service = LocalBackupService(SQLitePortfolioBackupSourceFactory(paths), paths, "1.2.3")
    return service.create_encrypted_backup(
        [
            PortfolioBackupSelection(
                database.name,
                paths.database_generation(database),
                "Carteira Família",
            )
        ],
        password,
    )


def repack_with_mutation(tmp_path, backup, mutation, password="senha segura") -> bytes:
    extracted = tmp_path / f"opened-{mutation.__name__}"
    packages = EncryptedBackupPackageService()
    packages.extract_with_password(backup.package_file, extracted, password)
    mutation(extracted)
    manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
    replacement = tmp_path / f"{mutation.__name__}.rpb"
    packages.create(
        extracted,
        replacement,
        password,
        backup_id=manifest["backup_id"],
    )
    return replacement.read_bytes()


def test_user_can_preview_and_restore_a_matching_portfolio_with_an_older_backup(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, portfolio_id = create_portfolio(paths, "portfolio_family.db", "BACK3")
    backup = create_package(paths, database)
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('LOCAL4')")
    connection.commit()
    connection.close()
    future_timestamp = database.stat().st_mtime + 60
    os.utime(database, (future_timestamp, future_timestamp))
    package_content = backup.package_file.read_bytes()
    restores = LocalRestoreService(paths)
    credential = RestoreCredential.with_password("senha segura")

    preview = restores.inspect_package(package_content, credential)

    assert preview.backup_id == backup.manifest["backup_id"]
    assert preview.created_at_utc == backup.manifest["created_at_utc"]
    assert preview.app_version == "1.2.3"
    assert preview.installation_id == backup.manifest["installation_id"]
    assert len(preview.portfolios) == 1
    portfolio = preview.portfolios[0]
    assert portfolio.portfolio_id == portfolio_id
    assert portfolio.display_name == "Carteira Família"
    assert portfolio.schema_version == CURRENT_SCHEMA_VERSION
    assert portfolio.target.filename == database.name
    assert portfolio.target.replaces_existing is True
    assert portfolio.backup_is_older_than_local is True

    restored = restores.restore_package(package_content, credential, portfolio)

    assert restored.database == database
    assert restored.recovery_directory is not None
    assert tracked_tickers(database) == ["BACK3"]
    assert tracked_tickers(restored.recovery_directory / database.name) == ["BACK3", "LOCAL4"]
    assert not tuple(paths.backups_dir.glob(".restore-*"))


def test_cleanup_failure_does_not_hide_a_committed_restore(tmp_path, monkeypatch, caplog):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio_family.db", "BACK3")
    backup = create_package(paths, database)
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('LOCAL4')")
    connection.commit()
    connection.close()
    package_content = backup.package_file.read_bytes()
    restores = LocalRestoreService(paths)
    credential = RestoreCredential.with_password("senha segura")
    preview = restores.inspect_package(package_content, credential)

    def fail_cleanup(_path):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr("services.local_restore_service.shutil.rmtree", fail_cleanup)
    caplog.set_level(logging.DEBUG, logger="services.local_restore_service")

    result = restores.restore_package(package_content, credential, preview.portfolios[0])

    assert result.database == database
    assert tracked_tickers(database) == ["BACK3"]
    assert result.cleanup_warning_path is not None
    assert result.cleanup_warning_path.name.startswith(".restore-")
    warning = next(
        record for record in caplog.records if record.message == "restore.cleanup.failed"
    )
    assert warning.levelno == logging.WARNING
    assert warning.exc_info is None
    assert str(result.cleanup_warning_path) not in warning.getMessage()
    assert any(
        record.levelno == logging.DEBUG
        and str(result.cleanup_warning_path) in record.getMessage()
        for record in caplog.records
    )


def test_inspection_cleanup_failure_reports_temporary_directory(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio_family.db", "BACK3")
    backup = create_package(paths, database)
    restores = LocalRestoreService(paths)

    def fail_cleanup(_path):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr("services.local_restore_service.shutil.rmtree", fail_cleanup)

    preview = restores.inspect_package(
        backup.package_file.read_bytes(), RestoreCredential.with_password("senha segura")
    )

    assert preview.cleanup_warning_path is not None
    assert preview.cleanup_warning_path.name.startswith(".restore-")


def test_failed_restore_reports_temporary_cleanup_failure(tmp_path, monkeypatch):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio_family.db", "BACK3")
    backup = create_package(paths, database)
    restores = LocalRestoreService(paths)
    package_content = backup.package_file.read_bytes()
    credential = RestoreCredential.with_password("senha segura")
    preview = restores.inspect_package(package_content, credential)

    def fail_cleanup(_path):
        raise OSError("simulated cleanup failure")

    def fail_publication(_self, _snapshot, _target):
        raise PortfolioRestoreConflictError("simulated conflict")

    with monkeypatch.context() as patch:
        patch.setattr("services.local_restore_service.shutil.rmtree", fail_cleanup)
        patch.setattr(ApplicationPaths, "publish_portfolio_restore", fail_publication)
        with pytest.raises(BackupRestoreError, match="temporários") as raised:
            restores.restore_package(package_content, credential, preview.portfolios[0])

    assert ".restore-" in str(raised.value)


def test_restore_accepts_wal_sidecar_churn_without_local_content_change(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio_family.db", "BACK3")
    backup = create_package(paths, database)
    package_content = backup.package_file.read_bytes()
    restores = LocalRestoreService(paths)
    credential = RestoreCredential.with_password("senha segura")
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        preview = restores.inspect_package(package_content, credential)
        shm = Path(f"{database}-shm")
        assert shm.exists()
        os.utime(shm, ns=(shm.stat().st_atime_ns, shm.stat().st_mtime_ns + 1_000_000))
    finally:
        writer.close()

    result = restores.restore_package(package_content, credential, preview.portfolios[0])

    assert result.database == database
    assert tracked_tickers(database) == ["BACK3"]


def test_user_can_restore_an_unknown_portfolio_with_the_recovery_key(tmp_path):
    source_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "source-data", tmp_path / "legacy"
    )
    source_paths.prepare()
    database, portfolio_id = create_portfolio(source_paths, "portfolio.db", "BACK3")
    backup = create_package(source_paths, database)
    destination_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "destination-data", tmp_path / "legacy"
    )
    destination_paths.prepare()
    restores = LocalRestoreService(destination_paths)
    credential = RestoreCredential.with_recovery_key(backup.recovery_key_file_content)

    preview = restores.inspect_package(backup.package_file.read_bytes(), credential)

    portfolio = preview.portfolios[0]
    assert portfolio.portfolio_id == portfolio_id
    assert portfolio.target.replaces_existing is False
    assert portfolio.backup_is_older_than_local is False

    restored = restores.restore_package(
        backup.package_file.read_bytes(), credential, portfolio
    )

    assert restored.database.name == f"portfolio_restored_{portfolio_id[:8]}.db"
    assert restored.recovery_directory is None
    assert tracked_tickers(restored.database) == ["BACK3"]


def test_colleagues_principal_backup_can_be_restored_under_a_chosen_local_name(tmp_path):
    source_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "source-data", tmp_path / "legacy"
    )
    source_paths.prepare()
    source_database, _source_id = create_portfolio(source_paths, "portfolio.db", "COLL3")
    backup = create_package(source_paths, source_database)
    destination_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "destination-data", tmp_path / "legacy"
    )
    destination_paths.prepare()
    principal, _principal_id = create_portfolio(destination_paths, "portfolio.db", "MINE3")
    package_content = backup.package_file.read_bytes()
    credential = RestoreCredential.with_password("senha segura")
    restores = LocalRestoreService(destination_paths)

    preview = restores.inspect_package(package_content, credential)
    chosen = restores.choose_new_destination(preview.portfolios[0], "João")
    restored = restores.restore_package(package_content, credential, chosen)

    assert chosen.target.filename == "portfolio_joão.db"
    assert restored.database.name == "portfolio_joão.db"
    assert tracked_tickers(restored.database) == ["COLL3"]
    assert tracked_tickers(principal) == ["MINE3"]


def test_restore_name_too_long_for_filesystem_has_clear_message(tmp_path):
    source_paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "source-data", tmp_path / "legacy")
    source_paths.prepare()
    source_database, _portfolio_id = create_portfolio(source_paths, "portfolio.db", "COLL3")
    backup = create_package(source_paths, source_database)
    destination_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "destination-data", tmp_path / "legacy"
    )
    destination_paths.prepare()
    restores = LocalRestoreService(destination_paths)
    preview = restores.inspect_package(
        backup.package_file.read_bytes(), RestoreCredential.with_password("senha segura")
    )

    with pytest.raises(BackupRestoreError, match="Escolha um nome mais curto"):
        restores.choose_new_destination(preview.portfolios[0], "𐐀" * 60)


def test_chosen_restore_name_taken_after_preview_cannot_replace_local_data(tmp_path):
    source_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "source-data", tmp_path / "legacy"
    )
    source_paths.prepare()
    source_database, _source_id = create_portfolio(source_paths, "portfolio.db", "COLL3")
    backup = create_package(source_paths, source_database)
    destination_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "destination-data", tmp_path / "legacy"
    )
    destination_paths.prepare()
    package_content = backup.package_file.read_bytes()
    credential = RestoreCredential.with_password("senha segura")
    restores = LocalRestoreService(destination_paths)
    preview = restores.inspect_package(package_content, credential)
    chosen = restores.choose_new_destination(preview.portfolios[0], "João")
    occupied = destination_paths.database_dir / "PORTFOLIO_JOÃO.DB"
    occupied.write_bytes(b"existing local data")

    with pytest.raises(BackupRestoreConflictError):
        restores.restore_package(package_content, credential, chosen)

    assert occupied.read_bytes() == b"existing local data"


def test_wrong_password_or_corrupted_package_never_changes_the_local_portfolio(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio.db", "SAFE3")
    backup = create_package(paths, database)
    restores = LocalRestoreService(paths)
    package_content = backup.package_file.read_bytes()

    with pytest.raises(BackupRestoreCredentialError):
        restores.inspect_package(
            package_content,
            RestoreCredential.with_password("senha errada"),
        )

    corrupted = package_content[:-1] + bytes([package_content[-1] ^ 1])
    with pytest.raises(BackupRestoreCorruptedError):
        restores.inspect_package(
            corrupted,
            RestoreCredential.with_password("senha segura"),
        )

    assert tracked_tickers(database) == ["SAFE3"]
    assert not tuple(paths.backups_dir.glob(".restore-*"))


def test_backup_with_a_newer_schema_is_rejected_without_changing_local_data(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio.db", "SAFE3")
    backup = create_package(paths, database)

    def use_newer_schema(extracted):
        manifest_path = extracted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["portfolios"][0]
        portfolio_dir = extracted / entry["relative_path"]
        restored_database = portfolio_dir / "backup.sqlite3"
        connection = sqlite3.connect(restored_database)
        connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
        connection.close()
        checksum = hashlib.sha256(restored_database.read_bytes()).hexdigest()
        metadata_path = portfolio_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        entry["schema_version"] = CURRENT_SCHEMA_VERSION + 1
        entry["sha256"] = checksum
        metadata["schema_version"] = CURRENT_SCHEMA_VERSION + 1
        metadata["sha256"] = checksum
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    package_content = repack_with_mutation(tmp_path, backup, use_newer_schema)

    with pytest.raises(BackupRestoreIncompatibleError, match="schema mais novo"):
        LocalRestoreService(paths).inspect_package(
            package_content,
            RestoreCredential.with_password("senha segura"),
        )

    assert tracked_tickers(database) == ["SAFE3"]


def test_authenticated_package_with_a_wrong_snapshot_hash_is_rejected(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio.db", "SAFE3")
    backup = create_package(paths, database)

    def use_wrong_hash(extracted):
        manifest_path = extracted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["portfolios"][0]
        metadata_path = extracted / entry["relative_path"] / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        entry["sha256"] = "0" * 64
        metadata["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    package_content = repack_with_mutation(tmp_path, backup, use_wrong_hash)

    with pytest.raises(BackupRestoreCorruptedError, match="hash"):
        LocalRestoreService(paths).inspect_package(
            package_content,
            RestoreCredential.with_password("senha segura"),
        )

    assert tracked_tickers(database) == ["SAFE3"]


def test_authenticated_package_with_non_sqlite_contents_is_rejected(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio.db", "SAFE3")
    backup = create_package(paths, database)

    def replace_sqlite(extracted):
        manifest_path = extracted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["portfolios"][0]
        portfolio_dir = extracted / entry["relative_path"]
        restored_database = portfolio_dir / "backup.sqlite3"
        restored_database.write_bytes(b"not a sqlite database")
        checksum = hashlib.sha256(restored_database.read_bytes()).hexdigest()
        metadata_path = portfolio_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        entry["sha256"] = checksum
        metadata["sha256"] = checksum
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    package_content = repack_with_mutation(tmp_path, backup, replace_sqlite)

    with pytest.raises(BackupRestoreCorruptedError):
        LocalRestoreService(paths).inspect_package(
            package_content,
            RestoreCredential.with_password("senha segura"),
        )

    assert tracked_tickers(database) == ["SAFE3"]


def test_package_with_duplicate_portfolio_identity_is_rejected(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio.db", "SAFE3")
    backup = create_package(paths, database)

    def duplicate_identity(extracted):
        manifest_path = extracted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["portfolios"].append(dict(manifest["portfolios"][0]))
        manifest["portfolio_count"] = 2
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    package_content = repack_with_mutation(tmp_path, backup, duplicate_identity)

    with pytest.raises(BackupRestoreCorruptedError, match="duplicadas"):
        LocalRestoreService(paths).inspect_package(
            package_content,
            RestoreCredential.with_password("senha segura"),
        )

    assert tracked_tickers(database) == ["SAFE3"]


def test_restore_requires_a_new_preview_when_local_data_changes_after_confirmation(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(paths, "portfolio.db", "BACK3")
    backup = create_package(paths, database)
    package_content = backup.package_file.read_bytes()
    restores = LocalRestoreService(paths)
    credential = RestoreCredential.with_password("senha segura")
    selected = restores.inspect_package(package_content, credential).portfolios[0]
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('LATE4')")
    connection.commit()
    connection.close()

    with pytest.raises(BackupRestoreConflictError, match="mudou"):
        restores.restore_package(package_content, credential, selected)

    assert tracked_tickers(database) == ["BACK3", "LATE4"]
    assert not (paths.backups_dir / "pre-restore").exists()


def test_supported_older_schema_is_migrated_before_publication(tmp_path):
    source_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "source-data", tmp_path / "legacy"
    )
    source_paths.prepare()
    database, _portfolio_id = create_portfolio(source_paths, "portfolio.db", "BACK3")
    backup = create_package(source_paths, database)

    def use_older_schema(extracted):
        manifest_path = extracted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["portfolios"][0]
        portfolio_dir = extracted / entry["relative_path"]
        restored_database = portfolio_dir / "backup.sqlite3"
        connection = sqlite3.connect(restored_database)
        connection.execute("PRAGMA user_version = 0")
        connection.close()
        checksum = hashlib.sha256(restored_database.read_bytes()).hexdigest()
        metadata_path = portfolio_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        entry["schema_version"] = 0
        entry["sha256"] = checksum
        metadata["schema_version"] = 0
        metadata["sha256"] = checksum
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    package_content = repack_with_mutation(tmp_path, backup, use_older_schema)
    destination_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "destination-data", tmp_path / "legacy"
    )
    destination_paths.prepare()
    restores = LocalRestoreService(destination_paths)
    credential = RestoreCredential.with_password("senha segura")
    selected = restores.inspect_package(package_content, credential).portfolios[0]

    result = restores.restore_package(package_content, credential, selected)

    connection = sqlite3.connect(result.database)
    try:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            CURRENT_SCHEMA_VERSION,
        )
    finally:
        connection.close()
    assert tracked_tickers(result.database) == ["BACK3"]


def test_multi_portfolio_package_restores_only_the_confirmed_portfolio(tmp_path):
    source_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "source-data", tmp_path / "legacy"
    )
    source_paths.prepare()
    first, _first_id = create_portfolio(source_paths, "portfolio.db", "FIRST3")
    second, second_id = create_portfolio(
        source_paths, "portfolio_family.db", "SECOND4"
    )
    backup_service = LocalBackupService(
        SQLitePortfolioBackupSourceFactory(source_paths), source_paths, "1.2.3"
    )
    backup = backup_service.create_encrypted_backup(
        [
            PortfolioBackupSelection(
                first.name,
                source_paths.database_generation(first),
                "Carteira Principal",
            ),
            PortfolioBackupSelection(
                second.name,
                source_paths.database_generation(second),
                "Carteira Família",
            ),
        ],
        "senha segura",
    )
    destination_paths = ApplicationPaths(
        tmp_path / "bundle", tmp_path / "destination-data", tmp_path / "legacy"
    )
    destination_paths.prepare()
    restores = LocalRestoreService(destination_paths)
    credential = RestoreCredential.with_password("senha segura")
    package_content = backup.package_file.read_bytes()
    preview = restores.inspect_package(package_content, credential)
    selected = next(
        portfolio for portfolio in preview.portfolios if portfolio.portfolio_id == second_id
    )

    result = restores.restore_package(package_content, credential, selected)

    assert tracked_tickers(result.database) == ["SECOND4"]
    inventory = destination_paths.inspect_portfolios()
    assert inventory.valid == (result.database,)


def test_restore_logs_lifecycle_without_credentials_or_portfolio_names(tmp_path, caplog):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    database, _portfolio_id = create_portfolio(
        paths, "portfolio_private_family.db", "SAFE3"
    )
    password = "segredo privado"
    backup = create_package(paths, database, password)

    with caplog.at_level(logging.DEBUG, logger="services.local_restore_service"):
        LocalRestoreService(paths).inspect_package(
            backup.package_file.read_bytes(),
            RestoreCredential.with_password(password),
        )

    messages = [record.getMessage() for record in caplog.records]
    assert "restore.inspect.started" in messages
    assert "restore.inspect.completed portfolios=1" in messages
    assert all(password not in message for message in messages)
    assert all(database.name not in message for message in messages)


def test_local_backup_list_reads_existing_packages_newest_first(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    restores = LocalRestoreService(paths)
    assert restores.list_local_packages() == ()

    paths.local_backups_dir.mkdir()
    older = paths.local_backups_dir / "older.rpb"
    newer = paths.local_backups_dir / "newer.rpb"
    older.write_bytes(b"older package")
    newer.write_bytes(b"newer package")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_700_000_100, 1_700_000_100))
    (paths.local_backups_dir / "incomplete.tmp").write_bytes(b"incomplete")

    assert restores.list_local_packages() == ("newer.rpb", "older.rpb")
    assert restores.read_local_package("older.rpb") == b"older package"

    upper_case = paths.local_backups_dir / "UPPER.RPB"
    upper_case.write_bytes(b"upper-case package")
    assert "UPPER.RPB" in restores.list_local_packages()
    assert restores.read_local_package("UPPER.RPB") == b"upper-case package"


def test_local_backup_selection_cannot_read_outside_the_backup_directory(tmp_path):
    paths = ApplicationPaths(tmp_path / "bundle", tmp_path / "user-data", tmp_path / "legacy")
    paths.prepare()
    paths.local_backups_dir.mkdir()
    external = tmp_path / "external.rpb"
    external.write_bytes(b"external package")
    (paths.local_backups_dir / "linked.rpb").symlink_to(external)
    restores = LocalRestoreService(paths)

    assert restores.list_local_packages() == ()
    with pytest.raises(BackupRestoreError):
        restores.read_local_package("../external.rpb")
    with pytest.raises(BackupRestoreError):
        restores.read_local_package("linked.rpb")

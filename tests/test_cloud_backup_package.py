import io
import sqlite3
import zipfile
from contextlib import closing

import pytest

from core.application_paths import ApplicationPaths
from core.database import DatabaseManager
from core.daos.portfolio_dao import PortfolioDAO
from core.dividends import DividendEvent, DividendPayment
from core.sqlite_backup import SQLitePortfolioBackupSourceFactory
from services.assets_service import AssetService
from services.local_backup_service import LocalBackupService, PortfolioBackupSelection
from services.local_restore_service import (
    BackupRestoreConflictError,
    BackupRestoreCorruptedError,
    LocalRestoreService,
    RestoreCredential,
)


def make_paths(tmp_path, name):
    paths = ApplicationPaths(tmp_path / 'bundle', tmp_path / name, tmp_path / 'legacy')
    paths.prepare()
    return paths


def create_cloud_backup(paths):
    database = paths.portfolio_database('portfolio_family.db')
    DatabaseManager(database).init_personal_db()
    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO tracked_market_assets VALUES ('TEST3')")
    connection.commit()
    connection.close()
    backups = LocalBackupService(SQLitePortfolioBackupSourceFactory(paths), paths, '1.2.3')
    return backups.create_cloud_backup(
        PortfolioBackupSelection(database.name, paths.database_generation(database), 'Família'),
        'Computador 1',
    )


def test_cloud_backup_can_be_restored_on_another_installation_without_password(tmp_path):
    source = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(source)
    destination = make_paths(tmp_path, 'destination')
    restores = LocalRestoreService(destination)

    preview = restores.inspect_cloud_package(artifact.content)
    selected = restores.choose_new_destination(preview.portfolios[0], 'Família')
    result = restores.restore_cloud_package(artifact.content, selected)

    connection = sqlite3.connect(result.database)
    assert connection.execute('SELECT ticker FROM tracked_market_assets').fetchall() == [('TEST3',)]
    connection.close()
    assert preview.portfolios[0].portfolio_id == artifact.portfolio_id
    assert preview.installation_id == artifact.installation_id
    assert not list(source.local_backups_dir.iterdir())
    assert not list(destination.backups_dir.glob('.restore-*'))


def test_cloud_restore_preserves_dividend_reviews_receipts_and_detection(tmp_path):
    source = make_paths(tmp_path, 'source')
    database = source.portfolio_database('portfolio_family.db')
    manager = DatabaseManager(database)
    manager.init_personal_db()
    repository = PortfolioDAO(manager)
    confirmed = DividendEvent('BBAS3', '2024-03-23', 1.0)
    ignored = DividendEvent('BBAS3', '2024-04-23', 0.3)
    legacy = DividendEvent('BBAS3', '2024-05-23', 0.5)
    pending = DividendEvent('BBAS3', '2024-07-23', 0.7)

    class Provider:
        def get_events(self, ticker, start_date):
            return [confirmed, ignored, legacy, pending]

    service = AssetService(portfolio_repo=repository, dividend_provider=Provider())
    service.add_transaction('BBAS3', '2024-01-01', 'BUY', 100, 10)
    service.confirm_dividend(confirmed, 'DIVIDEND', [
        DividendPayment('2024-03-30', 100, 1.0),
    ], service.get_local_projection_revision())
    service.add_dividend('BBAS3', '2024-06-01', 'DIVIDEND', 50, 100, 0.5)
    backups = LocalBackupService(SQLitePortfolioBackupSourceFactory(source), source, '1.2.3')
    selection = PortfolioBackupSelection(database.name, source.database_generation(database), 'Família')
    before_ignore = backups.create_cloud_backup(selection, 'Computador 1')
    service.ignore_dividend(ignored, service.get_local_projection_revision())
    artifact = backups.create_cloud_backup(selection, 'Computador 1')
    assert artifact.fingerprint != before_ignore.fingerprint
    expected = service.get_dividend_suggestions()
    assert [item['event'] for item in expected['suggestions']] == [pending]

    destination = make_paths(tmp_path, 'destination')
    restores = LocalRestoreService(destination)
    selected = restores.choose_new_destination(
        restores.inspect_cloud_package(artifact.content).portfolios[0], 'Família',
    )
    result = restores.restore_cloud_package(artifact.content, selected)
    restored_repository = PortfolioDAO(DatabaseManager(result.database))
    restored_service = AssetService(portfolio_repo=restored_repository, dividend_provider=Provider())

    assert destination.snapshot_content_digest(result.database) == source.snapshot_content_digest(database)
    assert restored_repository.get_dividend_reviews() == repository.get_dividend_reviews()
    assert restored_service.get_dividend_payments('BBAS3') == service.get_dividend_payments('BBAS3')
    assert restored_service.get_dividend_suggestions() == expected


def test_cloud_restore_can_explicitly_replace_principal_with_a_different_identity(tmp_path):
    source = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(source)
    destination = make_paths(tmp_path, 'destination')
    principal = destination.portfolio_database('portfolio.db')
    DatabaseManager(principal).init_personal_db()
    with closing(sqlite3.connect(principal)) as connection, connection:
        connection.execute("INSERT INTO tracked_market_assets VALUES ('LOCAL3')")
    restores = LocalRestoreService(destination)
    selected = restores.choose_existing_destination(
        restores.inspect_cloud_package(artifact.content).portfolios[0], principal.name,
    )

    result = restores.restore_cloud_package(artifact.content, selected)

    assert result.database == principal
    assert destination.inspect_portfolios().valid == (principal,)
    assert result.recovery_directory is not None
    with closing(sqlite3.connect(result.recovery_directory / principal.name)) as connection:
        assert connection.execute('SELECT ticker FROM tracked_market_assets').fetchall() == [('LOCAL3',)]
    with closing(sqlite3.connect(principal)) as connection:
        assert connection.execute('SELECT ticker FROM tracked_market_assets').fetchall() == [('TEST3',)]
        assert connection.execute('SELECT portfolio_id FROM portfolio_metadata').fetchone()[0] == artifact.portfolio_id


def test_explicit_cloud_replacement_rejects_changes_since_confirmation(tmp_path):
    source = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(source)
    destination = make_paths(tmp_path, 'destination')
    principal = destination.portfolio_database('portfolio.db')
    DatabaseManager(principal).init_personal_db()
    restores = LocalRestoreService(destination)
    selected = restores.choose_existing_destination(
        restores.inspect_cloud_package(artifact.content).portfolios[0], principal.name,
    )
    with closing(sqlite3.connect(principal)) as connection, connection:
        connection.execute("INSERT INTO tracked_market_assets VALUES ('LOCAL3')")
    with pytest.raises(BackupRestoreConflictError):
        restores.restore_cloud_package(artifact.content, selected)
    with closing(sqlite3.connect(principal)) as connection:
        assert connection.execute('SELECT ticker FROM tracked_market_assets').fetchall() == [('LOCAL3',)]
    assert destination.inspect_portfolios().valid == (principal,)


def test_explicit_replacement_cannot_duplicate_an_already_installed_backup_identity(tmp_path):
    source = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(source)
    destination = make_paths(tmp_path, 'destination')
    principal = destination.portfolio_database('portfolio.db')
    DatabaseManager(principal).init_personal_db()
    restores = LocalRestoreService(destination)
    selected = restores.choose_new_destination(
        restores.inspect_cloud_package(artifact.content).portfolios[0], 'Recuperada',
    )
    restored = restores.restore_cloud_package(artifact.content, selected)
    selected = restores.inspect_cloud_package(artifact.content).portfolios[0]
    with pytest.raises(BackupRestoreConflictError):
        restores.choose_existing_destination(selected, principal.name)
    assert set(destination.inspect_portfolios().valid) == {principal, restored.database}


def test_cloud_package_cannot_bypass_password_protection_of_local_restore(tmp_path):
    paths = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(paths)
    with pytest.raises(BackupRestoreCorruptedError):
        LocalRestoreService(paths).inspect_package(
            artifact.content, RestoreCredential.with_password('example password')
        )


@pytest.mark.parametrize('member', ['../outside', '/outside', 'carteiras/../../outside'])
def test_cloud_restore_rejects_paths_outside_the_package(tmp_path, member):
    paths = make_paths(tmp_path, 'destination')
    package = io.BytesIO()
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('manifest.json', b'{}')
        archive.writestr('carteiras/a930c554-997c-462a-8268-761f45380b58/metadata.json', b'{}')
        archive.writestr(member, b'unsafe')
    with pytest.raises(BackupRestoreCorruptedError):
        LocalRestoreService(paths).inspect_cloud_package(package.getvalue())
    assert not (tmp_path / 'outside').exists()
    assert not list(paths.backups_dir.glob('.restore-*'))


def test_corrupted_cloud_snapshot_preserves_the_existing_local_portfolio(tmp_path):
    paths = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(paths)
    database = paths.portfolio_database('portfolio_family.db')
    original = database.read_bytes()
    damaged = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(artifact.content)) as source, zipfile.ZipFile(damaged, 'w') as target:
        for name in source.namelist():
            content = source.read(name)
            target.writestr(name, b'corrupted sqlite' if name.endswith('.sqlite3') else content)
    with pytest.raises(BackupRestoreCorruptedError):
        LocalRestoreService(paths).inspect_cloud_package(damaged.getvalue())
    assert database.read_bytes() == original


def test_cloud_restore_replacement_preserves_a_recovery_copy(tmp_path):
    paths = make_paths(tmp_path, 'source')
    artifact = create_cloud_backup(paths)
    database = paths.portfolio_database('portfolio_family.db')
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("INSERT INTO tracked_market_assets VALUES ('NEW3')")
    restores = LocalRestoreService(paths)
    selected = restores.inspect_cloud_package(artifact.content).portfolios[0]
    assert selected.target.replaces_existing
    result = restores.restore_cloud_package(artifact.content, selected)
    assert result.recovery_directory is not None
    recovery = result.recovery_directory / database.name
    with closing(sqlite3.connect(recovery)) as connection:
        assert ('NEW3',) in connection.execute('SELECT ticker FROM tracked_market_assets').fetchall()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute('SELECT ticker FROM tracked_market_assets').fetchall() == [('TEST3',)]


def test_cloud_backup_rejects_unrestorable_extracted_size(tmp_path, monkeypatch):
    import core.cloud_backup.package as package

    paths = make_paths(tmp_path, 'source')
    monkeypatch.setattr(package, 'MAX_EXTRACTED_BYTES', 1)
    from services.local_backup_service import BackupCreationError
    with pytest.raises(BackupCreationError):
        create_cloud_backup(paths)
    assert not list(paths.local_backups_dir.iterdir())

import pytest
import sqlite3
from contextlib import closing

from core.application_paths import ApplicationPaths
from core.cloud_backup.models import CloudBackupArtifact, CloudBackupError, RemoteBackup
from core.cloud_backup.state import CloudBackupStateStore
from core.database import DatabaseManager
from services.cloud_backup.service import CloudBackupService

PORTFOLIO_ID = 'a930c554-997c-462a-8268-761f45380b58'


def create_portfolio(paths, name, portfolio_id=PORTFOLIO_ID):
    database = paths.portfolio_database(f'portfolio_{name.lower()}.db')
    DatabaseManager(database).init_personal_db()
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute('UPDATE portfolio_metadata SET portfolio_id=?', (portfolio_id,))


class FakeClock:
    value = 0

    def __call__(self):
        return self.value


class FakeProvider:
    def __init__(self):
        self.connected = False
        self.files = {}
        self.uploads = []
        self.fail = False
        self.account = 'account-one'

    def connect(self):
        self.connected = True
        return self.account

    def resume(self):
        return self.account if self.connected else None

    def disconnect(self):
        self.connected = False

    def list_backups(self):
        if self.fail:
            raise CloudBackupError('Não foi possível consultar o Drive.')
        return tuple(self.files.values())

    def upload(self, artifact):
        if self.fail:
            raise CloudBackupError('Não foi possível enviar o backup.')
        key = (artifact.portfolio_id, artifact.installation_id)
        self.uploads.append(artifact)
        previous = self.files.get(key)
        remote = RemoteBackup(
            previous.file_id if previous else f'file-{len(self.files)}',
            *key,
            artifact.display_name,
            artifact.machine_name,
            '2026-10-11T12:00:00Z',
            str(len(self.uploads)),
        )
        self.files[key] = remote
        return remote

    def download(self, remote):
        return self.uploads[-1].content


class FakeBackups:
    fingerprint = 'first'
    portfolio_id = PORTFOLIO_ID
    calls = []

    def create_cloud_backup(self, selection, machine_name):
        self.calls.append(selection.filename)
        return CloudBackupArtifact(
            b'package', self.portfolio_id, self.installation_id, selection.display_name,
            machine_name, f'{self.fingerprint}:{machine_name}',
        )


def make_service(tmp_path, provider=None, name='machine-one'):
    paths = ApplicationPaths(tmp_path / 'bundle', tmp_path / name, tmp_path / 'legacy')
    paths.prepare()
    backups = FakeBackups()
    backups.calls = []
    backups.installation_id = paths.get_or_create_installation_id()
    clock = FakeClock()
    service = CloudBackupService(
        provider or FakeProvider(), CloudBackupStateStore(paths), backups, paths, clock=clock,
    )
    return service, backups, clock, paths


def test_selected_portfolio_is_sent_only_after_ten_minutes(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador 1', enabled=True)
    clock.value = 599
    service.check_due()
    assert not service.provider.uploads
    clock.value = 600
    service.check_due()
    assert len(service.provider.uploads) == 1
    service.check_due()
    assert len(service.provider.uploads) == 1


def test_duplicate_portfolio_identities_cannot_replace_saved_selection(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    create_portfolio(paths, 'Cópia')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    with pytest.raises(CloudBackupError, match='mesma identidade'):
        service.configure(('portfolio_família.db', 'portfolio_cópia.db'), 'Computador', enabled=True)
    assert service.status().selected_filenames == ('portfolio_família.db',)


def test_distinct_portfolio_identities_can_be_selected_together(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    create_portfolio(paths, 'Outra', '3db228de-6d29-49b2-b214-f448824e093a')
    service.connect()
    service.configure(('portfolio_família.db', 'portfolio_outra.db'), 'Computador', enabled=True)
    assert service.status().selected_filenames == ('portfolio_família.db', 'portfolio_outra.db')


def test_drive_quota_error_keeps_service_connected_and_retries_next_interval(tmp_path):
    from tests.test_google_drive_backup import FakeHTTP, Response, make_provider

    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    drive, vault = make_provider(FakeHTTP([
        Response({'error': {'errors': [{'reason': 'rateLimitExceeded'}]}}, status=403),
        Response({'files': []}),
    ]))
    service.provider.list_backups = drive.list_backups
    clock.value = 600
    service.check_due()
    assert service.status().connected
    assert not service.provider.uploads
    clock.value = 1199
    service.check_due()
    assert not service.provider.uploads
    clock.value = 1200
    service.check_due()
    assert len(service.provider.uploads) == 1


def test_retryable_token_refresh_failure_retries_without_new_google_login(tmp_path, monkeypatch):
    import json
    from datetime import datetime
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    from tests.test_google_drive_backup import FakeHTTP, Response, make_provider

    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    drive, vault = make_provider(FakeHTTP([Response({'files': []})]))
    credential = json.loads(vault.content)
    credential['expiry'] = '2000-01-01T00:00:00Z'
    vault.content = json.dumps(credential)
    original = vault.content
    attempts = []

    def refresh(credentials, request):
        attempts.append(True)
        if len(attempts) == 1:
            raise RefreshError('synthetic response', retryable=True)
        credentials.token = 'renewed-access'
        credentials.expiry = datetime(2099, 1, 1)

    monkeypatch.setattr(Credentials, 'refresh', refresh)
    service.provider.list_backups = drive.list_backups
    clock.value = 600
    service.check_due()
    assert service.status().connected
    assert not service.provider.uploads
    assert vault.content == original
    clock.value = 1199
    service.check_due()
    assert len(attempts) == 1
    clock.value = 1200
    service.check_due()
    assert service.status().connected
    assert len(service.provider.uploads) == 1
    assert len(attempts) == 2


def test_legacy_duplicate_identity_selection_does_not_upload_either_copy(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    create_portfolio(paths, 'Cópia')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    with CloudBackupStateStore(paths).transaction() as state:
        settings = state['accounts']['account-one']
        settings['selected'].append('portfolio_cópia.db')
        settings['selected_ids']['portfolio_cópia.db'] = PORTFOLIO_ID
    clock.value = 600
    service.check_due()
    assert not service.provider.uploads
    assert not backups.calls
    assert 'mesma identidade' in service.status().error


def test_backup_updates_one_file_and_leaves_other_installations_copy(tmp_path):
    provider = FakeProvider()
    one, backup_one, clock_one, paths_one = make_service(tmp_path, provider)
    two, backup_two, clock_two, paths_two = make_service(tmp_path, provider, 'machine-two')
    for service, paths, clock in [(one, paths_one, clock_one), (two, paths_two, clock_two)]:
        create_portfolio(paths, 'Família')
        service.connect()
        service.configure(('portfolio_família.db',), 'Computador', enabled=True)
        clock.value = 600
        service.check_due()
    assert len(provider.files) == 2
    first_id = provider.files[(PORTFOLIO_ID, backup_one.installation_id)].file_id
    other = provider.files[(PORTFOLIO_ID, backup_two.installation_id)]
    backup_one.fingerprint = 'changed'
    clock_one.value = 1200
    one.check_due()
    assert len(provider.files) == 2
    assert provider.files[(PORTFOLIO_ID, backup_one.installation_id)].file_id == first_id
    assert provider.files[(PORTFOLIO_ID, backup_two.installation_id)] == other


def test_no_changes_does_not_send_and_failed_upload_retries_on_next_interval(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    clock.value = 1200
    service.check_due()
    assert len(service.provider.uploads) == 1
    backups.fingerprint = 'changed'
    service.provider.fail = True
    clock.value = 1800
    service.check_due()
    assert service.status().error
    assert len(service.provider.uploads) == 1
    service.provider.fail = False
    clock.value = 2399
    service.check_due()
    assert len(service.provider.uploads) == 1
    clock.value = 2400
    service.check_due()
    assert len(service.provider.uploads) == 2


def test_existing_remote_backups_do_not_block_selected_portfolio_upload(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.provider.files[('other', 'other-machine')] = RemoteBackup(
        'old', PORTFOLIO_ID, 'another-installation', 'Família', 'Computador antigo',
        '2026-10-11T12:00:00Z', '1',
    )
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    assert len(service.provider.uploads) == 1
    assert service.provider.files[('other', 'other-machine')].file_id == 'old'


def test_selection_persists_but_new_portfolios_are_not_added_automatically(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    create_portfolio(paths, 'Outra')
    restarted = CloudBackupService(
        service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock,
    )
    restarted.resume()
    assert restarted.status().selected_filenames == ('portfolio_família.db',)
    clock.value = 600
    restarted.check_due()
    assert backups.calls == ['portfolio_família.db']
    restarted.configure((), 'Computador', enabled=True)
    clock.value = 1200
    restarted.check_due()
    assert len(service.provider.files) == 1


def test_unknown_selection_is_rejected_without_changing_persisted_preferences(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    service.connect()
    with pytest.raises(CloudBackupError):
        service.configure(('../outside.db',), 'Computador', enabled=True)
    assert service.status().selected_filenames == ()


def test_deleted_remote_backup_is_recreated_even_when_local_data_is_unchanged(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    service.provider.files.clear()
    clock.value = 1200
    service.check_due()
    assert len(service.provider.uploads) == 2
    assert len(service.provider.files) == 1


@pytest.mark.parametrize('change', ['version', 'file_id', 'legacy_state'])
def test_changed_remote_copy_is_repaired_with_unchanged_local_data_and_survives_restart(tmp_path, change):
    from dataclasses import replace

    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    key = (PORTFOLIO_ID, backups.installation_id)
    remote = service.provider.files[key]
    if change == 'legacy_state':
        with CloudBackupStateStore(paths).transaction() as state:
            state['accounts']['account-one'].pop('sent_remote', None)
    else:
        service.provider.files[key] = replace(remote, **{change: 'changed-remotely'})
    restarted = CloudBackupService(service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock)
    restarted.resume()
    clock.value = 1200
    restarted.check_due()
    assert len(service.provider.uploads) == 2
    clock.value = 1800
    restarted.check_due()
    assert len(service.provider.uploads) == 2


def test_account_lookup_outage_after_consent_retries_automatically_without_new_login(tmp_path):
    import json
    from core.cloud_backup.google_drive import GoogleDriveBackupProvider
    from core.cloud_backup.models import OAuthClientConfiguration
    from tests.test_google_drive_backup import FakeHTTP, Response, make_provider

    http = FakeHTTP([
        Response({}, status=503), Response({'user': {'permissionId': 'account'}}),
        Response({'files': []}),
    ])
    _, vault = make_provider(http)
    issued = json.loads(vault.content)
    vault.content = None
    authorizations = []
    provider = GoogleDriveBackupProvider(
        OAuthClientConfiguration('test-client'), vault, http=http,
        authorize=lambda client: authorizations.append(client) or issued,
    )
    service, _, clock, _ = make_service(tmp_path, provider)
    with pytest.raises(CloudBackupError):
        service.connect()
    assert not service.status().connected
    clock.value = 600
    service.check_due()
    assert service.status().connected
    assert len(authorizations) == 1


def test_restarted_application_waits_ten_minutes_before_sending(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 900
    restarted = CloudBackupService(
        service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock,
    )
    restarted.resume()
    clock.value = 1499
    restarted.check_due()
    assert not service.provider.uploads
    clock.value = 1500
    restarted.check_due()
    assert len(service.provider.uploads) == 1


@pytest.mark.parametrize('operation', ['connect', 'resume'])
def test_temporary_initial_discovery_failure_recovers_before_upload(tmp_path, operation):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.provider.connect()
    service.provider.fail = True
    with pytest.raises(CloudBackupError):
        getattr(service, operation)()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    service.provider.fail = False
    service.provider.files[('other', 'other-machine')] = RemoteBackup(
        'old', PORTFOLIO_ID, 'another-installation', 'Família', 'Computador antigo',
        '2026-10-11T12:00:00Z', '1',
    )
    clock.value = 600
    service.check_due()
    assert service.status().remote_backups
    assert service.status().discovery_complete
    assert len(service.provider.uploads) == 1
    clock.value = 1200
    service.check_due()
    assert len(service.provider.uploads) == 1


def test_recreated_filename_requires_new_backup_consent(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    assert len(service.provider.uploads) == 1
    database = paths.portfolio_database('portfolio_família.db')
    create_portfolio(paths, 'Outra', 'c930c554-997c-462a-8268-761f45380b58')
    assert paths.delete_portfolio(database.name, database.name).deleted
    paths.prepare_portfolio_creation(database.name)
    create_portfolio(paths, 'Família', 'b930c554-997c-462a-8268-761f45380b58')
    backups.fingerprint = 'new-wallet'
    backups.portfolio_id = 'b930c554-997c-462a-8268-761f45380b58'
    clock.value = 1200
    service.check_due()
    assert len(service.provider.uploads) == 1
    assert 'seleção' in service.status().error
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 1800
    service.check_due()
    assert len(service.provider.uploads) == 2
    assert service.provider.uploads[-1].portfolio_id == backups.portfolio_id


def test_failed_credential_removal_can_be_retried_without_connecting(tmp_path, monkeypatch):
    service, backups, clock, paths = make_service(tmp_path)
    service.connect()
    original = service.provider.disconnect
    monkeypatch.setattr(service.provider, 'disconnect', lambda: (_ for _ in ()).throw(CloudBackupError('Cofre bloqueado.')))
    with pytest.raises(CloudBackupError):
        service.disconnect()
    assert not service.status().connected
    assert getattr(service.status(), 'credential_removal_pending', False)
    restarted = CloudBackupService(service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock)
    monkeypatch.setattr(service.provider, 'resume', lambda: pytest.fail('pending removal must not resume OAuth'))
    restarted.resume()
    assert not restarted.status().connected
    assert restarted.status().credential_removal_pending
    monkeypatch.setattr(service.provider, 'disconnect', original)
    service.disconnect()
    assert not service.status().credential_removal_pending
    assert not service.provider.connected


@pytest.mark.parametrize('has_remote_backups', [False, True])
def test_automatic_backup_continues_after_restart_without_recovery_decision(tmp_path, has_remote_backups):
    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    if has_remote_backups:
        service.provider.files[('other', 'other-machine')] = RemoteBackup(
            'old', PORTFOLIO_ID, 'another-installation', 'Família', 'Computador antigo',
            '2026-10-11T12:00:00Z', '1',
        )
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    assert len(service.provider.uploads) == 1
    backups.fingerprint = 'updated'
    clock.value = 900
    restarted = CloudBackupService(service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock)
    restarted.resume()
    assert restarted.status().discovery_complete
    clock.value = 1499
    restarted.check_due()
    assert len(service.provider.uploads) == 1
    clock.value = 1500
    restarted.check_due()
    assert len(service.provider.uploads) == 2


def test_backup_selection_is_not_shared_with_another_account_or_installation(tmp_path):
    service, backups, clock, paths = make_service(tmp_path)
    service.provider.files[('other', 'other-machine')] = RemoteBackup(
        'old', PORTFOLIO_ID, 'another-installation', 'Família', 'Computador antigo',
        '2026-10-11T12:00:00Z', '1',
    )
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    other_installation, _, _, _ = make_service(tmp_path, service.provider, 'machine-two')
    other_installation.resume()
    assert other_installation.status().discovery_complete
    assert not other_installation.status().enabled
    assert not other_installation.status().selected_filenames
    service.provider.account = 'account-two'
    service.connect()
    assert service.status().discovery_complete
    assert not service.status().enabled
    assert not service.status().selected_filenames


@pytest.mark.parametrize('legacy_confirmation', [None, False, True])
def test_newly_selected_portfolio_is_sent_with_legacy_preferences_and_existing_backup(tmp_path, legacy_confirmation):
    from core.sqlite_backup import SQLitePortfolioBackupSourceFactory
    from services.local_backup_service import LocalBackupService

    service, backups, clock, paths = make_service(tmp_path)
    backups = LocalBackupService(SQLitePortfolioBackupSourceFactory(paths), paths, 'test')
    service = CloudBackupService(
        service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock,
    )
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    clock.value = 600
    service.check_due()
    original = tuple(service.provider.files.values())
    create_portfolio(paths, 'Teste', '3db228de-6d29-49b2-b214-f448824e093a')
    service.configure(('portfolio_família.db', 'portfolio_teste.db'), 'Computador', enabled=True)
    with CloudBackupStateStore(paths).transaction() as state:
        preferences = state['accounts']['account-one']
        if legacy_confirmation is None:
            preferences.pop('discovery_complete', None)
        else:
            preferences['discovery_complete'] = legacy_confirmation
    restarted = CloudBackupService(service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock)
    restarted.resume()
    clock.value = 1199
    restarted.check_due()
    assert len(service.provider.uploads) == 1
    clock.value = 1200
    restarted.check_due()
    assert len(service.provider.uploads) == 2
    assert service.provider.uploads[-1].portfolio_id == '3db228de-6d29-49b2-b214-f448824e093a'
    assert original[0] in service.provider.files.values()
    clock.value = 3000
    restarted.check_due()
    assert len(service.provider.uploads) == 2

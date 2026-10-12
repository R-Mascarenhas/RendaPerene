import pytest

from core.application_paths import ApplicationPaths
from core.cloud_backup.models import CloudBackupArtifact, CloudBackupError, RemoteBackup
from core.cloud_backup.state import CloudBackupStateStore
from core.database import DatabaseManager
from services.cloud_backup.service import CloudBackupService

PORTFOLIO_ID = 'a930c554-997c-462a-8268-761f45380b58'


def create_portfolio(paths, name):
    DatabaseManager(paths.portfolio_database(f'portfolio_{name.lower()}.db')).init_personal_db()


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
    calls = []

    def create_cloud_backup(self, selection, machine_name):
        self.calls.append(selection.filename)
        return CloudBackupArtifact(
            b'package', PORTFOLIO_ID, self.installation_id, selection.display_name,
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


def test_backup_updates_one_file_and_leaves_other_installations_copy(tmp_path):
    provider = FakeProvider()
    one, backup_one, clock_one, paths_one = make_service(tmp_path, provider)
    two, backup_two, clock_two, paths_two = make_service(tmp_path, provider, 'machine-two')
    for service, paths, clock in [(one, paths_one, clock_one), (two, paths_two, clock_two)]:
        create_portfolio(paths, 'Família')
        service.connect()
        service.dismiss_discovery()
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


def test_existing_remote_backups_block_upload_until_user_reviews_discovery(tmp_path):
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
    assert not service.provider.uploads
    assert not service.status().discovery_complete
    service.dismiss_discovery()
    service.check_due()
    assert len(service.provider.uploads) == 1


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

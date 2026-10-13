import threading
import time
import pytest
from types import SimpleNamespace

from core.cloud_backup.models import CloudBackupError
from services.cloud_backup.runtime import CloudBackupRuntime


def wait_for_completion(runtime):
    deadline = time.monotonic() + 5
    while runtime.busy and time.monotonic() < deadline:
        runtime.poll()
        time.sleep(0.001)
    assert not runtime.busy


class Service:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.mark.parametrize('previous_check', [0, 300, 1200])
def test_first_backup_runs_ten_minutes_after_resume_even_with_slow_connection_or_new_boot(tmp_path, monkeypatch, previous_check):
    import services.cloud_backup.runtime as module
    from tests.test_cloud_backup_service import make_service, create_portfolio
    from core.cloud_backup.state import CloudBackupStateStore
    from services.cloud_backup.service import CloudBackupService

    service, backups, clock, paths = make_service(tmp_path)
    create_portfolio(paths, 'Família')
    service.connect()
    service.configure(('portfolio_família.db',), 'Computador', enabled=True)
    with CloudBackupStateStore(paths).transaction() as state:
        state['accounts']['account-one']['last_check'] = previous_check
    original_resume = service.provider.resume

    def slow_resume():
        clock.value = 4
        return original_resume()

    monkeypatch.setattr(service.provider, 'resume', slow_resume)
    monkeypatch.setattr(module.time, 'monotonic', clock)
    restarted = CloudBackupService(service.provider, CloudBackupStateStore(paths), backups, paths, clock=clock)
    runtime = CloudBackupRuntime(restarted, None)
    try:
        assert runtime.submit('resume')
        wait_for_completion(runtime)
        clock.value = 600
        runtime.schedule_due()
        wait_for_completion(runtime)
        assert not service.provider.uploads
        clock.value = 604
        runtime.schedule_due()
        wait_for_completion(runtime)
        assert len(service.provider.uploads) == 1
    finally:
        runtime.close()


@pytest.mark.parametrize('operation', ['inspect', 'restore'])
def test_interactive_completion_is_delivered_only_to_owner_even_after_background_check(operation):
    service = Service()
    service.download = lambda remote: b'package'
    preview = SimpleNamespace(installation_id='machine', portfolios=[SimpleNamespace(portfolio_id='portfolio')])
    result = object()
    restores = SimpleNamespace(
        inspect_cloud_package=lambda content: preview,
        restore_cloud_package=lambda *args: result,
    )
    runtime = CloudBackupRuntime(service, restores)
    remote = SimpleNamespace(installation_id='machine', portfolio_id='portfolio')
    try:
        args = (remote,) if operation == 'inspect' else (remote, object())
        assert runtime.submit(operation, *args, result_owner='owner')
        wait_for_completion(runtime)
        assert not runtime.submit(operation, *args, result_owner='owner')
        assert runtime.submit('check_due')
        wait_for_completion(runtime)
        assert runtime.consume_result('other') is None
        completion = runtime.consume_result('owner')
        assert completion.operation == operation
        assert not completion.error
        assert completion.result is result if operation == 'restore' else completion.result == (remote, preview)
        assert runtime.consume_result('owner') is None
    finally:
        runtime.close()


def test_interactive_error_is_preserved_only_for_owner_after_background_check():
    service = Service()

    def failed_download(remote):
        raise CloudBackupError('O backup remoto mudou.')

    service.download = failed_download
    runtime = CloudBackupRuntime(service, None)
    try:
        assert runtime.submit('restore', object(), object(), result_owner='owner')
        wait_for_completion(runtime)
        assert runtime.submit('check_due')
        wait_for_completion(runtime)
        assert runtime.consume_result('other') is None
        completion = runtime.consume_result('owner')
        assert completion.result is None
        assert completion.error == 'O backup remoto mudou.'
    finally:
        runtime.close()


def test_background_upload_does_not_block_status_or_start_another_operation():
    started = threading.Event()
    release = threading.Event()
    service = Service()
    def check_due():
        started.set()
        assert release.wait(5)
    service.check_due = check_due
    runtime = CloudBackupRuntime(service, None)
    try:
        assert runtime.submit('check_due')
        assert started.wait(5)
        assert runtime.busy
        runtime.poll()
        assert not runtime.submit('disconnect')
        release.set()
        wait_for_completion(runtime)
        assert runtime.completed_operation == 'check_due'
        assert not runtime.error
    finally:
        release.set()
        runtime.close()


def test_inspection_rejects_package_that_does_not_match_remote_identity():
    service = Service()
    service.download = lambda remote: b'package'
    restores = SimpleNamespace(inspect_cloud_package=lambda content: SimpleNamespace(
        installation_id='different', portfolios=[SimpleNamespace(portfolio_id='portfolio')],
    ))
    runtime = CloudBackupRuntime(service, restores)
    try:
        runtime.submit('inspect', SimpleNamespace(installation_id='machine', portfolio_id='portfolio'), result_owner='owner')
        wait_for_completion(runtime)
        assert 'identificação' in runtime.error
        assert runtime.result is None
    finally:
        runtime.close()


def test_restore_download_failure_does_not_publish():
    service = Service()
    calls = []
    def download(remote):
        raise CloudBackupError('O backup remoto mudou.')
    service.download = download
    restores = SimpleNamespace(restore_cloud_package=lambda *args: calls.append('publish'))
    runtime = CloudBackupRuntime(service, restores)
    try:
        runtime.submit('restore', object(), object(), result_owner='owner')
        wait_for_completion(runtime)
        assert 'mudou' in runtime.error
        assert not calls
    finally:
        runtime.close()


def test_successful_restore_needs_no_followup_preference_write():
    calls = []
    service = Service()
    service.download = lambda remote: b'package'
    service.mark_restored = lambda: (_ for _ in ()).throw(AssertionError('Unexpected preference write'))
    result = object()

    def restore(content, selected):
        calls.append((content, selected))
        return result

    runtime = CloudBackupRuntime(service, SimpleNamespace(restore_cloud_package=restore))
    try:
        selected = object()
        assert runtime.submit('restore', object(), selected, result_owner='owner')
        wait_for_completion(runtime)
        assert runtime.result is result
        assert not runtime.error
        assert calls == [(b'package', selected)]
    finally:
        runtime.close()


def test_connect_publishes_url_to_its_owner_and_clears_it_when_finished():
    from core.cloud_backup.browser_authorization import BrowserAuthorization

    started = threading.Event()
    release = threading.Event()
    browser = BrowserAuthorization()
    service = Service()
    url = 'https://accounts.google.com/o/oauth2/auth?state=synthetic'
    def connect():
        assert browser.open(url)
        started.set()
        assert release.wait(5)
    service.connect = connect
    runtime = CloudBackupRuntime(service, None, authorization_browser=browser)
    try:
        assert runtime.submit('connect', authorization_owner='owner')
        assert started.wait(5)
        assert browser.pending_url('owner') == url
        assert browser.pending_url('another') == ''
        assert not runtime.submit('connect', authorization_owner='another')
        release.set()
        wait_for_completion(runtime)
        assert not browser.active('owner')
        assert browser.pending_url('owner') == ''
    finally:
        release.set()
        runtime.close()


def test_failed_connect_clears_pending_url_without_affecting_local_use():
    from core.cloud_backup.browser_authorization import BrowserAuthorization

    browser = BrowserAuthorization()
    service = Service()
    def connect():
        browser.open('https://accounts.google.com/o/oauth2/auth?state=synthetic')
        raise CloudBackupError('Conexão cancelada.')
    service.connect = connect
    runtime = CloudBackupRuntime(service, None, authorization_browser=browser)
    try:
        runtime.submit('connect', authorization_owner='owner')
        wait_for_completion(runtime)
        assert 'cancelada' in runtime.error
        assert browser.pending_url('owner') == ''
        assert runtime.submit('check_due')
        wait_for_completion(runtime)
    finally:
        runtime.close()

import threading
import time
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
        runtime.submit('inspect', SimpleNamespace(installation_id='machine', portfolio_id='portfolio'))
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
        runtime.submit('restore', object(), object())
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
        assert runtime.submit('restore', object(), selected)
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

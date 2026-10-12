import json

import pytest

from core.cloud_backup.models import CloudBackupArtifact, CloudBackupError, OAuthClientConfiguration
from core.cloud_backup.google_drive import GoogleDriveBackupProvider

PORTFOLIO = 'a930c554-997c-462a-8268-761f45380b58'
INSTALLATION = 'a7e3a0e3-d0b3-41fb-9406-018d4df54c26'


class FakeVault:
    content = None

    def ensure_available(self):
        pass

    def read(self):
        return self.content

    def write(self, value):
        self.content = value

    def delete(self):
        self.content = None


class Response:
    def __init__(self, payload, status=200, content=b'', headers=None):
        self.payload = payload
        self.status_code = status
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        pass


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def remote_file(file_id='backup'):
    return {
        'id': file_id, 'name': 'Família_PC.rpbc', 'version': '2',
        'modifiedTime': '2026-10-11T12:00:00Z',
        'appProperties': {
            'kind': 'rendaperene-cloud-backup', 'portfolio_id': PORTFOLIO,
            'installation_id': INSTALLATION, 'display_name': 'Família', 'machine_name': 'PC',
        },
    }


def make_provider(http):
    vault = FakeVault()
    vault.content = json.dumps({
        'token': 'fake-access', 'refresh_token': 'fake-refresh',
        'expiry': '2099-01-01T00:00:00Z', 'client_id': 'test-client',
    })
    provider = GoogleDriveBackupProvider(
        OAuthClientConfiguration('test-client'), vault, http=http,
    )
    return provider, vault


def test_drive_upload_updates_only_the_matching_portfolio_and_installation():
    existing = remote_file()
    other_machine = remote_file('other')
    other_machine['appProperties']['installation_id'] = '3db228de-6d29-49b2-b214-f448824e093a'
    http = FakeHTTP([
        Response({'files': [{'id': 'folder'}]}),
        Response({'files': [other_machine, existing]}),
        Response(remote_file()),
    ])
    provider, vault = make_provider(http)
    artifact = CloudBackupArtifact(b'zip bytes', PORTFOLIO, INSTALLATION, 'Família', 'PC', 'hash')
    result = provider.upload(artifact)
    assert result.file_id == 'backup'
    upload = http.calls[-1]
    assert upload[0] == 'PATCH'
    assert upload[1].endswith('/backup')
    assert 'modifiedTime' not in upload[2].get('json', {})
    assert all(call[2]['timeout'] for call in http.calls)
    assert b'zip bytes' in upload[2]['data']


def test_incomplete_listing_does_not_create_duplicate_backup():
    http = FakeHTTP([
        Response({'files': [{'id': 'folder'}]}),
        Response({'files': [], 'incompleteSearch': True}),
    ])
    provider, vault = make_provider(http)
    with pytest.raises(CloudBackupError):
        provider.upload(CloudBackupArtifact(b'zip', PORTFOLIO, INSTALLATION, 'Família', 'PC', 'hash'))
    assert all(call[0] == 'GET' for call in http.calls)


def test_drive_error_does_not_expose_response_body_or_credentials():
    http = FakeHTTP([Response({'error': 'fake-access secret financial content'}, status=403)])
    provider, vault = make_provider(http)
    with pytest.raises(CloudBackupError) as failure:
        provider.list_backups()
    assert 'fake-access' not in str(failure.value)
    assert 'financial' not in str(failure.value)


def test_duplicate_backup_identity_is_not_overwritten_arbitrarily():
    http = FakeHTTP([
        Response({'files': [{'id': 'folder'}]}),
        Response({'files': [remote_file('one'), remote_file('two')]}),
    ])
    provider, vault = make_provider(http)
    with pytest.raises(CloudBackupError):
        provider.upload(CloudBackupArtifact(b'zip', PORTFOLIO, INSTALLATION, 'Família', 'PC', 'hash'))
    assert all(call[0] == 'GET' for call in http.calls)


def test_missing_folder_is_created_with_one_new_backup():
    http = FakeHTTP([
        Response({'files': []}), Response({'files': []}),
        Response({'id': 'folder'}), Response(remote_file()),
    ])
    provider, vault = make_provider(http)
    provider.upload(CloudBackupArtifact(b'zip', PORTFOLIO, INSTALLATION, 'Família', 'PC', 'hash'))
    writes = [call for call in http.calls if call[0] == 'POST']
    assert len(writes) == 2
    assert writes[0][2]['json']['name'] == 'RendaPerene'
    assert b'"parents": ["folder"]' in writes[1][2]['data']


def test_pagination_finds_existing_backup_before_creating_another():
    http = FakeHTTP([
        Response({'files': [{'id': 'folder'}]}),
        Response({'files': [], 'nextPageToken': 'second'}),
        Response({'files': [remote_file()]}), Response(remote_file()),
    ])
    provider, vault = make_provider(http)
    provider.upload(CloudBackupArtifact(b'zip', PORTFOLIO, INSTALLATION, 'Família', 'PC', 'hash'))
    assert http.calls[2][2]['params']['pageToken'] == 'second'
    assert http.calls[-1][0] == 'PATCH'


def test_large_backup_uses_resumable_upload_and_updates_existing_file():
    http = FakeHTTP([
        Response({'files': [{'id': 'folder'}]}), Response({'files': [remote_file()]}),
        Response({}, headers={'Location': 'https://www.googleapis.com/upload/drive/v3/files/backup?upload_id=fake'}),
        Response(remote_file()),
    ])
    provider, vault = make_provider(http)
    content = b'a' * (5 * 1024 * 1024 + 1)
    provider.upload(CloudBackupArtifact(content, PORTFOLIO, INSTALLATION, 'Família', 'PC', 'hash'))
    assert http.calls[-2][0] == 'PATCH'
    assert http.calls[-2][2]['params']['uploadType'] == 'resumable'
    assert http.calls[-1][0] == 'PUT'
    assert http.calls[-1][2]['data'] == content


def test_locked_vault_blocks_drive_operation_even_with_cached_access_token():
    http = FakeHTTP([Response({'files': []})])
    provider, vault = make_provider(http)
    provider._credential = json.loads(vault.content)
    def locked():
        raise CloudBackupError('Cofre bloqueado.')
    vault.read = locked
    with pytest.raises(CloudBackupError, match='Cofre bloqueado'):
        provider.list_backups()
    assert not http.calls


def test_cancelled_google_authorization_does_not_save_tokens():
    from core.cloud_backup.models import CloudAuthorizationError

    vault = FakeVault()
    def cancelled(client):
        raise CloudAuthorizationError('Conexão cancelada.')
    provider = GoogleDriveBackupProvider(OAuthClientConfiguration('test-client'), vault, authorize=cancelled)
    with pytest.raises(CloudAuthorizationError):
        provider.connect()
    assert vault.content is None


def test_failed_token_persistence_reports_revocation_and_does_not_connect():
    provider, vault = make_provider(FakeHTTP([Response({'user': {'permissionId': 'account'}})]))
    provider._authorize = lambda client: json.loads(vault.content)
    def failed_write(value):
        raise CloudBackupError('Cofre indisponível.')
    vault.write = failed_write
    with pytest.raises(CloudBackupError, match='Revogue'):
        provider.connect()


def test_desktop_authorization_uses_pkce_loopback_and_rejects_wrong_state(monkeypatch, caplog):
    import logging
    import io
    from urllib.parse import parse_qs, urlsplit
    from google_auth_oauthlib.flow import Flow
    import core.cloud_backup.google_drive as module

    captured = {}
    caplog.set_level(logging.INFO, logger='core.cloud_backup.google_drive')
    class Server:
        server_port = 54321
        def __init__(self, address, handler):
            captured['address'] = address
            self.handler = handler
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def handle_request(self):
            query = parse_qs(urlsplit(captured['url']).query)
            handler = object.__new__(self.handler)
            handler.send_error = lambda status, *args: captured.setdefault('rejected', status)
            handler.send_response = lambda status: None
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            handler.wfile = io.BytesIO()
            if 'rejected' not in captured:
                handler.path = '/?state=wrong&code=bad'
            else:
                handler.path = f"/?state={query['state'][0]}&code=good"
            handler.do_GET()
    def browser(url):
        captured['url'] = url
        return True
    def fetch_token(flow, **kwargs):
        captured['fetch'] = kwargs
        flow.oauth2session.token = {
            'access_token': 'fake-access', 'refresh_token': 'fake-refresh',
            'token_type': 'Bearer', 'expires_at': 4102444800, 'scope': module.DRIVE_SCOPE,
        }
    monkeypatch.setattr(module, 'HTTPServer', Server)
    monkeypatch.setattr(Flow, 'fetch_token', fetch_token)
    credential = module.authorize_desktop(OAuthClientConfiguration('test-client'), open_browser=browser)
    query = parse_qs(urlsplit(captured['url']).query)
    assert query['code_challenge_method'] == ['S256']
    assert query['redirect_uri'] == ['http://127.0.0.1:54321/']
    assert query['scope'] == [module.DRIVE_SCOPE]
    assert captured['address'] == ('127.0.0.1', 0)
    assert captured['rejected'] == 400
    assert captured['fetch']['code'] == 'good'
    assert captured['fetch']['timeout'] == module.HTTP_TIMEOUT
    assert credential['refresh_token'] == 'fake-refresh'
    assert 'google_oauth.callback.accepted' in caplog.text
    assert 'google_oauth.token_exchange.completed' in caplog.text
    assert 'fake-access' not in caplog.text
    assert 'fake-refresh' not in caplog.text
    assert query['state'][0] not in caplog.text


def test_remote_generation_change_prevents_download():
    original = GoogleDriveBackupProvider._parse_remote(remote_file())
    changed = remote_file()
    changed['version'] = '3'
    http = FakeHTTP([
        Response({'files': [{'id': 'folder'}]}), Response({'files': [changed]}),
    ])
    provider, vault = make_provider(http)
    with pytest.raises(CloudBackupError, match='mudou'):
        provider.download(original)
    assert all(call[2]['params'].get('alt') != 'media' for call in http.calls)


def test_pending_browser_authorization_can_be_cancelled_without_requesting_tokens(monkeypatch):
    from core.cloud_backup.browser_authorization import BrowserAuthorization
    from core.cloud_backup.models import CloudAuthorizationError
    import core.cloud_backup.google_drive as module

    browser = BrowserAuthorization()
    browser.begin('owner')
    closed = []
    class Server:
        server_port = 54321
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            closed.append(True)
        def handle_request(self):
            pytest.fail('Cancellation must end the listener before accepting more callbacks.')
    def open_browser(url):
        assert browser.open(url)
        browser.cancel('owner')
        return True
    monkeypatch.setattr(module, 'HTTPServer', Server)
    with pytest.raises(CloudAuthorizationError, match='cancelada'):
        module.authorize_desktop(
            OAuthClientConfiguration('test-client'), open_browser=open_browser,
            cancelled=browser.cancelled,
        )
    assert closed == [True]
    assert browser.pending_url('owner') == ''

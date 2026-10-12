import pytest

from core.cloud_backup.models import CloudBackupError
from core.cloud_backup.credential_vault import SystemCredentialVault


class FakeBackend:
    def __init__(self):
        self.values = {}
        self.fail = False

    def get_password(self, service, account):
        if self.fail:
            raise RuntimeError('private OS diagnostics')
        return self.values.get((service, account))

    def set_password(self, service, account, value):
        if self.fail:
            raise RuntimeError('private OS diagnostics')
        self.values[service, account] = value

    def delete_password(self, service, account):
        if self.fail:
            raise RuntimeError('private OS diagnostics')
        self.values.pop((service, account), None)


def test_vault_checks_read_write_delete_without_replacing_existing_tokens():
    backend = FakeBackend()
    vault = SystemCredentialVault('test-service', 'test-installation', backend_loader=lambda: backend)
    vault.write('fake-token')
    vault.ensure_available()
    assert vault.read() == 'fake-token'
    assert len(backend.values) == 1
    vault.delete()
    assert not backend.values


def test_locked_or_unavailable_vault_has_no_plaintext_fallback():
    backend = FakeBackend()
    backend.fail = True
    vault = SystemCredentialVault('test-service', 'test-installation', backend_loader=lambda: backend)
    with pytest.raises(CloudBackupError) as failure:
        vault.ensure_available()
    assert 'private OS diagnostics' not in str(failure.value)
    assert not backend.values


def test_missing_windows_components_report_setup_problem_instead_of_locked_vault(monkeypatch):
    import sys

    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setitem(sys.modules, 'keyring.backends.Windows', None)
    vault = SystemCredentialVault('test-service', 'test-installation')
    with pytest.raises(CloudBackupError) as failure:
        vault.ensure_available()
    assert 'componentes' in str(failure.value)
    assert 'Windows' in str(failure.value)
    assert 'Desbloqueie' not in str(failure.value)


def test_sanitized_backend_initialization_error_is_preserved():
    def unavailable():
        raise CloudBackupError('Os componentes do Windows precisam ser instalados.')
    vault = SystemCredentialVault('test-service', 'test-installation', backend_loader=unavailable)
    with pytest.raises(CloudBackupError, match='componentes do Windows'):
        vault.read()

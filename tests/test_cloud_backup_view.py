from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from core.cloud_backup.models import CloudBackupOperationResult, CloudBackupStatus, RemoteBackup


class FakeService:
    current = CloudBackupStatus(True, False, (), 'Computador', True)

    def status(self):
        return self.current


class FakeRuntime:
    def __init__(self):
        self.service = FakeService()
        self.busy = False
        self.error = ''
        self.result = None
        self.completed_operation = None
        self.completed_owner = 'owner'
        self.consumed_revision = -1
        self.revision = 0
        self.calls = []

    def poll(self):
        pass

    def schedule_due(self):
        pass

    def submit(self, operation, *args, **kwargs):
        self.calls.append((operation, args, kwargs))
        if operation == 'configure':
            self.service.current = replace(
                self.service.current, selected_filenames=args[0], machine_name=args[1],
                enabled=kwargs['enabled'],
            )
            self.revision += 1
        elif operation == 'inspect':
            self.result = self.inspection
            self.completed_operation = 'inspect'
            self.completed_owner = kwargs['result_owner']
            self.revision += 1
        return True

    def consume_result(self, owner):
        if self.completed_operation not in {'inspect', 'restore'} or owner != self.completed_owner or self.consumed_revision == self.revision:
            return None
        self.consumed_revision = self.revision
        return CloudBackupOperationResult(self.completed_operation, self.result, self.error)

    def choose_new_destination(self, selected, name):
        return selected

    def choose_existing_destination(self, selected, filename):
        return SimpleNamespace(
            **{**vars(selected), 'target': SimpleNamespace(
                replaces_existing=True, filename=filename, state_token=f'{filename}-state',
            )},
        )


def render_test_screen(runtime):
    import streamlit as st
    from views.cloud_backup.view import render_cloud_backup

    st.session_state.setdefault('cloud_authorization_owner', 'owner')
    render_cloud_backup(runtime, {'portfolio_family.db': 'Família', 'portfolio_other.db': 'Outra'})


@pytest.mark.parametrize('operation', ['inspect', 'restore'])
def test_interactive_result_does_not_change_another_browser_session(operation, monkeypatch):
    from core.utils import SessionManager

    monkeypatch.setattr(SessionManager, 'reset_portfolio_state', lambda: None)
    runtime = FakeRuntime()
    runtime.completed_operation = operation
    runtime.completed_owner = 'owner'
    remote = RemoteBackup('backup', 'portfolio', 'machine', 'Família', 'PC 1', '2026-10-11T12:00:00Z', '1')
    preview = SimpleNamespace(
        portfolios=(SimpleNamespace(
            display_name='Família', target=SimpleNamespace(replaces_existing=False, filename='portfolio_restored.db'),
            backup_is_older_than_local=False,
        ),), app_version='1.2.3', created_at_utc='2026-10-11T12:00:00Z',
        cleanup_warning_path=None, package_sha256='hash',
    )
    runtime.result = SimpleNamespace(
        database=Path('portfolio_restored.db'), recovery_directory=None, cleanup_warning_path=None,
    ) if operation == 'restore' else (remote, preview)
    runtime.revision = 1
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30)
    app.session_state['cloud_authorization_owner'] = 'other'
    app.session_state['active_db'] = 'portfolio_other.db'
    app.run()
    assert not app.exception
    assert app.session_state['active_db'] == 'portfolio_other.db'
    assert 'cloud_restore_preview' not in app.session_state
    owner = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30)
    owner.session_state['active_db'] = 'portfolio_family.db'
    owner.run()
    assert not owner.exception
    if operation == 'restore':
        assert owner.session_state['active_db'] == 'portfolio_restored.db'
    else:
        assert 'cloud_restore_preview' in owner.session_state


def test_user_can_choose_portfolios_and_activate_automatic_backup_without_password():
    runtime = FakeRuntime()
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30).run()
    assert not app.exception
    assert not any('senha' in item.label.lower() for item in app.text_input)
    selection = next(item for item in app.multiselect if item.label == 'Carteiras com backup automático')
    assert selection.value == []
    selection.select('portfolio_family.db')
    next(item for item in app.checkbox if item.label == 'Ativar backup automático').check()
    next(item for item in app.button if item.label == 'Salvar preferências').click().run()
    assert not app.exception
    configured = next(call for call in runtime.calls if call[0] == 'configure')
    assert configured[1][0] == ('portfolio_family.db',)
    assert configured[2]['enabled'] is True
    assert any('10 minutos' in item.value for item in app.caption)


def test_unconfigured_google_client_shows_login_and_explains_application_unavailability():
    def render():
        from views.cloud_backup.view import render_cloud_backup

        render_cloud_backup(None, {}, configuration_error='Configure o cliente OAuth desktop.')

    app = AppTest.from_function(render, default_timeout=30).run()
    assert not app.exception
    assert any('ainda não está disponível nesta versão' in item.value for item in app.info)
    login = next(item for item in app.button if item.label == 'Conectar ao Google')
    assert login.disabled
    assert not app.multiselect
    assert not any('OAuth' in item.value for item in app.info)


def test_login_starts_google_connection_before_showing_portfolio_selection():
    runtime = FakeRuntime()
    runtime.service.current = replace(runtime.service.current, connected=False)
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30).run()
    assert not app.exception
    assert not app.multiselect
    login = next(item for item in app.button if item.label == 'Conectar ao Google')
    assert not login.disabled
    login.click().run()
    assert not app.exception
    assert any(call[0] == 'connect' for call in runtime.calls)
    runtime.service.current = replace(runtime.service.current, connected=True)
    app.run()
    assert any(item.label == 'Carteiras com backup automático' for item in app.multiselect)


def test_drive_restore_requires_preview_destination_and_explicit_confirmation():
    runtime = FakeRuntime()
    remote = RemoteBackup(
        'backup', 'portfolio', 'machine', 'Família', 'PC 1', '2026-10-11T12:00:00Z', '1',
    )
    runtime.service.current = replace(
        runtime.service.current, remote_backups=(remote,), discovery_complete=False,
    )
    selected = SimpleNamespace(
        display_name='Família', target=SimpleNamespace(replaces_existing=False, filename='portfolio_restored.db'),
        backup_is_older_than_local=False,
    )
    runtime.inspection = (remote, SimpleNamespace(
        portfolios=(selected,), app_version='1.2.3', created_at_utc='2026-10-11T12:00:00Z',
        cleanup_warning_path=None, package_sha256='hash',
    ))
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30).run()
    assert not any(call[0] == 'restore' for call in runtime.calls)
    assert not any(item.label == 'Continuar sem restaurar' for item in app.button)
    next(item for item in app.button if item.label == 'Inspecionar backup').click().run()
    app.run()
    assert not app.exception
    restore = next(item for item in app.button if item.label == 'Restaurar carteira do Drive')
    assert restore.disabled
    next(item for item in app.radio if item.label == 'Destino da recuperação').set_value('Criar nova carteira').run()
    next(item for item in app.text_input if item.label == 'Nome da carteira recuperada').input('Família').run()
    assert next(item for item in app.button if item.label == 'Restaurar carteira do Drive').disabled
    next(item for item in app.checkbox if item.label == 'Confirmo a recuperação desta carteira').check().run()
    restore = next(item for item in app.button if item.label == 'Restaurar carteira do Drive')
    assert not restore.disabled
    restore.click().run()
    assert not app.exception
    assert any(call[0] == 'restore' and call[1][0] == remote for call in runtime.calls)


def test_drive_user_can_choose_existing_destination_and_must_reconfirm_after_changing_it():
    runtime = FakeRuntime()
    remote = RemoteBackup('backup', 'portfolio', 'machine', 'Principal', 'PC 1', '2026-10-11T12:00:00Z', '1')
    selected = SimpleNamespace(
        display_name='Principal', target=SimpleNamespace(replaces_existing=False, filename='portfolio_restored.db'),
        backup_is_older_than_local=False,
    )
    runtime.result = (remote, SimpleNamespace(
        portfolios=(selected,), app_version='1.2.3', created_at_utc='2026-10-11T12:00:00Z',
        cleanup_warning_path=None, package_sha256='hash',
    ))
    runtime.completed_operation = 'inspect'
    runtime.revision = 1
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30).run()
    assert not app.exception
    assert next(item for item in app.button if item.label == 'Restaurar carteira do Drive').disabled
    next(item for item in app.selectbox if item.label == 'Carteira local a substituir').select('portfolio_family.db').run()
    next(item for item in app.checkbox if item.label == 'Confirmo a recuperação desta carteira').check().run()
    assert not next(item for item in app.button if item.label == 'Restaurar carteira do Drive').disabled
    next(item for item in app.selectbox if item.label == 'Carteira local a substituir').select('portfolio_other.db').run()
    assert next(item for item in app.button if item.label == 'Restaurar carteira do Drive').disabled
    next(item for item in app.checkbox if item.label == 'Confirmo a recuperação desta carteira').check().run()
    next(item for item in app.button if item.label == 'Restaurar carteira do Drive').click().run()
    assert not app.exception
    restored = next(call[1][1] for call in runtime.calls if call[0] == 'restore')
    assert restored.target.filename == 'portfolio_other.db'
    assert restored.target.replaces_existing


def test_pending_credential_removal_offers_retry_without_google_login():
    runtime = FakeRuntime()
    runtime.service.current = replace(runtime.service.current, connected=False, credential_removal_pending=True)
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30).run()
    assert not app.exception
    assert not any(item.label == 'Conectar ao Google' for item in app.button)
    next(item for item in app.button if item.label == 'Tentar remover credenciais locais').click().run()
    assert not app.exception
    assert runtime.calls[-1][0] == 'disconnect'


def test_failed_inspection_is_consumed_before_a_scheduled_check_clears_its_error():
    runtime = FakeRuntime()
    runtime.completed_operation = 'inspect'
    runtime.revision = 1
    runtime.error = 'O backup remoto mudou.'
    # A failed inspection must never reuse a previous successful inspection result.
    runtime.result = (object(), object())
    def scheduled_check():
        runtime.error = ''
    runtime.schedule_due = scheduled_check
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30).run()
    assert not app.exception
    assert not any(item.label == 'Restaurar carteira do Drive' for item in app.button)


def test_pending_google_login_provides_fallback_link_only_to_its_browser_session():
    from core.cloud_backup.browser_authorization import BrowserAuthorization

    runtime = FakeRuntime()
    runtime.service.current = replace(runtime.service.current, connected=False)
    runtime.busy = True
    browser = BrowserAuthorization()
    runtime.authorization_browser = browser
    browser.begin('owner')
    url = 'https://accounts.google.com/o/oauth2/auth?state=synthetic'
    browser.open(url)
    app = AppTest.from_function(render_test_screen, args=(runtime,), default_timeout=30)
    app.session_state['cloud_authorization_owner'] = 'owner'
    app.run()
    assert not app.exception
    links = app.get('link_button')
    assert len(links) == 1
    assert links[0].proto.url == url
    assert links[0].proto.label == 'Abrir login em nova aba'
    app.session_state['cloud_authorization_owner'] = 'other'
    app.run()
    assert not app.exception
    assert not app.get('link_button')


def test_popup_diagnostics_are_logged_once_without_client_supplied_secrets(monkeypatch, caplog):
    import logging
    import views.cloud_backup.browser_authorization as view
    from core.cloud_backup.browser_authorization import BrowserAuthorization

    payload = {'event': 'opened', 'sequence': 1, 'url': 'private-authorization-url', 'token': 'private-token'}
    monkeypatch.setattr(view, '_popup_renderer', lambda: lambda **kwargs: {'popup_event': payload})
    browser = BrowserAuthorization()
    def render(browser):
        from views.cloud_backup.browser_authorization import render_authorization_browser
        render_authorization_browser(browser, 'owner', enabled=True)
    caplog.set_level(logging.INFO, logger='views.cloud_backup.browser_authorization')
    app = AppTest.from_function(render, args=(browser,), default_timeout=30).run()
    app.run()
    assert not app.exception
    messages = [record.message for record in caplog.records if record.name == 'views.cloud_backup.browser_authorization']
    assert messages == ['google_oauth.popup.opened']
    assert 'private-token' not in caplog.text
    assert 'private-authorization-url' not in caplog.text

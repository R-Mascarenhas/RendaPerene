import pytest

from core.cloud_backup.browser_authorization import BrowserAuthorization

URL = 'https://accounts.google.com/o/oauth2/auth?state=synthetic&code_challenge=public'


def test_authorization_link_is_visible_only_to_the_session_that_started_login():
    browser = BrowserAuthorization()
    browser.begin('owner')
    assert browser.open(URL)
    assert browser.pending_url('owner') == URL
    assert browser.pending_url('other-session') == ''
    browser.finish()
    assert browser.pending_url('owner') == ''
    assert not browser.active('owner')


def test_other_session_cannot_cancel_authorization():
    browser = BrowserAuthorization()
    browser.begin('owner')
    browser.cancel('other')
    assert not browser.cancelled()
    browser.cancel('owner')
    assert browser.cancelled()
    assert not browser.open(URL)
    browser.finish()
    browser.begin('next')
    assert not browser.cancelled()


@pytest.mark.parametrize('url', [
    'http://accounts.google.com/o/oauth2/auth',
    'https://accounts.google.com.evil.example/auth',
    'https://accounts.google.com@evil.example/auth',
    'javascript:alert(1)',
])
def test_only_google_https_authorization_urls_are_published(url):
    browser = BrowserAuthorization()
    browser.begin('owner')
    assert not browser.open(url)
    assert browser.pending_url('owner') == ''


def test_completion_revision_changes_only_when_an_owners_attempt_ends():
    browser = BrowserAuthorization()
    browser.begin('owner')
    assert browser.completed_revision('owner') == 0
    assert browser.completed_revision('another') == 0
    browser.finish()
    assert browser.completed_revision('owner') == 1
    assert browser.completed_revision('another') == 0
    browser.finish()
    assert browser.completed_revision('owner') == 1
    browser.begin('owner')
    assert browser.completed_revision('owner') == 1
    browser.finish()
    assert browser.completed_revision('owner') == 2


def test_authorization_lifecycle_logs_do_not_contain_url_state_or_session(caplog):
    import logging

    caplog.set_level(logging.INFO, logger='core.cloud_backup.browser_authorization')
    browser = BrowserAuthorization()
    browser.begin('private-session')
    browser.open('https://accounts.google.com/o/oauth2/auth?state=private-state')
    browser.finish()
    assert [record.message for record in caplog.records] == [
        'google_oauth.browser.started', 'google_oauth.browser.url_ready', 'google_oauth.browser.finished',
    ]
    assert 'private-session' not in caplog.text
    assert 'private-state' not in caplog.text

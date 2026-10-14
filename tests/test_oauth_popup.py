import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('blocked', [False, True])
def test_popup_opens_on_click_in_the_current_browser_then_receives_google_url(tmp_path, blocked):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for browser-side authorization checks.')
    source = (Path(__file__).resolve().parents[1] / 'views' / 'cloud_backup' / 'oauth_popup.js').read_text()
    # Execute the actual frontend renderer against browser API doubles, without Google/network.
    harness = """
import assert from 'node:assert/strict';
const listeners = new Set();
const click = event => { for (const listener of [...listeners]) listener(event); };
const popup = {opener: {}, document: {body: {}}, location: {
  replace(url) { this.url = url; }
}, close() { this.wasClosed = true; }, closed: false};
globalThis.document = {
  addEventListener(name, callback, capture) { assert.equal(capture, true); listeners.add(callback); },
  removeEventListener(name, callback) { listeners.delete(callback); }
};
globalThis.window = {open(url, target, features) {
  this.opened = {url, target, features};
  return BLOCKED ? null : popup;
}};
const events = [];
const renderWithEvents = data => render({data, setTriggerValue(name, event) {
  assert.equal(name, 'popup_event'); events.push(event);
}});
let cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 0});
const previousCleanup = cleanup;
cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 0});
assert.equal(listeners.size, 1);
previousCleanup();
assert.equal(listeners.size, 1);
assert.equal(window.opened, undefined);
const button = {textContent: 'Conectar ao Google', disabled: false};
click({target: {closest() { return button; }}});
assert.equal(window.opened.url, 'about:blank');
assert.match(window.opened.features, /popup=yes/);
assert.equal(popup.location.url, undefined);
cleanup();
// A component update can arrive before the click is acknowledged by Python.
cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 0});
if (!BLOCKED) assert.notEqual(popup.wasClosed, true, 'Preparing popup closed before server acknowledgment');
cleanup();
const google = 'https://accounts.google.com/o/oauth2/auth?state=synthetic';
cleanup = renderWithEvents({session: 'owner', enabled: false, active: true, url: google, completed: 0});
if (!BLOCKED) {
  assert.equal(popup.location.url, google);
  assert.equal(popup.opener, null);
}
cleanup();
cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 1});
if (!BLOCKED) assert.equal(popup.wasClosed, true);
cleanup();
await new Promise(resolve => setTimeout(resolve, 10));
assert.equal(events[0].event, BLOCKED ? 'blocked' : 'opened');
assert.ok(events.some(item => item.event === (BLOCKED ? 'unavailable' : 'navigated')));
assert.ok(events.some(item => item.event === 'finished'));
assert.equal(JSON.stringify(events).includes(google), false);
// A retry uses the last completion as its baseline, including an immediate backend failure.
popup.wasClosed = false;
cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 1});
click({target: {closest() { return button; }}});
cleanup();
cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 1});
if (!BLOCKED) assert.equal(popup.wasClosed, false);
cleanup();
cleanup = renderWithEvents({session: 'owner', enabled: true, active: false, url: '', completed: 2});
if (!BLOCKED) assert.equal(popup.wasClosed, true);
cleanup();
// A disabled button never opens another window.
window.opened = undefined;
cleanup = render({data: {session: 'owner', enabled: false, active: false, url: ''}});
click({target: {closest() { return button; }}});
assert.equal(window.opened, undefined);
cleanup();
""".replace('BLOCKED', json.dumps(blocked))
    script = tmp_path / 'popup-test.mjs'
    script.write_text(source.replace('export default function', 'function render') + harness)
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

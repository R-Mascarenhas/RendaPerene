#!/usr/bin/env bash
# Install/remove packages only on a disposable Ubuntu CI runner.
set -euo pipefail
if [[ "${CI:-}" != "true" ]]; then
    echo "Run package lifecycle tests only on a disposable CI Ubuntu runner." >&2
    exit 1
fi

package="$(realpath "$1")"
temporary="$(mktemp -d)"
application_pid=""
cleanup() {
    if [[ -n "$application_pid" ]]; then
        kill "$application_pid" 2>/dev/null || true
        wait "$application_pid" 2>/dev/null || true
    fi
    rm -rf "$temporary"
}
trap cleanup EXIT
export XDG_DATA_HOME="$temporary/data"
mkdir -p "$XDG_DATA_HOME/RendaPerene/database"
marker="$XDG_DATA_HOME/RendaPerene/database/installer-test.txt"
echo "synthetic portfolio data" > "$marker"

dpkg-deb --raw-extract "$package" "$temporary/previous"
sed -i 's/^Version: .*/Version: 0.0.0/' "$temporary/previous/DEBIAN/control"
echo "obsolete private runtime" > "$temporary/previous/opt/rendaperene/_internal/obsolete-installer-test.txt"
dpkg-deb --root-owner-group --build "$temporary/previous" "$temporary/previous.deb"
sudo apt-get install --no-install-recommends -y "$temporary/previous.deb"
test "$(dpkg-query -W -f='${Version}' rendaperene)" = "0.0.0"
test -x /usr/bin/rendaperene
test -f /usr/share/applications/rendaperene.desktop

# An active executable must block upgrade/removal before package files change.
RENDAPERENE_HEADLESS=true RENDAPERENE_PORT=18501 /usr/bin/rendaperene >/dev/null 2>&1 &
application_pid=$!
for _ in $(seq 1 100); do
    if [[ "$(readlink "/proc/$application_pid/exe" || true)" == "/opt/rendaperene/RendaPerene" ]]; then
        break
    fi
    sleep 0.1
done
test "$(readlink "/proc/$application_pid/exe")" = "/opt/rendaperene/RendaPerene"
if sudo dpkg --install "$package"; then
    echo "Upgrade unexpectedly succeeded while the application was running." >&2
    exit 1
fi
if sudo dpkg --remove rendaperene; then
    echo "Removal unexpectedly succeeded while the application was running." >&2
    exit 1
fi
test -f /opt/rendaperene/_internal/obsolete-installer-test.txt
kill "$application_pid"
wait "$application_pid" || true
application_pid=""

sudo dpkg --install "$package"
expected_version="$(dpkg-deb --field "$package" Version)"
test "$(dpkg-query -W -f='${Version}' rendaperene)" = "$expected_version"
test ! -e /opt/rendaperene/_internal/obsolete-installer-test.txt
test "$(cat "$marker")" = "synthetic portfolio data"
grep -qx 'Exec=/usr/bin/rendaperene' /usr/share/applications/rendaperene.desktop
.venv-packaging/bin/python scripts/smoke_bundle.py /usr/bin/rendaperene
sudo dpkg --remove rendaperene
test ! -e /usr/bin/rendaperene
test ! -e /usr/share/applications/rendaperene.desktop
test "$(cat "$marker")" = "synthetic portfolio data"

#!/usr/bin/env bash
set -euo pipefail

app_version="$(tr -d '[:space:]' < version.txt)"
test -n "$app_version"
if [[ "${GITHUB_REF_TYPE:-}" == "tag" && "${GITHUB_REF_NAME#v}" != "$app_version" ]]; then
    echo "Release tag does not match version.txt" >&2
    exit 1
fi

python3 -m pip install --upgrade pip
python3 -m pip install ".[packaging]"
python3 -m PyInstaller --clean --noconfirm --distpath dist --workpath build RendaPerene.spec

archive="dist/RendaPerene-v${app_version}-ubuntu-x64.tar.gz"
rm -f "$archive"
tar -czf "$archive" -C dist "RendaPerene-v${app_version}"
python3 scripts/validate_bundle.py "dist/RendaPerene-v${app_version}" "$app_version"
python3 scripts/smoke_bundle.py "dist/RendaPerene-v${app_version}/RendaPerene-v${app_version}"

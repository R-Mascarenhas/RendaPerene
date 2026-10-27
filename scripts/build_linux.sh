#!/usr/bin/env bash
set -euo pipefail

app_version="$(tr -d '[:space:]' < version.txt)"
test -n "$app_version"
if [[ "${GITHUB_REF_TYPE:-}" == "tag" && "${GITHUB_REF_NAME#v}" != "$app_version" ]]; then
    echo "Release tag does not match version.txt" >&2
    exit 1
fi

build_venv=".venv-packaging"
if [[ ! -x "$build_venv/bin/python" ]]; then
    python3 -m venv "$build_venv"
fi
build_python="$build_venv/bin/python"
"$build_python" -m pip install --upgrade pip
"$build_python" -m pip install ".[packaging]"
"$build_python" -m PyInstaller --clean --noconfirm --distpath dist --workpath build RendaPerene.spec

"$build_python" scripts/validate_bundle.py dist/RendaPerene "$app_version"
"$build_python" scripts/smoke_bundle.py dist/RendaPerene/RendaPerene
"$build_python" -m scripts.build_deb dist/RendaPerene "$app_version"

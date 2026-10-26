import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.build_deb import build_deb

pytestmark = pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="Requires dpkg-deb")


@pytest.fixture
def bundle(tmp_path):
    directory = tmp_path / "RendaPerene"
    resources = directory / "_internal"
    for name in ("core", "views", "services"):
        (resources / name).mkdir(parents=True)
    for name in ("app.py", "assets.csv", "views/cloud_backup/oauth_popup.js"):
        resource = resources / name
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("synthetic package resource", encoding="utf-8")
    (resources / "version.txt").write_text("1.2.0", encoding="utf-8")
    (directory / "RendaPerene").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    return directory


def test_deb_installs_stable_command_and_desktop_entry_with_versioned_metadata(bundle, tmp_path):
    package = build_deb(bundle, "1.2.0", tmp_path / "dist")

    assert package.name == "RendaPerene-v1.2.0-ubuntu-x64.deb"
    metadata = subprocess.check_output(["dpkg-deb", "--field", str(package)], text=True)
    assert "Package: rendaperene\n" in metadata
    assert "Version: 1.2.0\n" in metadata
    assert "Architecture: amd64\n" in metadata
    assert "libc6 (>= 2.35)" in metadata
    extracted = tmp_path / "installed"
    subprocess.run(["dpkg-deb", "--extract", str(package), str(extracted)], check=True)
    executable = extracted / "opt/rendaperene/RendaPerene"
    assert executable.stat().st_mode & 0o111
    launcher = extracted / "usr/bin/rendaperene"
    assert launcher.stat().st_mode & 0o111
    assert 'exec /opt/rendaperene/RendaPerene "$@"' in launcher.read_text()
    desktop = (extracted / "usr/share/applications/rendaperene.desktop").read_text()
    assert "Exec=/usr/bin/rendaperene\n" in desktop
    assert "Terminal=false\n" in desktop
    assert (extracted / "opt/rendaperene/_internal/version.txt").read_text() == "1.2.0"
    assert not (extracted / "home").exists()
    assert not (extracted / "root").exists()


@pytest.mark.parametrize("relative_path", ["portfolio.db", "_internal/portfolio.db", "token.key"])
def test_package_rejects_personal_files_anywhere_in_bundle(bundle, tmp_path, relative_path):
    (bundle / relative_path).write_text("synthetic private data")

    with pytest.raises(ValueError, match="Personal or generated"):
        build_deb(bundle, "1.2.0", tmp_path / "dist")

    assert not list(tmp_path.glob("dist/*.deb"))


def test_package_rejects_mismatched_resource_version(bundle, tmp_path):
    with pytest.raises(ValueError, match="version does not match"):
        build_deb(bundle, "1.3.0", tmp_path / "dist")


@pytest.mark.parametrize("version", ["../1.2.0", "01.2.0", "1.2", "1.2.0\nDepends: other"])
def test_package_rejects_invalid_version_before_creating_output(bundle, tmp_path, version):
    with pytest.raises(ValueError, match="semantic X.Y.Z"):
        build_deb(bundle, version, tmp_path / "dist")

    assert not (tmp_path / "dist").exists()

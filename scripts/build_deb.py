"""Build a local-first Ubuntu desktop package from a validated PyInstaller bundle."""

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.validate_bundle import validate_bundle

RUNNING_APPLICATION_CHECK = """#!/bin/sh
set -eu
case "${1:-}" in
  install|upgrade|remove|deconfigure)
    for executable in /proc/[0-9]*/exe; do
      target=$(readlink "$executable" 2>/dev/null || true)
      case "$target" in
        /opt/rendaperene/RendaPerene|"/opt/rendaperene/RendaPerene (deleted)")
          echo "Feche o RendaPerene antes de atualizar ou remover o aplicativo." >&2
          exit 1
          ;;
      esac
    done
    ;;
esac
exit 0
"""


def build_deb(bundle: Path, version: str, output_directory: Path) -> Path:
    """Create an amd64 DEB; never include or touch the user's application data."""
    if re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version) is None:
        raise ValueError("Package version must use semantic X.Y.Z format")
    validate_bundle(bundle, version)
    executable = bundle / "RendaPerene"
    if not executable.is_file():
        raise ValueError("Bundle is missing the RendaPerene executable")
    output_directory.mkdir(parents=True, exist_ok=True)
    package = output_directory.resolve() / f"RendaPerene-v{version}-ubuntu-x64.deb"
    with tempfile.TemporaryDirectory(prefix="rendaperene-deb-") as temporary:
        stage = Path(temporary)
        stage.chmod(0o755)
        application = stage / "opt/rendaperene"
        application.parent.mkdir(parents=True)
        shutil.copytree(bundle, application, symlinks=True)
        (application / "RendaPerene").chmod(0o755)

        launcher = stage / "usr/bin/rendaperene"
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/sh\nexec /opt/rendaperene/RendaPerene "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
        desktop = stage / "usr/share/applications/rendaperene.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text(
            "[Desktop Entry]\nType=Application\nName=RendaPerene\n"
            "Comment=Carteira de investimentos e planejamento de aposentadoria\n"
            "Exec=/usr/bin/rendaperene\nTryExec=/usr/bin/rendaperene\n"
            "Icon=office-chart-line\nTerminal=false\nCategories=Office;Finance;\n",
            encoding="utf-8",
        )
        installed_size = sum(
            path.stat().st_size for path in application.rglob("*") if path.is_file()
        )
        control = stage / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            f"Package: rendaperene\nVersion: {version}\nArchitecture: amd64\n"
            "Maintainer: RendaPerene <noreply@github.com>\nSection: misc\nPriority: optional\n"
            f"Installed-Size: {(installed_size + 1023) // 1024}\n"
            "Depends: libc6 (>= 2.35), libstdc++6, libgcc-s1, zlib1g, libglib2.0-0, "
            "libdbus-1-3, libsecret-1-0, xdg-utils\n"
            "Recommends: gnome-keyring\n"
            "Homepage: https://github.com/R-Mascarenhas/RendaPerene\n"
            "Description: Carteira de investimentos e planejamento de aposentadoria\n"
            " Aplicativo local para acompanhamento de carteiras B3.\n",
            encoding="utf-8",
        )
        for hook in ("preinst", "prerm"):
            script = control / hook
            script.write_text(RUNNING_APPLICATION_CHECK, encoding="utf-8")
            script.chmod(0o755)
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)], check=True
        )
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("version")
    parser.add_argument("--output", type=Path, default=Path("dist"))
    arguments = parser.parse_args()
    build_deb(arguments.bundle, arguments.version, arguments.output)


if __name__ == "__main__":
    main()

# ruff: noqa: F821, I001, UP009
"""Common PyInstaller definition for native Windows and Linux builds."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


ROOT = Path(SPECPATH)
version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
if not version:
    raise ValueError("version.txt must contain a non-empty release version")

datas = [
    (str(ROOT / "app.py"), "."),
    (str(ROOT / "assets.csv"), "."),
    (str(ROOT / "version.txt"), "."),
]
binaries = []
hiddenimports = []

# Streamlit and Plotly load templates, static files, and plugins dynamically.
for package in ("streamlit", "plotly"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)
    datas.extend(copy_metadata(package))

# app.py is executed later by Streamlit, so Analysis cannot discover its imports directly.
for package in ("core", "views", "services"):
    hiddenimports.extend(collect_submodules(package))

# yfinance is imported by the market-data adapter during Streamlit startup.
yfinance_datas, yfinance_binaries, yfinance_hiddenimports = collect_all("yfinance")
datas.extend(yfinance_datas)
binaries.extend(yfinance_binaries)
hiddenimports.extend(yfinance_hiddenimports)

# Application modules are resources because Streamlit receives app.py as a script.
for package in ("core", "views", "services"):
    datas.append((str(ROOT / package), package))


a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=f"RendaPerene-v{version}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=f"RendaPerene-v{version}",
)

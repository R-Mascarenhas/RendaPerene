# run_app.py
import os
import shutil
import sys

# Force PyInstaller to index library dependencies in the executable bundle
import streamlit.web.cli as stcli


def resolve_path(relative_path: str) -> str:
    """Resolves absolute path for packaged assets under PyInstaller or dev mode."""
    try:
        # PyInstaller unpacks bundled resources to sys._MEIPASS at runtime
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    # Ensure database and assets are persisted locally on the host, not in temporary unpacked paths
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
    else:
        exe_dir = os.path.abspath(".")

    os.chdir(exe_dir)

    os.makedirs("database", exist_ok=True)

    # Copy fallback catalog assets.csv if not present locally
    local_assets_csv = "assets.csv"
    if not os.path.exists(local_assets_csv):
        try:
            bundled_assets_csv = resolve_path("assets.csv")
            if os.path.exists(bundled_assets_csv):
                shutil.copy(bundled_assets_csv, local_assets_csv)
        except Exception as e:
            sys.stderr.write(f"Error initializing assets.csv: {e}\n")

    script_path = resolve_path("app.py")

    # Configure command line arguments to run Streamlit in quiet offline mode
    sys.argv = [
        "streamlit",
        "run",
        script_path,
        "--global.developmentMode=false",
        "--server.port=8501",
        "--server.headless=false",
        "--server.showEmailPrompt=false",
        "--browser.gatherUsageStats=false",
    ]

    sys.exit(stcli.main())

# run_app.py
import sys

# Force PyInstaller to index library dependencies in the executable bundle
import streamlit.web.cli as stcli

from core.application_paths import ApplicationPaths

if __name__ == "__main__":
    app_paths = ApplicationPaths.discover()
    script_path = app_paths.bundled_resource("app.py")

    # Configure command line arguments to run Streamlit in quiet offline mode
    sys.argv = [
        "streamlit",
        "run",
        str(script_path),
        "--global.developmentMode=false",
        "--server.port=8501",
        "--server.headless=false",
        "--server.showEmailPrompt=false",
        "--browser.gatherUsageStats=false",
    ]

    sys.exit(stcli.main())

import os
import sys

# Force PyInstaller to index library dependencies in the executable bundle
import streamlit.web.cli as stcli

from core.application_paths import ApplicationPaths
from core.utils.session import configure_session_log

if __name__ == "__main__":
    app_paths = ApplicationPaths.discover()
    app_paths.logs_dir.mkdir(parents=True, exist_ok=True)
    configure_session_log(app_paths.logs_dir / "session_debug.log")
    script_path = app_paths.bundled_resource("app.py")

    # Configure command line arguments to run Streamlit in quiet offline mode.
    port = os.environ.get("RENDAPERENE_PORT", "8501")
    sys.argv = [
        "streamlit",
        "run",
        str(script_path),
        "--global.developmentMode=false",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=false",
        "--server.showEmailPrompt=false",
        "--browser.gatherUsageStats=false",
    ]

    sys.exit(stcli.main())

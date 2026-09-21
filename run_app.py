import logging
import os
import sys

# Force PyInstaller to index library dependencies in the executable bundle
import streamlit.web.cli as stcli

from core.application_paths import ApplicationPaths
from core.logging_config import configure_logging

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    app_paths = ApplicationPaths.discover()
    configure_logging(app_paths.logs_dir)
    logger.info("application.launcher_started")
    script_path = app_paths.bundled_resource("app.py")

    # Configure command line arguments to run Streamlit in quiet offline mode.
    port = os.environ.get("RENDAPERENE_PORT", "8501")
    headless = os.environ.get("RENDAPERENE_HEADLESS", "false").casefold() == "true"
    sys.argv = [
        "streamlit",
        "run",
        str(script_path),
        "--global.developmentMode=false",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        f"--server.headless={str(headless).lower()}",
        "--server.showEmailPrompt=false",
        "--browser.gatherUsageStats=false",
    ]

    sys.exit(stcli.main())

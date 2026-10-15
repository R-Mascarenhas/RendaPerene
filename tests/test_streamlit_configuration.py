"""Verify the effective configuration used by documented source launches."""

import os
import subprocess
import sys
from pathlib import Path


def test_source_launch_disables_streamlit_usage_statistics():
    environment = os.environ.copy()
    environment.pop("STREAMLIT_BROWSER_GATHER_USAGE_STATS", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import streamlit; print(streamlit.get_option('browser.gatherUsageStats'))",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip() == "False"

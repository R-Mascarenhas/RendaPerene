"""Start a packaged application and verify that its Streamlit server responds."""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    executable = Path(sys.argv[1]).resolve()
    if not executable.is_file():
        raise SystemExit(f"Packaged executable was not found: {executable}")
    with tempfile.TemporaryDirectory(prefix="rendaperene-smoke-") as data_root:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = os.environ.copy()
        environment["XDG_DATA_HOME"] = data_root
        environment["LOCALAPPDATA"] = data_root
        environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        environment["RENDAPERENE_PORT"] = str(port)
        process = subprocess.Popen(
            [str(executable)],
            cwd=executable.parent,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise SystemExit(
                        f"Packaged Streamlit application exited with code {process.returncode}"
                    )
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                        if response.status < 500:
                            return 0
                except (OSError, urllib.error.URLError):
                    time.sleep(0.5)
            raise SystemExit("Packaged Streamlit application did not start within 45 seconds")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())

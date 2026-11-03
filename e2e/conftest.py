"""Own the Streamlit subprocess independently of the in-process test adapters."""

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption(
        "--e2e-executable",
        default=None,
        help="Installed Windows executable for native navigation tests",
    )


class AppServer:
    def __init__(self, sandbox, artifacts, executable=None):
        self.sandbox = sandbox
        self.artifacts = artifacts
        self.executable = executable
        self.data_root = sandbox / "data"
        if executable is not None:
            self.data_root /= "RendaPerene"
        self.process = None
        self.log = None
        self.starts = 0
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def start(self):
        self.starts += 1
        self.log = (self.artifacts / f"server-{self.starts}.log").open("w")
        environment = os.environ.copy()
        environment.update(
            RENDAPERENE_E2E_ROOT=str(self.sandbox),
            RENDAPERENE_GOOGLE_OAUTH_CLIENT_FILE=str(self.sandbox / "no-oauth.json"),
            PYTHONPATH=str(ROOT),
            APP_ENV="prod",
            LOG_TO_FILE="false",
        )
        if self.executable is not None:
            environment.update(
                WIN_PD_OVERRIDE_LOCAL_APPDATA=str(self.sandbox / "data"),
                WIN_PD_OVERRIDE_APPDATA=str(self.sandbox / "roaming"),
                RENDAPERENE_HEADLESS="true",
                RENDAPERENE_PORT=str(self.port),
                STREAMLIT_BROWSER_GATHER_USAGE_STATS="false",
            )
            command = [str(self.executable)]
            working_directory = self.executable.parent
        else:
            command = [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "e2e/app_runner.py",
                "--server.address=127.0.0.1",
                f"--server.port={self.port}",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
                "--server.fileWatcherType=none",
            ]
            working_directory = ROOT
        self.process = subprocess.Popen(
            command,
            cwd=working_directory,
            env=environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Streamlit exited; see {self.log.name}")
            try:
                with urlopen(f"{self.url}/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except (URLError, TimeoutError):
                pass
            time.sleep(0.1)
        raise TimeoutError(f"Streamlit did not start; see {self.log.name}")

    def stop(self):
        try:
            if self.process is not None and self.process.poll() is not None:
                self.log.write(f"\nServer exited before teardown: {self.process.returncode}\n")
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self.log is not None:
                self.log.close()

    def restart(self):
        self.stop()
        self.start()


@pytest.fixture
def app_server(tmp_path, output_path, pytestconfig):
    executable_name = pytestconfig.getoption("--e2e-executable")
    executable = Path(executable_name).resolve() if executable_name else None
    if executable is not None:
        if sys.platform != "win32" or not executable.is_file():
            raise pytest.UsageError("Native navigation requires a Windows executable on Windows")
        if (
            executable.parent / "database"
        ).exists() or executable.parent.name.casefold().startswith("rendaperene-v"):
            raise pytest.UsageError("Use a bundle without legacy portfolio discovery candidates")
    resources = tmp_path / "resources"
    resources.mkdir()
    shutil.copyfile(ROOT / "assets.csv", resources / "assets.csv")
    shutil.copyfile(ROOT / "version.txt", resources / "version.txt")
    artifacts = Path(output_path)
    artifacts.mkdir(parents=True, exist_ok=True)
    server = AppServer(tmp_path, artifacts, executable)
    try:
        server.start()
        yield server
    finally:
        server.stop()


@pytest.fixture
def local_page(page, app_server):
    expect.set_options(timeout=15000)
    # Also stop browser-side external requests (for example, ticker logos).
    page.context.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(app_server.url + "/")
            else route.abort()
        ),
    )
    page.set_default_timeout(15000)
    page.on("websocket", lambda connection: setattr(page, "streamlit_socket", connection))
    page.goto(app_server.url)
    page.get_by_role("textbox", name="Nome da Nova Carteira", exact=True).wait_for(timeout=60000)
    expect(page.get_by_test_id("stApp")).to_have_attribute(
        "data-test-script-state", "notRunning", timeout=60000
    )
    return page

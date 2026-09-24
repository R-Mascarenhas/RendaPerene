import logging

import pytest

from core.update_checker import UpdateChecker


def release_payload(version="1.2.0", assets=None):
    if assets is None:
        assets = [
            {
                "name": f"RendaPerene-v{version}-windows-x64.zip",
                "browser_download_url": "https://github.com/R-Mascarenhas/RendaPerene/releases/download/"
                f"v{version}/RendaPerene-v{version}-windows-x64.zip",
            },
            {
                "name": f"RendaPerene-v{version}-ubuntu-x64.tar.gz",
                "browser_download_url": "https://github.com/R-Mascarenhas/RendaPerene/releases/download/"
                f"v{version}/RendaPerene-v{version}-ubuntu-x64.tar.gz",
            },
        ]
    return {"tag_name": f"v{version}", "body": "Correções importantes.", "assets": assets}


def test_check_returns_newer_windows_release_with_matching_asset():
    checker = UpdateChecker(lambda timeout: release_payload())

    update = checker.check("1.1.0", platform_name="win32")

    assert update is not None
    assert update.version == "1.2.0"
    assert update.release_notes == "Correções importantes."
    assert update.download_url.endswith("RendaPerene-v1.2.0-windows-x64.zip")


@pytest.mark.parametrize("installed_version", ["1.2.0", "1.3.0"])
def test_check_ignores_release_that_is_not_newer(installed_version):
    checker = UpdateChecker(lambda timeout: release_payload())

    assert checker.check(installed_version, platform_name="win32") is None


def test_check_selects_linux_asset_by_its_expected_name():
    checker = UpdateChecker(lambda timeout: release_payload())

    update = checker.check("1.1.0", platform_name="linux")

    assert update is not None
    assert update.download_url.endswith("RendaPerene-v1.2.0-ubuntu-x64.tar.gz")


@pytest.mark.parametrize(
    ("platform_name", "machine_name"),
    [("linux", "aarch64"), ("linux", "i686"), ("win32", "arm64")],
)
def test_check_ignores_release_without_a_compatible_x64_package(platform_name, machine_name):
    checker = UpdateChecker(lambda timeout: release_payload())

    assert checker.check("1.1.0", platform_name=platform_name, machine_name=machine_name) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"tag_name": "release-1.2.0", "assets": []},
        {"tag_name": "v01.2.0", "assets": []},
        release_payload(assets=[]),
    ],
)
def test_check_ignores_invalid_release_or_missing_platform_asset(payload):
    checker = UpdateChecker(lambda timeout: payload)

    assert checker.check("1.1.0", platform_name="win32") is None


def test_check_handles_network_errors_without_logging_download_url(caplog):
    download_url = "https://example.invalid/private-installer.zip"

    def fail_fetch(_timeout):
        raise OSError(download_url)

    checker = UpdateChecker(fail_fetch)
    with caplog.at_level(logging.WARNING, logger="core.update_checker"):
        assert checker.check("1.1.0", platform_name="win32") is None

    assert "update_check.request_failed error_type=OSError" in caplog.text
    assert download_url not in caplog.text

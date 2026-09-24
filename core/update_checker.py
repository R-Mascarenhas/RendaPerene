"""Check public GitHub releases for a compatible application update."""

import json
import logging
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

LATEST_RELEASE_URL = "https://api.github.com/repos/R-Mascarenhas/RendaPerene/releases/latest"
REQUEST_TIMEOUT_SECONDS = 3.0
DOWNLOAD_URL_PREFIX = "https://github.com/R-Mascarenhas/RendaPerene/releases/download/"
logger = logging.getLogger(__name__)

ReleaseFetcher = Callable[[float], dict[str, Any]]


@dataclass(frozen=True)
class AvailableUpdate:
    """A newer release package that can be downloaded on this platform."""

    version: str
    release_notes: str
    download_url: str


class UpdateChecker:
    """Retrieve and validate the latest compatible public release."""

    def __init__(self, fetch_latest_release: ReleaseFetcher | None = None):
        self._fetch_latest_release = fetch_latest_release or self._request_latest_release

    def check(
        self,
        installed_version: str,
        platform_name: str | None = None,
        machine_name: str | None = None,
    ) -> AvailableUpdate | None:
        """Return a compatible update only when the release is newer than installed_version."""
        installed = _parse_version(installed_version)
        if installed is None:
            logger.warning("update_check.installed_version_invalid")
            return None

        try:
            release = self._fetch_latest_release(REQUEST_TIMEOUT_SECONDS)
        except (OSError, TimeoutError, UnicodeError, ValueError) as error:
            logger.warning("update_check.request_failed error_type=%s", type(error).__name__)
            return None
        if not isinstance(release, dict):
            logger.warning("update_check.response_invalid")
            return None

        release_version = _parse_version(release.get("tag_name"))
        if release_version is None:
            logger.warning("update_check.release_version_invalid")
            return None
        if release_version <= installed:
            return None

        version = _format_version(release_version)
        asset_name = _asset_name(
            version, platform_name or sys.platform, machine_name or platform.machine()
        )
        if asset_name is None:
            logger.info("update_check.platform_unsupported")
            return None

        asset_url = _find_asset_url(release.get("assets"), asset_name)
        if asset_url is None:
            logger.warning("update_check.asset_unavailable")
            return None

        release_notes = release.get("body")
        return AvailableUpdate(
            version=version,
            release_notes=release_notes if isinstance(release_notes, str) else "",
            download_url=asset_url,
        )

    @staticmethod
    def _request_latest_release(timeout: float) -> dict[str, Any]:
        request = Request(LATEST_RELEASE_URL, headers={"User-Agent": "RendaPerene-update-checker"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed GitHub API URL
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("Latest release response must be an object.")
        return payload


def _parse_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().removeprefix("v")
    parts = normalized.split(".")
    if len(parts) != 3 or any(
        not part.isdigit() or (len(part) > 1 and part.startswith("0")) for part in parts
    ):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def _format_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _asset_name(version: str, platform_name: str, machine_name: str) -> str | None:
    if machine_name.lower() not in {"amd64", "x86_64"}:
        return None
    if platform_name.startswith("win"):
        return f"RendaPerene-v{version}-windows-x64.zip"
    if platform_name.startswith("linux"):
        return f"RendaPerene-v{version}-ubuntu-x64.tar.gz"
    return None


def _find_asset_url(assets: object, expected_name: str) -> str | None:
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != expected_name:
            continue
        url = asset.get("browser_download_url")
        if isinstance(url, str) and url.startswith(DOWNLOAD_URL_PREFIX):
            return url
    return None

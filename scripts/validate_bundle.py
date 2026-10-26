"""Validate the portable resources shipped in a PyInstaller onedir bundle."""

import sys
from pathlib import Path


def validate_bundle(bundle: Path, expected_version: str) -> None:
    """Reject missing resources, version mismatches and personal/generated files."""
    resource_root = bundle / "_internal" if (bundle / "_internal").is_dir() else bundle
    required = (
        "app.py",
        "assets.csv",
        "version.txt",
        "core",
        "views",
        "services",
        "views/cloud_backup/oauth_popup.js",
    )
    missing = [item for item in required if not (resource_root / item).exists()]
    if missing:
        raise ValueError(f"Bundle is missing required resources: {', '.join(missing)}")
    actual_version = (resource_root / "version.txt").read_text(encoding="utf-8").strip()
    if actual_version != expected_version:
        raise ValueError("Bundle version does not match version.txt")
    forbidden_directories = tuple(
        path
        for root in {bundle, resource_root}
        for name in ("database", "catalog", "logs")
        if (path := root / name).exists()
    )
    forbidden = forbidden_directories
    allowed_catalog = resource_root / "assets.csv"
    forbidden += tuple(
        path
        for path in bundle.rglob("*")
        if path.is_file()
        and (
            path.suffix.casefold()
            in {".db", ".xlsx", ".ods", ".log", ".csv", ".rpb", ".rpbc", ".key"}
            or path.name in {"cloud-backup-state.json", ".installation-id"}
        )
        and path != allowed_catalog
    )
    if forbidden:
        raise ValueError("Personal or generated files found in bundle")


def main() -> int:
    try:
        validate_bundle(Path(sys.argv[1]), sys.argv[2])
    except ValueError as error:
        raise SystemExit(str(error)) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

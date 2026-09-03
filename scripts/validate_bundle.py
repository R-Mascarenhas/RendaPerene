"""Validate the portable resources shipped in a PyInstaller onedir bundle."""

import sys
from pathlib import Path


def main() -> int:
    bundle = Path(sys.argv[1])
    expected_version = sys.argv[2]
    resource_root = bundle / "_internal" if (bundle / "_internal").is_dir() else bundle
    required = ("app.py", "assets.csv", "version.txt", "core", "views", "services")
    missing = [item for item in required if not (resource_root / item).exists()]
    if missing:
        raise SystemExit(f"Bundle is missing required resources: {', '.join(missing)}")
    actual_version = (resource_root / "version.txt").read_text(encoding="utf-8").strip()
    if actual_version != expected_version:
        raise SystemExit("Bundle version does not match version.txt")
    forbidden_directories = tuple(
        path for name in ("database", "catalog", "logs") if (path := resource_root / name).exists()
    )
    forbidden = forbidden_directories + tuple(resource_root.rglob("*.db"))
    forbidden += tuple(resource_root.rglob("*.xlsx")) + tuple(resource_root.rglob("*.ods"))
    forbidden += tuple(resource_root.rglob("*.log"))
    if forbidden:
        raise SystemExit(f"Personal or generated files found in bundle: {forbidden}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

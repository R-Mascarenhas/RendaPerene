"""Validate the portable resources shipped in a PyInstaller onedir bundle."""

import sys
from pathlib import Path


def main() -> int:
    bundle = Path(sys.argv[1])
    expected_version = sys.argv[2]
    required = ("app.py", "assets.csv", "version.txt", "core", "views", "services")
    missing = [item for item in required if not (bundle / item).exists()]
    if missing:
        raise SystemExit(f"Bundle is missing required resources: {', '.join(missing)}")
    actual_version = (bundle / "version.txt").read_text(encoding="utf-8").strip()
    if actual_version != expected_version:
        raise SystemExit("Bundle version does not match version.txt")
    forbidden_directories = tuple(
        path for name in ("database", "catalog", "logs") if (path := bundle / name).exists()
    )
    forbidden = forbidden_directories + tuple(bundle.rglob("*.db"))
    forbidden += tuple(bundle.rglob("*.xlsx")) + tuple(bundle.rglob("*.ods"))
    forbidden += tuple(bundle.rglob("*.log"))
    if forbidden:
        raise SystemExit(f"Personal or generated files found in bundle: {forbidden}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

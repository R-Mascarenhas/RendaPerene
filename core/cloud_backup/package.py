"""Bounded ZIP packages for Drive-managed encryption, separate from encrypted RPB."""

import io
import json
import os
import re
import stat
import zipfile
import zlib
from pathlib import Path

from core.encrypted_backup_package import BackupPackageCorruptedError

MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
PACKAGE_KIND = "rendaperene-cloud-backup"
CLOUD_FORMAT_VERSION = 1
_PORTFOLIO_MEMBER = re.compile(
    r"carteiras/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"(?:backup\.sqlite3|metadata\.json)"
)


class CloudBackupPackageService:
    """Create and extract exactly one portfolio without trusting archive paths."""

    def create(self, directory: Path, machine_name: str) -> bytes:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if len(manifest["portfolios"]) != 1:
            raise ValueError("A cloud package must contain exactly one portfolio.")
        manifest.update(
            package_kind=PACKAGE_KIND,
            cloud_format_version=CLOUD_FORMAT_VERSION,
            machine_name=machine_name,
        )
        entry = manifest["portfolios"][0]
        manifest_content = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        metadata_size = (directory / entry["relative_path"] / "metadata.json").stat().st_size
        database_size = (directory / entry["relative_path"] / "backup.sqlite3").stat().st_size
        if (
            len(manifest_content) > MAX_METADATA_BYTES
            or metadata_size > MAX_METADATA_BYTES
            or len(manifest_content) + metadata_size + database_size > MAX_EXTRACTED_BYTES
        ):
            raise ValueError("The cloud backup exceeds the supported extracted size.")
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", manifest_content)
            for filename in ("metadata.json", "backup.sqlite3"):
                relative = f"{entry['relative_path']}/{filename}"
                archive.write(directory / relative, relative)
        content = result.getvalue()
        if len(content) > MAX_PACKAGE_BYTES:
            raise ValueError("The cloud backup exceeds the supported package size.")
        return content

    def extract(self, content: bytes, destination: Path) -> str:
        if not isinstance(content, bytes) or not content or len(content) > MAX_PACKAGE_BYTES:
            raise BackupPackageCorruptedError("Invalid cloud backup size.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                names = [member.filename for member in members]
                if (
                    len(members) != 3
                    or len(set(names)) != len(names)
                    or "manifest.json" not in names
                    or sum(member.file_size for member in members) > MAX_EXTRACTED_BYTES
                ):
                    raise BackupPackageCorruptedError("Invalid cloud backup members.")
                for member in members:
                    mode = member.external_attr >> 16
                    if (
                        (
                            member.filename != "manifest.json"
                            and not _PORTFOLIO_MEMBER.fullmatch(member.filename)
                        )
                        or stat.S_ISLNK(mode)
                        or member.is_dir()
                        or member.flag_bits & 1
                    ):
                        raise BackupPackageCorruptedError("Unsafe cloud backup member.")
                    if member.filename.endswith(".json") and member.file_size > MAX_METADATA_BYTES:
                        raise BackupPackageCorruptedError("Cloud metadata is too large.")
                manifest = json.loads(archive.read("manifest.json"))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("package_kind") != PACKAGE_KIND
                    or manifest.get("cloud_format_version") != CLOUD_FORMAT_VERSION
                    or manifest.get("encryption_state") != "unencrypted"
                    or manifest.get("portfolio_count") != 1
                    or len(manifest.get("portfolios", [])) != 1
                ):
                    raise BackupPackageCorruptedError("Invalid cloud backup format.")
                entry = manifest["portfolios"][0]
                expected = {
                    "manifest.json",
                    f"{entry['relative_path']}/metadata.json",
                    f"{entry['relative_path']}/backup.sqlite3",
                }
                if set(names) != expected:
                    raise BackupPackageCorruptedError("Cloud backup members do not match metadata.")
                destination.mkdir(parents=True, mode=0o700, exist_ok=False)
                for member in members:
                    target = destination / member.filename
                    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as output, archive.open(member) as source:
                        remaining = member.file_size
                        while block := source.read(min(1024 * 1024, remaining + 1)):
                            remaining -= len(block)
                            if remaining < 0:
                                raise BackupPackageCorruptedError("Invalid extracted size.")
                            output.write(block)
                        if remaining != 0:
                            raise BackupPackageCorruptedError("Incomplete cloud backup member.")
                return manifest["backup_id"]
        except BackupPackageCorruptedError:
            raise
        except (
            zipfile.BadZipFile,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            RuntimeError,
            NotImplementedError,
            zlib.error,
        ) as error:
            raise BackupPackageCorruptedError("Invalid cloud backup package.") from error

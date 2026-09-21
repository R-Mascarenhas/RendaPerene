import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

import core.encrypted_backup_package as package_module
from core.encrypted_backup_package import (
    BackupPackageCorruptedError,
    BackupPackageCredentialError,
    BackupPackageIncompatibleError,
    EncryptedBackupPackageService,
)


def _write_snapshot(source: Path) -> None:
    portfolio = source / "carteiras" / "f4b8d9bf-3295-4d80-93b1-846095d53c1f"
    portfolio.mkdir(parents=True)
    (source / "manifest.json").write_text('{"portfolio_count": 1}\n', encoding="utf-8")
    (portfolio / "metadata.json").write_text('{"schema_version": 7}\n', encoding="utf-8")
    (portfolio / "backup.sqlite3").write_bytes(b"SQLite format 3\x00private portfolio data")


@pytest.fixture(autouse=True)
def fast_password_derivation(monkeypatch):
    monkeypatch.setattr(package_module, "ARGON2_MEMORY_COST_KIB", 8)
    monkeypatch.setattr(package_module, "ARGON2_ITERATIONS", 1)
    monkeypatch.setattr(package_module, "ARGON2_LANES", 1)


def test_package_round_trips_snapshot_with_password_without_exposing_sqlite(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    package_file = tmp_path / "backup.rpb"
    destination = tmp_path / "opened"
    password = "senha"
    packages = EncryptedBackupPackageService()

    packages.create(source, package_file, password)
    packages.extract_with_password(package_file, destination, password)

    assert package_file.read_bytes().startswith(b"RendaPerene Backup")
    assert b"SQLite format 3\x00" not in package_file.read_bytes()
    assert b"private portfolio data" not in package_file.read_bytes()
    assert (destination / "manifest.json").read_text(encoding="utf-8") == '{"portfolio_count": 1}\n'
    assert (
        destination / "carteiras" / "f4b8d9bf-3295-4d80-93b1-846095d53c1f" / "backup.sqlite3"
    ).read_bytes() == (b"SQLite format 3\x00private portfolio data")


def test_package_round_trips_snapshot_with_separate_recovery_key_file(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    package_file = tmp_path / "backup.rpb"
    destination = tmp_path / "opened"
    packages = EncryptedBackupPackageService()

    result = packages.create(source, package_file, "senha")
    packages.extract_with_recovery_key_file(
        package_file,
        destination,
        result.recovery_key_file_content,
    )

    assert result.recovery_key_file_name.endswith(".key")
    assert b"senha" not in result.recovery_key_file_content
    assert (destination / "manifest.json").exists()


def test_wrong_password_does_not_publish_a_partial_snapshot(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    package_file = tmp_path / "backup.rpb"
    destination = tmp_path / "opened"
    packages = EncryptedBackupPackageService()
    packages.create(source, package_file, "senha correta")

    with pytest.raises(BackupPackageCredentialError):
        packages.extract_with_password(package_file, destination, "senha errada")

    assert not destination.exists()
    assert not list(tmp_path.glob(".opened.*.tmp"))


def test_corrupted_authenticated_payload_does_not_publish_a_partial_snapshot(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    package_file = tmp_path / "backup.rpb"
    destination = tmp_path / "opened"
    packages = EncryptedBackupPackageService()
    packages.create(source, package_file, "senha correta")
    package_file.write_bytes(package_file.read_bytes()[:-1] + b"\x00")

    with pytest.raises(BackupPackageCorruptedError):
        packages.extract_with_password(package_file, destination, "senha correta")

    assert not destination.exists()
    assert not list(tmp_path.glob(".opened.*.tmp"))


@pytest.mark.skipif(
    os.name == "nt", reason="O nome de arquivo com barra invertida é específico do POSIX."
)
def test_package_rejects_windows_native_parent_traversal_member(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    (source / "..\\outside.db").write_bytes(b"untrusted")
    package_file = tmp_path / "backup.rpb"
    destination = tmp_path / "opened"
    packages = EncryptedBackupPackageService()
    packages.create(source, package_file, "senha")

    with pytest.raises(BackupPackageCorruptedError):
        packages.extract_with_password(package_file, destination, "senha")

    assert not destination.exists()


def test_package_with_unknown_format_version_is_rejected_before_decryption(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    package_file = tmp_path / "backup.rpb"
    packages = EncryptedBackupPackageService()
    packages.create(source, package_file, "senha correta")

    package_bytes = package_file.read_bytes()
    header_size = int.from_bytes(package_bytes[19:23], "big")
    header = json.loads(package_bytes[23 : 23 + header_size])
    header.pop("header_checksum")
    header["format_version"] = 2
    header["header_checksum"] = hashlib.sha256(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    replacement = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert len(replacement) == header_size
    package_file.write_bytes(package_bytes[:23] + replacement + package_bytes[23 + header_size :])

    with pytest.raises(BackupPackageIncompatibleError):
        packages.extract_with_password(package_file, tmp_path / "opened", "senha correta")


@pytest.mark.skipif(os.name != "posix", reason="Permissões POSIX não se aplicam ao Windows.")
def test_extracted_snapshot_uses_owner_only_permissions(tmp_path):
    source = tmp_path / "snapshot"
    _write_snapshot(source)
    package_file = tmp_path / "backup.rpb"
    destination = tmp_path / "opened"
    packages = EncryptedBackupPackageService()
    packages.create(source, package_file, "senha")

    packages.extract_with_password(package_file, destination, "senha")

    database = destination / "carteiras" / "f4b8d9bf-3295-4d80-93b1-846095d53c1f" / "backup.sqlite3"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600

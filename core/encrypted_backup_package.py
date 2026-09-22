"""Versioned authenticated encryption for portable RendaPerene backup packages."""

import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PACKAGE_MAGIC = b"RendaPerene Backup\x00"
PACKAGE_FORMAT_VERSION = 1
PACKAGE_HEADER_MAXIMUM_BYTES = 64 * 1024
GCM_NONCE_BYTES = 12
DATA_KEY_BYTES = 32
RECOVERY_KEY_BYTES = 32
ARGON2_SALT_BYTES = 16
ARGON2_MEMORY_COST_KIB = 64 * 1024
ARGON2_ITERATIONS = 3
ARGON2_LANES = 4
STREAM_CHUNK_BYTES = 1024 * 1024
OWNER_ONLY_DIRECTORY_MODE = 0o700
OWNER_ONLY_FILE_MODE = 0o600


class BackupPackageError(RuntimeError):
    """Base error raised while creating or opening a backup package."""


class BackupPackageCredentialError(BackupPackageError):
    """The supplied password or recovery key does not open the package."""


class BackupPackageCorruptedError(BackupPackageError):
    """The package is malformed, truncated, or fails authentication."""


class BackupPackageIncompatibleError(BackupPackageError):
    """The package uses a format version or algorithm not supported by this app."""


@dataclass(frozen=True)
class EncryptedBackupPackageResult:
    """The encrypted package and the recovery key file offered to the user."""

    package_file: Path
    recovery_key_file_name: str
    recovery_key_file_content: bytes


@dataclass(frozen=True)
class OpenedBackupPackage:
    """Authenticated identity of a completely extracted backup package."""

    backup_id: str


class _EncryptingWriter(io.RawIOBase):
    def __init__(self, destination, encryptor):
        self._destination = destination
        self._encryptor = encryptor

    def writable(self):
        return True

    def write(self, data):
        if not data:
            return 0
        self._destination.write(self._encryptor.update(data))
        return len(data)


class _DecryptingReader(io.RawIOBase):
    def __init__(self, source, encrypted_size, decryptor):
        self._source = source
        self._remaining = encrypted_size
        self._decryptor = decryptor
        self._buffer = bytearray()
        self._authenticated = False

    def readable(self):
        return True

    def readinto(self, target):
        while not self._buffer and not self._authenticated:
            if self._remaining:
                encrypted = self._source.read(min(STREAM_CHUNK_BYTES, self._remaining))
                if not encrypted:
                    raise BackupPackageCorruptedError("The package payload is truncated.")
                self._remaining -= len(encrypted)
                self._buffer.extend(self._decryptor.update(encrypted))
            else:
                try:
                    self._buffer.extend(self._decryptor.finalize())
                except InvalidTag as error:
                    raise BackupPackageCorruptedError(
                        "The package authentication tag is invalid."
                    ) from error
                self._authenticated = True
        size = min(len(target), len(self._buffer))
        target[:size] = self._buffer[:size]
        del self._buffer[:size]
        return size

    def drain_and_verify(self):
        buffer = bytearray(STREAM_CHUNK_BYTES)
        while self.readinto(buffer):
            pass


class EncryptedBackupPackageService:
    """Create and open RPB v1 packages without persisting credential material."""

    def create(
        self,
        source_directory: Path,
        package_file: Path,
        password: str,
        *,
        backup_id: str | None = None,
    ) -> EncryptedBackupPackageResult:
        """Encrypt a complete staging directory and atomically publish the package."""
        password_bytes = self._validated_password(password)
        if not source_directory.is_dir():
            raise ValueError("The backup source directory must exist.")
        package_file.parent.mkdir(parents=True, exist_ok=True)
        backup_id = str(uuid.UUID(backup_id)) if backup_id is not None else str(uuid.uuid4())
        data_key = os.urandom(DATA_KEY_BYTES)
        recovery_key = os.urandom(RECOVERY_KEY_BYTES)
        header = self._create_header(backup_id, data_key, password_bytes, recovery_key)
        header_bytes = self._serialize_header(header)
        temporary_file = package_file.with_name(f".{package_file.name}.{uuid.uuid4().hex}.tmp")

        try:
            with self._open_owner_only_file(temporary_file) as destination:
                destination.write(PACKAGE_MAGIC)
                destination.write(len(header_bytes).to_bytes(4, "big"))
                destination.write(header_bytes)
                encryptor = Cipher(
                    algorithms.AES(data_key), modes.GCM(self._decode(header["data_nonce"]))
                ).encryptor()
                encryptor.authenticate_additional_data(header_bytes)
                with tarfile.open(
                    fileobj=_EncryptingWriter(destination, encryptor),
                    mode="w|",
                    format=tarfile.PAX_FORMAT,
                ) as archive:
                    for source_file in self._source_files(source_directory):
                        archive.add(
                            source_file,
                            arcname=source_file.relative_to(source_directory).as_posix(),
                        )
                destination.write(encryptor.finalize())
                destination.write(encryptor.tag)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary_file, package_file)
        finally:
            if temporary_file.exists():
                temporary_file.unlink()

        return EncryptedBackupPackageResult(
            package_file=package_file,
            recovery_key_file_name=package_file.with_suffix(".key").name,
            recovery_key_file_content=self._serialize_recovery_key(backup_id, recovery_key),
        )

    def extract_with_password(
        self, package_file: Path, destination: Path, password: str
    ) -> OpenedBackupPackage:
        """Open one package using its password without publishing partial contents."""
        password_bytes = self._validated_password(password)
        header, payload_offset, encrypted_size, tag = self._read_header(package_file)
        password_key = self._derive_password_key(
            password_bytes, self._decode(header["password"]["salt"])
        )
        data_key = self._unwrap_data_key(password_key, header, "password")
        self._extract(
            package_file, destination, header, payload_offset, encrypted_size, tag, data_key
        )
        return OpenedBackupPackage(backup_id=header["backup_id"])

    def extract_with_recovery_key_file(
        self,
        package_file: Path,
        destination: Path,
        recovery_key_file_content: bytes,
    ) -> OpenedBackupPackage:
        """Open one package using a separately stored recovery key file."""
        backup_id, recovery_key = self._parse_recovery_key(recovery_key_file_content)
        header, payload_offset, encrypted_size, tag = self._read_header(package_file)
        if not hmac.compare_digest(backup_id, header["backup_id"]):
            raise BackupPackageCredentialError("The recovery key does not belong to this package.")
        recovery_key_encryption_key = self._derive_recovery_key(
            recovery_key,
            self._decode(header["recovery"]["salt"]),
        )
        data_key = self._unwrap_data_key(recovery_key_encryption_key, header, "recovery")
        self._extract(
            package_file,
            destination,
            header,
            payload_offset,
            encrypted_size,
            tag,
            data_key,
        )
        return OpenedBackupPackage(backup_id=header["backup_id"])

    @staticmethod
    def _validated_password(password: str) -> bytes:
        if not isinstance(password, str) or len(password) < 4:
            raise ValueError("The backup password must contain at least four characters.")
        return password.encode("utf-8")

    @staticmethod
    def _source_files(source_directory: Path) -> list[Path]:
        files = []
        for candidate in source_directory.rglob("*"):
            if candidate.is_symlink() or not candidate.is_file():
                if candidate.is_symlink():
                    raise ValueError("The backup source must not contain symbolic links.")
                continue
            files.append(candidate)
        return sorted(files)

    def _create_header(
        self,
        backup_id: str,
        data_key: bytes,
        password: bytes,
        recovery_key: bytes,
    ) -> dict:
        password_salt = os.urandom(ARGON2_SALT_BYTES)
        password_key = self._derive_password_key(password, password_salt)
        recovery_salt = os.urandom(ARGON2_SALT_BYTES)
        recovery_key_encryption_key = self._derive_recovery_key(recovery_key, recovery_salt)
        return {
            "format_version": PACKAGE_FORMAT_VERSION,
            "backup_id": backup_id,
            "cipher": "AES-256-GCM",
            "data_nonce": self._encode(os.urandom(GCM_NONCE_BYTES)),
            "password": self._credential_slot(
                password_key, data_key, backup_id, "password", password_salt
            ),
            "recovery": self._credential_slot(
                recovery_key_encryption_key,
                data_key,
                backup_id,
                "recovery",
                recovery_salt,
            ),
        }

    def _credential_slot(
        self,
        key_encryption_key: bytes,
        data_key: bytes,
        backup_id: str,
        slot_name: str,
        salt: bytes,
    ) -> dict:
        nonce = os.urandom(GCM_NONCE_BYTES)
        aad = self._slot_aad(backup_id, slot_name)
        return {
            "salt": self._encode(salt),
            "nonce": self._encode(nonce),
            "wrapped_key": self._encode(AESGCM(key_encryption_key).encrypt(nonce, data_key, aad)),
            "verifier": self._encode(hmac.new(key_encryption_key, aad, hashlib.sha256).digest()),
        }

    @staticmethod
    def _derive_password_key(password: bytes, salt: bytes) -> bytes:
        return Argon2id(
            salt=salt,
            length=DATA_KEY_BYTES,
            iterations=ARGON2_ITERATIONS,
            lanes=ARGON2_LANES,
            memory_cost=ARGON2_MEMORY_COST_KIB,
        ).derive(password)

    @staticmethod
    def _derive_recovery_key(recovery_key: bytes, salt: bytes) -> bytes:
        return HKDF(
            algorithm=SHA256(),
            length=DATA_KEY_BYTES,
            salt=salt,
            info=b"RendaPerene RPB v1 recovery wrapping key",
        ).derive(recovery_key)

    @staticmethod
    def _slot_aad(backup_id: str, slot_name: str) -> bytes:
        return f"RendaPerene RPB v1/{backup_id}/{slot_name}".encode("ascii")

    @classmethod
    def _serialize_header(cls, header: dict) -> bytes:
        protected_header = dict(header)
        header_without_checksum = cls._canonical_json(protected_header)
        protected_header["header_checksum"] = hashlib.sha256(header_without_checksum).hexdigest()
        return cls._canonical_json(protected_header)

    @staticmethod
    def _canonical_json(payload: dict) -> bytes:
        return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        if not isinstance(value, str):
            raise BackupPackageCorruptedError("The package header is malformed.")
        try:
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except ValueError as error:
            raise BackupPackageCorruptedError("The package header is malformed.") from error

    def _read_header(self, package_file: Path) -> tuple[dict, int, int, bytes]:
        try:
            package_size = package_file.stat().st_size
            with package_file.open("rb") as source:
                if source.read(len(PACKAGE_MAGIC)) != PACKAGE_MAGIC:
                    raise BackupPackageCorruptedError("The package signature is invalid.")
                header_size = int.from_bytes(source.read(4), "big")
                if not 2 <= header_size <= PACKAGE_HEADER_MAXIMUM_BYTES:
                    raise BackupPackageCorruptedError("The package header size is invalid.")
                header_bytes = source.read(header_size)
                if len(header_bytes) != header_size:
                    raise BackupPackageCorruptedError("The package header is truncated.")
                header = json.loads(header_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupPackageCorruptedError("The package header cannot be read.") from error
        self._validate_header(header)
        payload_offset = len(PACKAGE_MAGIC) + 4 + header_size
        encrypted_size = package_size - payload_offset - 16
        if encrypted_size < 0:
            raise BackupPackageCorruptedError("The package payload is truncated.")
        with package_file.open("rb") as source:
            source.seek(package_size - 16)
            tag = source.read(16)
        return header, payload_offset, encrypted_size, tag

    def _validate_header(self, header: object) -> None:
        if not isinstance(header, dict):
            raise BackupPackageCorruptedError("The package header is malformed.")
        checksum = header.get("header_checksum")
        protected_header = dict(header)
        protected_header.pop("header_checksum", None)
        if not isinstance(checksum, str) or not hmac.compare_digest(
            checksum,
            hashlib.sha256(self._canonical_json(protected_header)).hexdigest(),
        ):
            raise BackupPackageCorruptedError("The package header integrity check failed.")
        if header.get("format_version") != PACKAGE_FORMAT_VERSION:
            raise BackupPackageIncompatibleError("The package format version is not supported.")
        if header.get("cipher") != "AES-256-GCM":
            raise BackupPackageIncompatibleError(
                "The package encryption algorithm is not supported."
            )
        try:
            uuid.UUID(header["backup_id"])
            if len(self._decode(header["data_nonce"])) != GCM_NONCE_BYTES:
                raise ValueError
            for slot_name in ("password", "recovery"):
                slot = header[slot_name]
                if not isinstance(slot, dict):
                    raise ValueError
                if len(self._decode(slot["salt"])) != ARGON2_SALT_BYTES:
                    raise ValueError
                if len(self._decode(slot["nonce"])) != GCM_NONCE_BYTES:
                    raise ValueError
                if len(self._decode(slot["wrapped_key"])) != DATA_KEY_BYTES + 16:
                    raise ValueError
                if len(self._decode(slot["verifier"])) != hashlib.sha256().digest_size:
                    raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise BackupPackageCorruptedError("The package header is malformed.") from error

    def _unwrap_data_key(self, key_encryption_key: bytes, header: dict, slot_name: str) -> bytes:
        slot = header[slot_name]
        aad = self._slot_aad(header["backup_id"], slot_name)
        expected_verifier = hmac.new(key_encryption_key, aad, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_verifier, self._decode(slot["verifier"])):
            raise BackupPackageCredentialError(
                "The supplied credential does not open this package."
            )
        try:
            return AESGCM(key_encryption_key).decrypt(
                self._decode(slot["nonce"]),
                self._decode(slot["wrapped_key"]),
                aad,
            )
        except InvalidTag as error:
            raise BackupPackageCorruptedError("The wrapped package key is invalid.") from error

    def _extract(  # noqa: PLR0913
        self,
        package_file: Path,
        destination: Path,
        header: dict,
        payload_offset: int,
        encrypted_size: int,
        tag: bytes,
        data_key: bytes,
    ) -> None:
        if destination.exists():
            raise ValueError("The package extraction destination already exists.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            self._create_owner_only_directory(staging)
            with package_file.open("rb") as source:
                source.seek(payload_offset)
                decryptor = Cipher(
                    algorithms.AES(data_key),
                    modes.GCM(self._decode(header["data_nonce"]), tag),
                ).decryptor()
                decryptor.authenticate_additional_data(self._serialize_header_from_read(header))
                reader = _DecryptingReader(source, encrypted_size, decryptor)
                self._extract_archive(reader, staging)
                reader.drain_and_verify()
            os.replace(staging, destination)
        except (OSError, tarfile.TarError, BackupPackageError) as error:
            if isinstance(error, BackupPackageError):
                raise
            raise BackupPackageCorruptedError(
                "The encrypted package contents are invalid."
            ) from error
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    @staticmethod
    def _serialize_header_from_read(header: dict) -> bytes:
        return EncryptedBackupPackageService._canonical_json(header)

    def _extract_archive(self, reader: _DecryptingReader, staging: Path) -> None:
        extracted_files = set()
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                relative_path = self._validated_archive_path(member.name)
                if not member.isfile() or relative_path in extracted_files:
                    raise BackupPackageCorruptedError(
                        "The package archive contains an invalid entry."
                    )
                extracted_files.add(relative_path)
                source = archive.extractfile(member)
                if source is None:
                    raise BackupPackageCorruptedError("The package archive cannot be read.")
                destination = staging / relative_path
                self._create_owner_only_directory(destination.parent)
                with self._open_owner_only_file(destination) as output:
                    shutil.copyfileobj(source, output, length=STREAM_CHUNK_BYTES)
        if Path("manifest.json") not in extracted_files:
            raise BackupPackageCorruptedError("The package archive has no manifest.")

    @staticmethod
    def _validated_archive_path(member_name: str) -> Path:
        path = PurePosixPath(member_name)
        windows_path = PureWindowsPath(member_name)
        if (
            path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in path.parts
            or ".." in windows_path.parts
            or "\\" in member_name
            or not path.parts
        ):
            raise BackupPackageCorruptedError("The package archive path is invalid.")
        return Path(*path.parts)

    @staticmethod
    def _create_owner_only_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIRECTORY_MODE)
        if os.name == "posix":
            path.chmod(OWNER_ONLY_DIRECTORY_MODE)

    @staticmethod
    def _open_owner_only_file(path: Path):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_ONLY_FILE_MODE)
        return os.fdopen(descriptor, "wb")

    def _serialize_recovery_key(self, backup_id: str, recovery_key: bytes) -> bytes:
        return (
            self._canonical_json(
                {
                    "backup_id": backup_id,
                    "format_version": 1,
                    "recovery_key": self._encode(recovery_key),
                }
            )
            + b"\n"
        )

    def _parse_recovery_key(self, content: bytes) -> tuple[str, bytes]:
        try:
            payload = json.loads(content.decode("utf-8"))
            backup_id = payload["backup_id"]
            if payload["format_version"] != 1:
                raise ValueError
            uuid.UUID(backup_id)
            recovery_key = self._decode(payload["recovery_key"])
            if len(recovery_key) != RECOVERY_KEY_BYTES:
                raise ValueError
            return backup_id, recovery_key
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupPackageCredentialError("The recovery key file is invalid.") from error

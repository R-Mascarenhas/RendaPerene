"""Discardable, bounded local cache for market inputs and prepared screen data."""

import datetime as dt
import hashlib
import io
import json
import logging
import math
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
_SCHEMA_VERSION = 1
_MAX_ENTRY_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_ENTRIES = 2048


@dataclass(frozen=True)
class CacheHit:
    value: Any
    stale: bool
    age_seconds: float
    remaining_seconds: float
    updated_at: dt.datetime


def _pack(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _pack(value.item())
    if value is pd.NaT or value is pd.NA:
        return {"t": "null"}
    if isinstance(value, dt.datetime):
        return {"t": "datetime", "v": value.isoformat()}
    if isinstance(value, dt.date):
        return {"t": "date", "v": value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {"t": "float", "v": str(value)}
    if isinstance(value, dict):
        return {"t": "dict", "v": [[_pack(k), _pack(v)] for k, v in value.items()]}
    if isinstance(value, (list, tuple)):
        return {"t": "list", "v": [_pack(item) for item in value]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Unsupported cache value")


def _unpack(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    kind = value["t"]
    if kind == "null":
        return None
    if kind == "datetime":
        return dt.datetime.fromisoformat(value["v"])
    if kind == "date":
        return dt.date.fromisoformat(value["v"])
    if kind == "float":
        return float(value["v"])
    if kind == "dict":
        return {_unpack(key): _unpack(item) for key, item in value["v"]}
    if kind == "list":
        return [_unpack(item) for item in value["v"]]
    raise ValueError("Unsupported cache value")


def _encode(value: Any) -> str:
    if isinstance(value, pd.DataFrame):
        return json.dumps(
            {
                "kind": "dataframe",
                "data": value.to_json(orient="table", date_format="iso", double_precision=15),
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    return json.dumps({"kind": "json", "data": _pack(value)}, ensure_ascii=False, allow_nan=False)


def _decode(payload: str) -> Any:
    envelope = json.loads(payload)
    if envelope["kind"] == "dataframe":
        return pd.read_json(io.StringIO(envelope["data"]), orient="table")
    if envelope["kind"] == "json":
        return _unpack(envelope["data"])
    raise ValueError("Unsupported cache value")


class ScreenCache:
    """Small fail-open interface over a separate SQLite file, never a portfolio DB."""

    def __init__(self, path: Path, *, clock=None):
        self.path = Path(path)
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    @staticmethod
    def _key(namespace: str, key: tuple) -> str:
        raw = json.dumps([namespace, key], ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _connect(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=0.05)
        try:
            conn.execute("PRAGMA busy_timeout=50")
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            conn.execute(f"PRAGMA max_page_count={160 * 1024 * 1024 // page_size}")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, _SCHEMA_VERSION):
                raise ValueError("Unsupported cache schema")
            if version == 0:
                conn.execute("BEGIN IMMEDIATE")
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, _SCHEMA_VERSION):
                    raise ValueError("Unsupported cache schema")
                if version == 0:
                    existing = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                    if existing:
                        raise ValueError("Unrecognized SQLite file at cache path")
                    conn.execute(
                        """CREATE TABLE IF NOT EXISTS entries (
                            key TEXT PRIMARY KEY,
                            payload TEXT NOT NULL,
                            checksum TEXT NOT NULL,
                            updated_at REAL NOT NULL,
                            expires_at REAL NOT NULL,
                            size INTEGER NOT NULL
                        )"""
                    )
                    conn.execute("CREATE INDEX IF NOT EXISTS entries_age ON entries(updated_at)")
                    conn.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                conn.commit()
            if os.name == "posix":
                os.chmod(self.path, 0o600)
            return conn
        except Exception:
            conn.close()
            raise

    def get(self, namespace: str, key: tuple) -> CacheHit | None:
        try:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT payload, checksum, updated_at, expires_at FROM entries WHERE key = ?",
                    (self._key(namespace, key),),
                ).fetchone()
            if row is None:
                return None
            payload, checksum, updated, expires = row
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != checksum:
                return None
            now = self._clock().timestamp()
            return CacheHit(
                value=_decode(payload),
                stale=now >= expires,
                age_seconds=max(0.0, now - updated),
                remaining_seconds=max(0.0, expires - now),
                updated_at=dt.datetime.fromtimestamp(updated, dt.timezone.utc),
            )
        except Exception as error:  # Cache failures must never prevent reading the portfolio.
            logger.warning("screen_cache.read_failed error_type=%s", type(error).__name__)
            return None

    def put(self, namespace: str, key: tuple, value: Any, *, ttl: float) -> bool:
        try:
            payload = _encode(value)
            size = len(payload.encode("utf-8"))
            if size > _MAX_ENTRY_BYTES or ttl <= 0:
                return False
            now = self._clock().timestamp()
            with closing(self._connect()) as conn, conn:
                conn.execute(
                    """INSERT INTO entries(key, payload, checksum, updated_at, expires_at, size)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,
                        checksum=excluded.checksum, updated_at=excluded.updated_at,
                        expires_at=excluded.expires_at, size=excluded.size""",
                    (
                        self._key(namespace, key),
                        payload,
                        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                        now,
                        now + ttl,
                        size,
                    ),
                )
                count, total = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM entries"
                ).fetchone()
                if total > _MAX_TOTAL_BYTES or count > _MAX_ENTRIES:
                    conn.execute(
                        """DELETE FROM entries WHERE key IN
                        (SELECT key FROM entries ORDER BY updated_at ASC LIMIT
                         (SELECT COUNT(*) FROM entries) / 4 + 1)"""
                    )
            return True
        except Exception as error:  # Cache failures must never prevent reading the portfolio.
            logger.warning("screen_cache.write_failed error_type=%s", type(error).__name__)
            return False

    def expire_many(self, namespace: str, keys: list[tuple]) -> None:
        """Keep last values but require fresh remote requests next time."""
        try:
            with closing(self._connect()) as conn, conn:
                conn.executemany(
                    "UPDATE entries SET expires_at = 0 WHERE key = ?",
                    [(self._key(namespace, key),) for key in keys],
                )
        except Exception as error:  # Cache failures must never prevent reading the portfolio.
            logger.warning("screen_cache.expire_failed error_type=%s", type(error).__name__)

"""Atomic non-secret preferences and successful backup fingerprints."""

import json
import math
import os
import uuid
from contextlib import contextmanager

from core.application_paths import ApplicationPaths
from core.cloud_backup.models import CloudBackupError


class CloudBackupStateStore:
    def __init__(self, paths: ApplicationPaths):
        self._paths = paths

    def load(self) -> dict:
        try:
            content = json.loads(self._paths.cloud_backup_state_file.read_text(encoding="utf-8"))
            if not isinstance(content, dict) or content.get("format_version") != 1:
                raise ValueError("Invalid cloud preference format.")
            accounts = content.get("accounts")
            if not isinstance(content.get("credential_removal_pending", False), bool):
                raise ValueError("Invalid credential removal state.")
            if not isinstance(accounts, dict):
                raise ValueError("Invalid cloud accounts.")
            for account, preferences in accounts.items():
                if not isinstance(account, str) or not isinstance(preferences, dict):
                    raise ValueError("Invalid cloud account preferences.")
                selected = preferences.get("selected")
                sent = preferences.get("sent")
                selected_ids = preferences.get("selected_ids", {})
                last_check = preferences.get("last_check", 0)
                if (
                    not isinstance(preferences.get("enabled"), bool)
                    or not isinstance(preferences.get("discovery_complete", False), bool)
                    or not isinstance(preferences.get("machine_name"), str)
                    or not isinstance(selected, list)
                    or any(not isinstance(name, str) for name in selected)
                    or not isinstance(sent, dict)
                    or any(not isinstance(value, str) for value in sent.values())
                    or not isinstance(selected_ids, dict)
                    or any(
                        not isinstance(name, str) or not isinstance(identity, str)
                        for name, identity in selected_ids.items()
                    )
                    or not isinstance(last_check, (int, float))
                    or not math.isfinite(last_check)
                ):
                    raise ValueError("Invalid cloud preferences.")
            return content
        except FileNotFoundError:
            return {"format_version": 1, "accounts": {}}
        except (OSError, UnicodeError, ValueError) as error:
            raise CloudBackupError(
                "Não foi possível ler as preferências do backup automático."
            ) from error

    @contextmanager
    def transaction(self):
        try:
            with self._paths.cloud_backup_lock():
                state = self.load()
                yield state
                self._save(state)
        except (OSError, TimeoutError, ValueError) as error:
            raise CloudBackupError(
                "Não foi possível salvar as preferências do backup automático."
            ) from error

    def _save(self, state: dict) -> None:
        destination = self._paths.cloud_backup_state_file
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(state, output, ensure_ascii=False, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

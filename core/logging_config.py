import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

_HANDLER_MARKER = "_rendaperene_logging_handler"
_LOG_FORMAT = "%(asctime)s | %(levelname)s\t| %(name)s\t| %(message)s"
_APPLICATION_LOGGER_NAMES = ("__main__", "app", "run_app", "core", "services", "views")
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
OWNER_ONLY_DIRECTORY_MODE = 0o700
OWNER_ONLY_FILE_MODE = 0o600
_CONFIGURATION_LOCK = threading.Lock()


class _ApplicationLogFilter(logging.Filter):
    """Keep dependency internals out of application-owned log destinations."""

    def filter(self, record: logging.LogRecord) -> bool:
        return any(
            record.name == logger_name or record.name.startswith(f"{logger_name}.")
            for logger_name in _APPLICATION_LOGGER_NAMES
        )


class _OwnerOnlyRotatingFileHandler(RotatingFileHandler):
    """Restrict application logs to their owner on POSIX systems."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self._restrict_existing_log_files()
        except OSError:
            self.close()
            raise

    def _open(self):
        stream = super()._open()
        if os.name == "posix":
            try:
                os.chmod(self.baseFilename, OWNER_ONLY_FILE_MODE)
            except OSError:
                stream.close()
                raise
        return stream

    def doRollover(self) -> None:
        super().doRollover()
        self._restrict_existing_log_files()

    def _restrict_existing_log_files(self) -> None:
        if os.name != "posix":
            return
        for index in range(self.backupCount + 1):
            suffix = "" if index == 0 else f".{index}"
            log_path = Path(f"{self.baseFilename}{suffix}")
            if log_path.exists():
                log_path.chmod(OWNER_ONLY_FILE_MODE)


def configure_logging(logs_dir: Path) -> None:
    """Configure application logging from environment variables."""
    with _CONFIGURATION_LOCK:
        _replace_application_handlers(logs_dir)


def _replace_application_handlers(logs_dir: Path) -> None:
    """Replace handlers installed by this module while holding the configuration lock."""
    level = (
        logging.DEBUG
        if os.environ.get("APP_ENV", "prod").strip().casefold() == "dev"
        else logging.INFO
    )
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        if getattr(handler, _HANDLER_MARKER, False):
            root_logger.removeHandler(handler)
            handler.close()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    stdout_handler.addFilter(_ApplicationLogFilter())
    setattr(stdout_handler, _HANDLER_MARKER, True)
    root_logger.addHandler(stdout_handler)
    root_logger.setLevel(level)

    if os.environ.get("LOG_TO_FILE", "false").strip().casefold() == "true":
        try:
            logs_dir.mkdir(parents=True, exist_ok=True, mode=OWNER_ONLY_DIRECTORY_MODE)
            if os.name == "posix":
                logs_dir.chmod(OWNER_ONLY_DIRECTORY_MODE)
            file_handler = _OwnerOnlyRotatingFileHandler(
                logs_dir / "rendaperene.log",
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError:
            logging.getLogger(__name__).warning(
                "File logging could not be enabled; continuing with stdout only."
            )
        else:
            file_handler.setLevel(level)
            file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
            file_handler.addFilter(_ApplicationLogFilter())
            setattr(file_handler, _HANDLER_MARKER, True)
            root_logger.addHandler(file_handler)

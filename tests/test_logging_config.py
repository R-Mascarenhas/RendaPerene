import logging
import os
import stat

import pytest

import core.logging_config as logging_config
from core.logging_config import configure_logging


@pytest.fixture(autouse=True)
def restore_root_logging():
    root_logger = logging.getLogger()
    original_level = root_logger.level
    original_handlers = root_logger.handlers[:]
    yield
    for logger in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(logger, logging.Logger) and logging_config._is_server_logger(logger.name):
            for handler in logger.handlers[:]:
                if (
                    getattr(handler, logging_config._HANDLER_MARKER, False)
                    and handler not in original_handlers
                ):
                    logger.removeHandler(handler)
    for handler in root_logger.handlers[:]:
        if handler not in original_handlers:
            root_logger.removeHandler(handler)
            handler.close()
    root_logger.handlers[:] = original_handlers
    root_logger.setLevel(original_level)


@pytest.mark.parametrize("file_setting", [None, "false", "yes"])
def test_defaults_to_warning_file_logging(monkeypatch, tmp_path, capsys, file_setting):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_TO_FILE", raising=False)
    if file_setting is not None:
        monkeypatch.setenv("LOG_TO_FILE", file_setting)

    configure_logging(tmp_path / "logs")
    logger = logging.getLogger("core.example")
    logger.debug("debug hidden")
    logger.info("startup complete")
    logger.warning("connection interrupted")
    logger.error("server failed")
    logger.critical("fatal failure")

    captured = capsys.readouterr()
    assert "startup complete" in captured.out
    assert "debug hidden" not in captured.out
    log_contents = (tmp_path / "logs" / "rendaperene.log").read_text(encoding="utf-8")
    assert "startup complete" not in log_contents
    assert "debug hidden" not in log_contents
    assert "connection interrupted" in log_contents
    assert "server failed" in log_contents
    assert "fatal failure" in log_contents


def test_unknown_environment_values_use_safe_defaults(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("LOG_TO_FILE", "yes")

    configure_logging(tmp_path / "logs")
    logger = logging.getLogger("core.example")
    logger.debug("debug hidden")
    logger.info("safe defaults active")

    captured = capsys.readouterr()
    assert "safe defaults active" in captured.out
    assert "debug hidden" not in captured.out
    assert (tmp_path / "logs" / "rendaperene.log").exists()


@pytest.mark.parametrize("environment", ["prod", "dev"])
def test_session_lifecycle_is_persisted_without_verbose_file_logging(
    monkeypatch, tmp_path, environment
):
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("LOG_TO_FILE", "false")
    configure_logging(tmp_path)

    logging.getLogger("core.utils.session").info("ordinary session information")
    lifecycle_logger = logging.getLogger("core.utils.session.lifecycle")
    lifecycle_logger.debug("verbose lifecycle details")
    lifecycle_logger.info("session.reconnection_grace_started grace_seconds=%s", 120)
    lifecycle_logger.info("session.connection_restored")
    lifecycle_logger.info("application.no_active_sessions")

    log_contents = (tmp_path / "rendaperene.log").read_text(encoding="utf-8")
    assert "session.reconnection_grace_started grace_seconds=120" in log_contents
    assert "session.connection_restored" in log_contents
    assert "application.no_active_sessions" in log_contents
    assert "ordinary session information" not in log_contents
    assert "verbose lifecycle details" not in log_contents


def test_file_logging_creates_directory_and_keeps_stdout(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LOG_TO_FILE", "TrUe")
    logs_dir = tmp_path / "logs"

    configure_logging(logs_dir)
    logging.getLogger("services.example").debug("portfolio service ready")

    captured = capsys.readouterr()
    log_file = logs_dir / "rendaperene.log"
    assert "portfolio service ready" in captured.out
    assert "portfolio service ready" in log_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("file_setting", ["true", "false"])
def test_file_logging_failure_falls_back_to_stdout(monkeypatch, tmp_path, capsys, file_setting):
    monkeypatch.setenv("LOG_TO_FILE", file_setting)

    def fail_file_handler(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(logging_config, "_OwnerOnlyRotatingFileHandler", fail_file_handler)

    configure_logging(tmp_path / "logs")
    logging.getLogger("core.example").info("application still running")

    captured = capsys.readouterr()
    assert "continuing with stdout only" in captured.out
    assert "application still running" in captured.out


def test_reconfiguration_does_not_duplicate_messages(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOG_TO_FILE", "true")
    logs_dir = tmp_path / "logs"

    configure_logging(logs_dir)
    configure_logging(logs_dir)
    logging.getLogger("views.example").info("render once")

    captured = capsys.readouterr()
    log_contents = (logs_dir / "rendaperene.log").read_text(encoding="utf-8")
    assert captured.out.count("render once") == 1
    assert log_contents.count("render once") == 1


def test_reconfiguration_keeps_warnings_when_verbose_file_logging_is_disabled(
    monkeypatch, tmp_path
):
    logs_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_TO_FILE", "true")
    configure_logging(logs_dir)
    logger = logging.getLogger("views.example")
    logger.info("written to file")

    monkeypatch.setenv("LOG_TO_FILE", "false")
    configure_logging(logs_dir)
    logger.info("stdout only")
    logger.warning("still recorded")

    log_contents = (logs_dir / "rendaperene.log").read_text(encoding="utf-8")
    assert "written to file" in log_contents
    assert "stdout only" not in log_contents
    assert log_contents.count("still recorded") == 1


def test_file_logging_rotates_and_limits_backups(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_TO_FILE", "true")
    monkeypatch.setattr(logging_config, "LOG_MAX_BYTES", 200)
    monkeypatch.setattr(logging_config, "LOG_BACKUP_COUNT", 3)
    logs_dir = tmp_path / "logs"

    configure_logging(logs_dir)
    logger = logging.getLogger("core.rotation")
    for index in range(20):
        logger.info("rotation message %s with enough content to fill the file", index)

    log_files = tuple(logs_dir.glob("rendaperene.log*"))
    assert 1 < len(log_files) <= 4


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes are not available")
def test_file_logging_restricts_existing_and_rotated_files_to_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_TO_FILE", "true")
    monkeypatch.setattr(logging_config, "LOG_MAX_BYTES", 200)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(mode=0o755)
    log_file = logs_dir / "rendaperene.log"
    log_file.write_text("existing log\n", encoding="utf-8")
    log_file.chmod(0o644)

    configure_logging(logs_dir)
    logger = logging.getLogger("core.rotation")
    for index in range(20):
        logger.info("rotation message %s with enough content to fill the file", index)

    assert stat.S_IMODE(logs_dir.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in logs_dir.glob("rendaperene.log*")
    )


def test_debug_logging_excludes_dependency_internals(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LOG_TO_FILE", "true")
    logs_dir = tmp_path / "logs"

    configure_logging(logs_dir)
    logging.getLogger("services.example").debug("application debug context")
    logging.getLogger("yfinance").debug("crumb = sensitive-session-material")
    logging.getLogger("peewee").debug("sensitive SQL internals")
    logging.getLogger("yfinance").warning("third-party warning with ticker BBAS3")

    captured = capsys.readouterr().out
    log_contents = (logs_dir / "rendaperene.log").read_text(encoding="utf-8")
    assert "application debug context" in captured
    assert "application debug context" in log_contents
    assert "sensitive-session-material" not in captured
    assert "sensitive-session-material" not in log_contents
    assert "sensitive SQL internals" not in captured
    assert "sensitive SQL internals" not in log_contents
    assert "third-party warning" not in captured
    assert "third-party warning" not in log_contents


@pytest.mark.parametrize("logger_name", ["streamlit.test_server", "tornado.test_server"])
@pytest.mark.parametrize("propagate", [True, False])
@pytest.mark.parametrize("file_setting", ["true", "false"])
def test_server_warnings_are_recorded_once_and_sanitized(
    monkeypatch, tmp_path, logger_name, propagate, file_setting
):
    monkeypatch.setenv("LOG_TO_FILE", file_setting)
    monkeypatch.setenv("APP_ENV", "dev")
    logger = logging.getLogger(logger_name)
    monkeypatch.setattr(logger, "propagate", propagate)
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    logs_dir = tmp_path / "logs"
    configure_logging(logs_dir)
    configure_logging(logs_dir)

    logger.debug("private debug payload")
    logger.info("private info payload")
    logger.warning("private warning payload %s", "token-secret")
    try:
        raise ConnectionError("private exception payload")
    except ConnectionError:
        logger.exception("private error payload", stack_info=True)

    log_contents = (logs_dir / "rendaperene.log").read_text(encoding="utf-8")
    assert log_contents.count("server.diagnostic") == 2
    assert "WARNING" in log_contents
    assert "ERROR" in log_contents
    assert logger_name in log_contents
    assert "exception_type=ConnectionError" in log_contents
    assert "private" not in log_contents
    assert "token-secret" not in log_contents
    assert "Traceback" not in log_contents
    assert "Stack" not in log_contents


def test_streamlit_formatter_update_preserves_file_logging(monkeypatch, tmp_path):
    from streamlit.logger import get_logger, setup_formatter

    monkeypatch.setenv("LOG_TO_FILE", "false")
    logger = get_logger("streamlit.test_formatter_update")
    logs_dir = tmp_path / "logs"
    configure_logging(logs_dir)
    setup_formatter(logger)
    logger.error("private server message")

    log_contents = (logs_dir / "rendaperene.log").read_text(encoding="utf-8")
    assert log_contents.count("server.diagnostic") == 1
    assert "private server message" not in log_contents

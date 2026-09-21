import logging

import pytest

import core.logging_config as logging_config
from core.logging_config import configure_logging


@pytest.fixture(autouse=True)
def restore_root_logging():
    root_logger = logging.getLogger()
    original_level = root_logger.level
    original_handlers = root_logger.handlers[:]
    yield
    for handler in root_logger.handlers[:]:
        if handler not in original_handlers:
            root_logger.removeHandler(handler)
            handler.close()
    root_logger.handlers[:] = original_handlers
    root_logger.setLevel(original_level)


def test_defaults_to_production_logging_on_stdout_only(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_TO_FILE", raising=False)

    configure_logging(tmp_path / "logs")
    logger = logging.getLogger("core.example")
    logger.debug("debug hidden")
    logger.info("startup complete")

    captured = capsys.readouterr()
    assert "startup complete" in captured.out
    assert "debug hidden" not in captured.out
    assert not (tmp_path / "logs").exists()


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
    assert not (tmp_path / "logs").exists()


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


def test_file_logging_failure_falls_back_to_stdout(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOG_TO_FILE", "true")

    def fail_file_handler(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(logging_config, "RotatingFileHandler", fail_file_handler)

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


def test_reconfiguration_disables_previous_file_handler(monkeypatch, tmp_path):
    logs_dir = tmp_path / "logs"
    monkeypatch.setenv("LOG_TO_FILE", "true")
    configure_logging(logs_dir)
    logger = logging.getLogger("views.example")
    logger.info("written to file")

    monkeypatch.setenv("LOG_TO_FILE", "false")
    configure_logging(logs_dir)
    logger.info("stdout only")

    log_contents = (logs_dir / "rendaperene.log").read_text(encoding="utf-8")
    assert "written to file" in log_contents
    assert "stdout only" not in log_contents


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

"""可选轮转文件日志。"""
from logging.handlers import RotatingFileHandler

from app import config, observability


def test_setup_logging_writes_file(tmp_path, monkeypatch):
    path = tmp_path / "app.log"
    monkeypatch.setattr(config, "LOG_FILE", str(path))
    monkeypatch.setattr(config, "LOG_MAX_BYTES", 1024)
    monkeypatch.setattr(config, "LOG_BACKUP_COUNT", 1)

    observability.setup_logging()
    observability.logger.info("hello log")
    for handler in observability.logger.handlers:
        handler.flush()
    try:
        assert path.exists()
        assert "hello log" in path.read_text(encoding="utf-8")
    finally:
        resolved = str(path.resolve())
        for handler in list(observability.logger.handlers):
            if isinstance(handler, RotatingFileHandler) and handler.baseFilename == resolved:
                observability.logger.removeHandler(handler)
                handler.close()

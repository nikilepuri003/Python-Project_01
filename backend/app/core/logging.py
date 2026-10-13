import logging
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "service"):
            payload["service"] = record.service
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        if hasattr(record, "trace_id"):
            payload["trace_id"] = record.trace_id
        return str(payload)


def get_logger(name: str, service: str = "backend") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    logger.handlers[0].formatter = JsonFormatter()
    logger = logging.LoggerAdapter(logger, {"service": service})
    return logger

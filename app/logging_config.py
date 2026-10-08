import json
import logging
import sys
from datetime import datetime, timezone
from app.security import mask_pii_in_text


class JSONFormatter(logging.Formatter):
    """Custom logging formatter that outputs JSON with automatic PII masking."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_pii_in_text(record.getMessage()),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_structured_logging():
    """Initializes structured JSON logging for the application."""
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

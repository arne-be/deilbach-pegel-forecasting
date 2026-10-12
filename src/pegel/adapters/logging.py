"""JSON-lines logging to stdout, so CloudWatch can filter on job, station and time window."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord has. Anything else on a record came in through `extra=`.
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
) | {"message", "asctime", "taskName"}

# httpx logs every request with its full URL at INFO. The URL carries the source host and
# the query, which must stay out of the logs.
_NOISY_LOGGERS = ("httpx", "httpcore")


class JsonLinesFormatter(logging.Formatter):
    """Formats each record as one JSON object: timestamp, level, logger, message and extras."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_RECORD_ATTRIBUTES and key not in entry:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    """Sends all logs as JSON lines to stdout, replacing any handlers already on the root."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLinesFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

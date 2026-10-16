"""Publishes the API's forecast and recent history as files, so page visits don't wake Neon."""

import logging
from datetime import datetime

from pegel.adapters.api_files import FORECAST_KEY, RECENT_KEY, WriteFile
from pegel.api.responses import Conn, forecast_response, history_response, to_json
from pegel.config import PegelConfig
from pegel.core.history import DISPLAY_TIME_ZONE, history_days

logger = logging.getLogger(__name__)


def publish_recent(conn: Conn, config: PegelConfig, write: WriteFile) -> None:
    """Writes the default history range up to today. Logs and returns on any error."""
    try:
        today = datetime.now(DISPLAY_TIME_ZONE).date()
        first_day, last_day = history_days(None, None, today, config.api)
        response = history_response(conn, config.forecast.station_id, first_day, last_day)
        _write(write, RECENT_KEY, to_json(response))
    except Exception:
        _log_failure(RECENT_KEY)


def publish_forecast(conn: Conn, config: PegelConfig, write: WriteFile) -> None:
    """Writes the forecast the API would serve. Logs and returns on any error."""
    try:
        response = forecast_response(conn, config)
        if response is None:
            raise RuntimeError("no forecast stored")
        _write(write, FORECAST_KEY, to_json(response))
    except Exception:
        _log_failure(FORECAST_KEY)


def _write(write: WriteFile, key: str, body: bytes) -> None:
    write(key, body)
    logger.info("published file", extra={"job": "publish", "key": key, "bytes": len(body)})


def _log_failure(key: str) -> None:
    logger.exception(
        "publishing failed, continuing without it", extra={"job": "publish", "key": key}
    )

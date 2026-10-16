"""The public read-only API. Locally with uvicorn; on AWS behind the Lambda Web Adapter.

The forecast and the default history range come from files the hourly run writes to S3, so
page visits don't wake Neon. Anything else, or a missing or unreadable file, comes from Neon.
"""

import logging
import os
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response

from pegel.adapters.api_files import FORECAST_KEY, RECENT_KEY, ReadFile, s3_reader
from pegel.adapters.env_files import load_env_files, main_checkout
from pegel.adapters.logging import configure_logging
from pegel.adapters.secrets import secrets_manager
from pegel.adapters.storage.connection import connect
from pegel.api.responses import forecast_response, history_response, matches_range, to_json
from pegel.api.schemas import ForecastResponse, HistoryResponse
from pegel.config import PegelConfig, load_config
from pegel.core.history import DISPLAY_TIME_ZONE, history_days

# Only plain dates, so a day has one spelling and one cache entry (no times, no timestamps).
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
ON_LAMBDA = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
# Recent data changes with every hourly run; days before yesterday are final. Yesterday's last
# readings only arrive with the 00:30 run. stale-if-error lets CloudFront bridge a failing API.
RECENT_CACHE = "public, max-age=300, stale-if-error=86400"
PAST_CACHE = "public, max-age=86400, stale-if-error=86400"

if ON_LAMBDA:
    configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Deilbach Pegel",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)


@cache
def get_config() -> PegelConfig:
    return load_config()


def get_today() -> date:
    return datetime.now(DISPLAY_TIME_ZONE).date()


@cache
def _database_url() -> str:
    if ON_LAMBDA:
        # shortcut: cached per container, so a rotated password needs recycled containers
        # (a redeploy). Fine while rotation is manual.
        return secrets_manager()(os.environ["API_DATABASE_URL_SECRET_NAME"]).strip()
    load_env_files(main_checkout())
    database_url = os.environ.get("API_DATABASE_URL")
    if not database_url:
        raise RuntimeError("API_DATABASE_URL is not set")
    return database_url


def get_database_url() -> Callable[[], str]:
    """Called only on the Neon path, so a request the files answer needs no database settings."""
    return _database_url


@cache
def get_read_file() -> ReadFile | None:
    """Reads the hourly run's files; None without API_FILES_BUCKET, e.g. locally."""
    bucket = os.environ.get("API_FILES_BUCKET")
    return s3_reader(bucket) if bucket else None


def _json(body: bytes, cache_control: str = RECENT_CACHE) -> Response:
    return Response(body, media_type="application/json", headers={"Cache-Control": cache_control})


def _read(read_file: ReadFile | None, endpoint: str, key: str) -> bytes | None:
    """The file's bytes, or None if there is no reader or the file can't be read (logged)."""
    if read_file is None:
        return None
    try:
        return read_file(key)
    except Exception as error:
        # Without s3:ListBucket a missing file is AccessDenied, not NoSuchKey: both land here.
        logger.warning(
            "api file unreadable, answering from the database",
            extra={"endpoint": endpoint, "key": key, "error": type(error).__name__},
        )
        return None


@app.get(
    "/api/forecast",
    response_model=ForecastResponse,
    responses={404: {"description": "No forecast stored yet"}},
)
def forecast(
    config: Annotated[PegelConfig, Depends(get_config)],
    database_url: Annotated[Callable[[], str], Depends(get_database_url)],
    read_file: Annotated[ReadFile | None, Depends(get_read_file)],
) -> Response:
    """The newest forecast of the configured model, with its issue time and the newest reading
    it used. Persistence instead when the model's forecast is missing or older, so a failing
    model step never leaves the page on a stale forecast."""
    body = _read(read_file, "forecast", FORECAST_KEY)
    if body is not None:
        return _json(body)
    with connect(database_url()) as conn:
        response = forecast_response(conn, config)
    if response is None:
        raise HTTPException(status_code=404, detail="no forecast yet")
    return _json(to_json(response))


@app.get("/api/history", response_model=HistoryResponse)
def history(
    config: Annotated[PegelConfig, Depends(get_config)],
    today: Annotated[date, Depends(get_today)],
    database_url: Annotated[Callable[[], str], Depends(get_database_url)],
    read_file: Annotated[ReadFile | None, Depends(get_read_file)],
    from_text: Annotated[
        str | None,
        Query(
            alias="from",
            pattern=DAY_PATTERN,
            description="First day (YYYY-MM-DD, Europe/Berlin)",
        ),
    ] = None,
    to_text: Annotated[
        str | None,
        Query(alias="to", pattern=DAY_PATTERN, description="Last day, included; defaults to today"),
    ] = None,
) -> Response:
    """Observed levels, outliers removed, for whole days. Without a range, the last days."""
    try:
        # fromisoformat also rejects days that don't exist, like 2026-02-30.
        first_day, last_day = history_days(
            date.fromisoformat(from_text) if from_text else None,
            date.fromisoformat(to_text) if to_text else None,
            today,
            config.api,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    # The file holds the default range only. Served only if its own range is exactly the one
    # asked for: after midnight it still ends yesterday until the next run replaces it.
    is_default = (first_day, last_day) == history_days(None, None, today, config.api)
    body = _read(read_file, "history", RECENT_KEY) if is_default else None
    if body is not None and matches_range(body, first_day, last_day):
        return _json(body)
    # The connection opens only after validation, so bad requests never wake the database.
    with connect(database_url()) as conn:
        response = history_response(conn, config.forecast.station_id, first_day, last_day)
    cache_control = PAST_CACHE if last_day < today - timedelta(days=1) else RECENT_CACHE
    return _json(to_json(response), cache_control)

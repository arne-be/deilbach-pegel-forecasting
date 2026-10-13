"""The public read-only API. Locally with uvicorn; on AWS behind the Lambda Web Adapter."""

import os
from datetime import date, datetime
from functools import cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from pegel.adapters.env_files import load_env_files, main_checkout
from pegel.adapters.storage.connection import connect
from pegel.adapters.storage.forecasts import newest_forecast
from pegel.adapters.storage.observations import fetch_observations
from pegel.api.schemas import (
    ForecastPointResponse,
    ForecastResponse,
    HistoryPoint,
    HistoryResponse,
)
from pegel.config import PegelConfig, load_config
from pegel.core.history import DISPLAY_TIME_ZONE, history_days, utc_window

# Only plain dates, so a day has one spelling and one cache entry (no times, no timestamps).
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

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
def get_database_url() -> str:
    # On Lambda the environment is set already, and there is no git checkout to read from.
    if "AWS_LAMBDA_FUNCTION_NAME" not in os.environ:
        load_env_files(main_checkout())
    database_url = os.environ.get("API_DATABASE_URL")
    if not database_url:
        raise RuntimeError("API_DATABASE_URL is not set")
    return database_url


@app.get("/api/forecast", responses={404: {"description": "No forecast stored yet"}})
def forecast(
    config: Annotated[PegelConfig, Depends(get_config)],
    database_url: Annotated[str, Depends(get_database_url)],
) -> ForecastResponse:
    """The newest forecast, with its issue time and the newest reading it used."""
    with connect(database_url) as conn:
        newest = newest_forecast(conn, config.forecast.station_id, config.forecast.model)
    if newest is None:
        raise HTTPException(status_code=404, detail="no forecast yet")
    return ForecastResponse(
        station_id=newest.station_id,
        model=newest.model,
        issued_at=newest.issued_at,
        newest_observation_at=newest.newest_observation_at,
        points=[
            ForecastPointResponse(valid_at=point.valid_at, level_cm=point.level_cm)
            for point in newest.points
        ],
    )


@app.get("/api/history")
def history(
    config: Annotated[PegelConfig, Depends(get_config)],
    today: Annotated[date, Depends(get_today)],
    database_url: Annotated[str, Depends(get_database_url)],
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
) -> HistoryResponse:
    """Observed levels for whole days. Without a range, the last days up to today."""
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
    station_id = config.forecast.station_id
    # The connection opens only after validation, so bad requests never wake the database.
    with connect(database_url) as conn:
        observations = fetch_observations(conn, station_id, *utc_window(first_day, last_day))
    return HistoryResponse(
        station_id=station_id,
        first_day=first_day,
        last_day=last_day,
        observations=[
            HistoryPoint(observed_at=observation.observed_at, level_cm=observation.level_cm)
            for observation in observations
        ],
    )

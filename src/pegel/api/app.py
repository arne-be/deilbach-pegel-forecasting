"""The public read-only API. Locally with uvicorn; on AWS behind the Lambda Web Adapter."""

import os
from datetime import date, datetime
from functools import cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from pegel.adapters.env_files import load_env_files, main_checkout
from pegel.adapters.storage.connection import connect
from pegel.adapters.storage.observations import fetch_observations
from pegel.api.schemas import HistoryPoint, HistoryResponse
from pegel.config import PegelConfig, load_config
from pegel.core.history import DISPLAY_TIME_ZONE, history_days, utc_window

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


@app.get("/api/history")
def history(
    config: Annotated[PegelConfig, Depends(get_config)],
    today: Annotated[date, Depends(get_today)],
    database_url: Annotated[str, Depends(get_database_url)],
    first_day: Annotated[
        date | None, Query(alias="from", description="First day (YYYY-MM-DD, Europe/Berlin)")
    ] = None,
    last_day: Annotated[
        date | None, Query(alias="to", description="Last day, included; defaults to today")
    ] = None,
) -> HistoryResponse:
    """Observed levels for whole days. Without a range, the last days up to today."""
    try:
        first_day, last_day = history_days(
            first_day,
            last_day,
            today,
            config.api.history_default_days,
            config.api.history_max_days,
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
            HistoryPoint(observed_at=observation.observed_at, level_m=observation.level_m)
            for observation in observations
        ],
    )

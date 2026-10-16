"""Response bodies built from storage. One place, so the API and the files the hourly run
publishes for it can't drift apart."""

import json
from datetime import date

import psycopg
from psycopg.rows import TupleRow
from pydantic import BaseModel

from pegel.adapters.storage.forecasts import newest_forecast
from pegel.adapters.storage.observations import fetch_values
from pegel.api.schemas import (
    BandResponse,
    ForecastPointResponse,
    ForecastResponse,
    HistoryPoint,
    HistoryResponse,
)
from pegel.config import PegelConfig
from pegel.core.history import utc_window
from pegel.core.persistence import MODEL_NAME as PERSISTENCE
from pegel.core.series import cleaned_level_series_id

Conn = psycopg.Connection[TupleRow]


def forecast_response(conn: Conn, config: PegelConfig) -> ForecastResponse | None:
    """The newest forecast of the configured model, or None if there is none. Persistence
    instead when the model's forecast is missing or older, so a failing model step never
    leaves the page on a stale forecast."""
    station_id = config.forecast.station_id
    newest = newest_forecast(conn, station_id, config.forecast.model)
    if config.forecast.model != PERSISTENCE:
        fallback = newest_forecast(conn, station_id, PERSISTENCE)
        if newest is None or (fallback is not None and fallback.issued_at > newest.issued_at):
            newest = fallback
    if newest is None:
        return None
    return ForecastResponse(
        station_id=newest.station_id,
        model=newest.model,
        issued_at=newest.issued_at,
        newest_observation_at=newest.newest_observation_at,
        situation=newest.situation,
        points=[
            ForecastPointResponse(
                valid_at=point.valid_at,
                level_cm=point.level_cm,
                bands=[
                    BandResponse(
                        coverage_percent=band.coverage_percent,
                        lower_cm=band.lower_cm,
                        upper_cm=band.upper_cm,
                    )
                    for band in point.bands
                ],
            )
            for point in newest.points
        ],
    )


def history_response(
    conn: Conn, station_id: str, first_day: date, last_day: date
) -> HistoryResponse:
    """The cleaned levels of whole Berlin days, both included."""
    values = fetch_values(
        conn, cleaned_level_series_id(station_id), *utc_window(first_day, last_day)
    )
    return HistoryResponse(
        station_id=station_id,
        first_day=first_day,
        last_day=last_day,
        observations=[
            HistoryPoint(observed_at=value.valid_at, level_cm=value.value) for value in values
        ],
    )


def to_json(response: BaseModel) -> bytes:
    """The body as FastAPI would send it, with aliases such as "from" and "to"."""
    return response.model_dump_json(by_alias=True).encode()


def matches_range(body: bytes, first_day: date, last_day: date) -> bool:
    """Whether a history body covers exactly these days. False for a body that isn't JSON."""
    try:
        data = json.loads(body)
        return bool(data["from"] == first_day.isoformat() and data["to"] == last_day.isoformat())
    except (ValueError, KeyError, TypeError):
        return False

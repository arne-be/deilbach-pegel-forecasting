"""The ingest and forecast steps. Each takes its time window, so it can rerun for any period."""

import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

import psycopg
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import save_forecast
from pegel.adapters.storage.observations import newest_observation, upsert_observations
from pegel.adapters.storage.series import ensure_series
from pegel.config import PegelConfig, Station
from pegel.core.forecasts import Forecast
from pegel.core.observations import Observation
from pegel.core.persistence import persistence_forecast
from pegel.core.schedule import monthly_windows
from pegel.core.series import level_series

logger = logging.getLogger(__name__)

Conn = psycopg.Connection[TupleRow]
# Fetches a station's readings in [start, end). The source adapter, passed in for testing.
FetchLevels = Callable[[Station, datetime, datetime], list[Observation]]


class NoObservationError(Exception):
    """There is no observation to base a forecast on."""


def ingest(fetch: FetchLevels, conn: Conn, station: Station, start: datetime, end: datetime) -> int:
    """Fetches and stores one window. Returns the number of new or changed rows."""
    observations = fetch(station, start, end)
    ensure_series(conn, [level_series(station)])
    changed = upsert_observations(conn, observations)
    logger.info(
        "ingested window",
        extra={
            "job": "ingest",
            "station": station.id,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "fetched": len(observations),
            "changed": changed,
        },
    )
    return changed


def fetch_by_source(
    fetchers: Mapping[str, FetchLevels], station: Station, start: datetime, end: datetime
) -> list[Observation]:
    """Fetches from the station's own source. Bind `fetchers` to get a FetchLevels."""
    return fetchers[station.source](station, start, end)


def backfill(
    fetch: FetchLevels, conn: Conn, station: Station, start: datetime, end: datetime
) -> int:
    """Ingests [start, end) in monthly chunks, so one failed month doesn't lose the others."""
    return sum(
        ingest(fetch, conn, station, window_start, window_end)
        for window_start, window_end in monthly_windows(start, end)
    )


def forecast(conn: Conn, config: PegelConfig, issued_at: datetime) -> Forecast:
    """Builds and stores the persistence forecast from the newest observation at issue time."""
    station_id = config.forecast.station_id
    newest = newest_observation(conn, station_id, at_or_before=issued_at)
    if newest is None:
        raise NoObservationError(f"no observation for {station_id} at or before {issued_at}")
    result = persistence_forecast(newest, issued_at, config.forecast.horizon_hours)
    save_forecast(conn, result)
    logger.info(
        "saved forecast",
        extra={
            "job": "forecast",
            "station": station_id,
            "model": result.model,
            "issued_at": issued_at.isoformat(),
            "newest_observation_at": newest.observed_at.isoformat(),
            "observation_age_minutes": (issued_at - newest.observed_at) // timedelta(minutes=1),
        },
    )
    return result


def run_hourly(
    fetch: FetchLevels, conn: Conn, config: PegelConfig, issued_at: datetime
) -> Forecast:
    """Ingests the recent hours of every station, then forecasts.

    Only uses readings up to the issue time. A failing upstream station is logged and skipped,
    so it can't block the forecast; a failing forecast station fails the run.
    """
    forecast_station = config.station(config.forecast.station_id)
    start = issued_at - timedelta(hours=config.forecast.ingest_lookback_hours)
    ingest(fetch, conn, forecast_station, start, issued_at)
    upstream_start = issued_at - timedelta(hours=config.forecast.upstream_ingest_lookback_hours)
    for station in config.stations:
        if station.id == forecast_station.id:
            continue
        try:
            ingest(fetch, conn, station, upstream_start, issued_at)
        except Exception:
            logger.exception(
                "upstream ingest failed, continuing without it",
                extra={
                    "job": "ingest",
                    "station": station.id,
                    "window_start": upstream_start.isoformat(),
                    "window_end": issued_at.isoformat(),
                },
            )
    return forecast(conn, config, issued_at)

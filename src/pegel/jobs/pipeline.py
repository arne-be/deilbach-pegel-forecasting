"""The ingest, clean and forecast steps. Each takes its time window, so it can rerun."""

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import save_forecast
from pegel.adapters.storage.observations import (
    delete_values,
    fetch_values,
    newest_value,
    upsert_values,
)
from pegel.adapters.storage.series import ensure_series
from pegel.config import PegelConfig, Station
from pegel.core.cleaning import outlier_flags
from pegel.core.forecasts import Forecast
from pegel.core.observations import Observation
from pegel.core.persistence import MODEL_NAME as PERSISTENCE
from pegel.core.persistence import persistence_forecast
from pegel.core.schedule import issue_time, monthly_windows, scheduled_available_at
from pegel.core.series import (
    SeriesValue,
    cleaned_level_series,
    cleaned_level_series_id,
    level_series,
    level_series_id,
)
from pegel.jobs.model_forecast import ModelLoader, model_forecast

logger = logging.getLogger(__name__)

Conn = psycopg.Connection[TupleRow]
# Fetches a station's readings in [start, end). The source adapter, passed in for testing.
FetchLevels = Callable[[Station, datetime, datetime], list[Observation]]
# An extra input for the hourly run, e.g. radar rain. Gets the connection and the issue time,
# stores what it fetched and returns the number of new or changed rows.
HourlyStep = Callable[[Conn, datetime], int]


class NoObservationError(Exception):
    """There is no observation to base a forecast on."""


def ingest(
    fetch: FetchLevels,
    conn: Conn,
    station: Station,
    start: datetime,
    end: datetime,
    issue_minute: int,
    *,
    live: bool,
) -> int:
    """Fetches and stores one window. Returns the number of new or changed rows.

    Live runs stamp new values with the issue slot of the fetch, so the run that fetched them
    may use them. Backfills can't know when a value first appeared, so they use the slot the
    hourly run would first have used it in.
    """
    observations = fetch(station, start, end)
    seen_at = issue_time(datetime.now(UTC), issue_minute)
    series = level_series(station)
    ensure_series(conn, [series])
    values = [
        SeriesValue(
            series.id,
            observation.observed_at,
            # Rounded like the migration that shifted the stored values, so reruns change nothing.
            round(observation.level_cm + station.level_offset_cm, 3),
            seen_at
            if live
            else scheduled_available_at(
                observation.observed_at,
                timedelta(minutes=station.available_after_minutes),
                issue_minute,
            ),
        )
        for observation in observations
    ]
    changed = upsert_values(conn, values, seen_at)
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
    fetch: FetchLevels,
    conn: Conn,
    station: Station,
    start: datetime,
    end: datetime,
    issue_minute: int,
) -> int:
    """Ingests [start, end) in monthly chunks, so one failed month doesn't lose the others."""
    return sum(
        ingest(fetch, conn, station, window_start, window_end, issue_minute, live=False)
        for window_start, window_end in monthly_windows(start, end)
    )


def clean(conn: Conn, config: PegelConfig, station: Station, start: datetime, end: datetime) -> int:
    """Writes the cleaned levels of [start, end). Returns rows written or deleted.

    The filter replays from `warm_up_hours` before the window, so it needs no stored state.
    A reading rejected on a rerun is deleted from the cleaned series, so reruns converge.
    """
    warm_up_start = start - timedelta(hours=config.cleaning.warm_up_hours)
    raw = fetch_values(conn, level_series_id(station.id), warm_up_start, end)
    flags = outlier_flags(raw, config.cleaning)
    in_window = [
        (value, flag) for value, flag in zip(raw, flags, strict=True) if value.valid_at >= start
    ]
    cleaned_id = cleaned_level_series_id(station.id)
    # Our zero is below the lowest level ever seen, so a reading under it is a sensor error.
    accepted = [
        SeriesValue(cleaned_id, value.valid_at, max(value.value, 0.0), value.available_at)
        for value, flag in in_window
        if not flag
    ]
    rejected = [value.valid_at for value, flag in in_window if flag]
    ensure_series(conn, [cleaned_level_series(station)])
    seen_at = issue_time(datetime.now(UTC), config.forecast.issue_minute)
    changed = upsert_values(conn, accepted, seen_at) + delete_values(conn, cleaned_id, rejected)
    logger.info(
        "cleaned window",
        extra={
            "job": "clean",
            "station": station.id,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "changed": changed,
        },
    )
    return changed


def clean_history(
    conn: Conn, config: PegelConfig, station: Station, start: datetime, end: datetime
) -> int:
    """Cleans [start, end) in monthly chunks, so one failed month doesn't lose the others."""
    return sum(
        clean(conn, config, station, window_start, window_end)
        for window_start, window_end in monthly_windows(start, end)
    )


def forecast(conn: Conn, config: PegelConfig, issued_at: datetime) -> Forecast:
    """Builds and stores the persistence forecast from the newest cleaned level at issue time.

    Cleaned, so a spike never becomes the forecast; its time is then the newest accepted reading.
    """
    station_id = config.forecast.station_id
    value = newest_value(conn, cleaned_level_series_id(station_id), at_or_before=issued_at)
    if value is None:
        raise NoObservationError(f"no observation for {station_id} at or before {issued_at}")
    newest = Observation(station_id, value.valid_at, value.value)
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
    fetch: FetchLevels,
    conn: Conn,
    config: PegelConfig,
    issued_at: datetime,
    extra_steps: Sequence[tuple[str, HourlyStep]] = (),
    load_model: ModelLoader | None = None,
) -> Forecast:
    """Ingests the recent hours of every station and the extra inputs, cleans the forecast
    station's levels, then forecasts. Returns the forecast the page shows.

    Only uses readings up to the issue time. A failing upstream station or extra step is logged
    and skipped, so it can't block the forecast; a failing forecast station fails the run.
    """
    forecast_station = config.station(config.forecast.station_id)
    start = issued_at - timedelta(hours=config.forecast.ingest_lookback_hours)
    issue_minute = config.forecast.issue_minute
    ingest(fetch, conn, forecast_station, start, issued_at, issue_minute, live=True)
    clean(conn, config, forecast_station, start, issued_at)
    upstream_start = issued_at - timedelta(hours=config.forecast.upstream_ingest_lookback_hours)
    for station in config.stations:
        if station.id == forecast_station.id:
            continue
        try:
            ingest(fetch, conn, station, upstream_start, issued_at, issue_minute, live=True)
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
    for name, step in extra_steps:
        try:
            step(conn, issued_at)
        except Exception:
            logger.exception(
                "hourly step failed, continuing without it",
                extra={"job": name, "issued_at": issued_at.isoformat()},
            )
    # Always saved, and first: it is the baseline and the page's fallback.
    persistence = forecast(conn, config, issued_at)
    if config.forecast.model == PERSISTENCE:
        return persistence
    return save_model_forecast(conn, config, issued_at, load_model) or persistence


def save_model_forecast(
    conn: Conn, config: PegelConfig, issued_at: datetime, load_model: ModelLoader | None
) -> Forecast | None:
    """Builds and stores the configured model's forecast; None if anything fails (logged)."""
    context = {
        "job": "forecast",
        "model": config.forecast.model,
        "issued_at": issued_at.isoformat(),
    }
    try:
        if load_model is None:
            raise RuntimeError("no model loader passed")
        result = model_forecast(conn, config, issued_at, load_model())
        save_forecast(conn, result)
    except Exception:
        logger.exception("model forecast failed, keeping the persistence forecast", extra=context)
        return None
    logger.info(
        "saved forecast",
        extra=context | {"newest_observation_at": result.newest_observation_at.isoformat()},
    )
    return result

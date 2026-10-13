"""ICON-D2 rain forecasts: the newest run in the hourly job, and the archive backfill."""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx

from pegel.adapters.sources import open_meteo
from pegel.adapters.storage.input_forecasts import newest_run_at, upsert_input_forecasts
from pegel.adapters.storage.series import ensure_series
from pegel.config import RainForecastSettings, config_file
from pegel.core.rain_forecast import (
    GridPoint,
    archive_values,
    catchment_series_id,
    check_run,
    forecast_series,
    run_values,
)
from pegel.core.schedule import issue_time
from pegel.jobs.pipeline import Conn, HourlyStep

logger = logging.getLogger(__name__)

LIVE_NOTE = "run_at is the run start from Open-Meteo's ICON-D2 metadata."
ARCHIVE_NOTE = (
    "From the Previous Runs API; run_at is approximate: the newest 3-hourly run starting "
    "before valid_at (day 0) or before valid_at - 24 h (day 1), see docs/catchment.md."
)
# Previous Runs variables and how many days before valid_at their run started.
ARCHIVE_VARIABLES = {"precipitation": 0, "precipitation_previous_day1": 1}
ARCHIVE_CHUNK_DAYS = 14
# One 70-point chunk weighs 70 calls. A request a minute stays far below Open-Meteo's 600 calls
# a minute and, with the hourly job, below its 5,000 an hour.
ARCHIVE_SECONDS_BETWEEN_REQUESTS = 60.0
# Per invocation; stop well before the 10,000 calls a day, leaving room for the hourly job.
# Reaching it, or a 429, stops the backfill cleanly with the date to resume from.
ARCHIVE_MAX_CALLS = 9000
# Day 0 values of the last hours aren't final until their run is out (about 85 min after it
# starts); before that the archive serves longer lead times under the same variable.
ARCHIVE_SETTLE_TIME = timedelta(hours=3)


def hourly_step(
    client: httpx.Client, settings: RainForecastSettings, issue_minute: int
) -> HourlyStep:
    """The hourly job's rain forecast step. Ignores the issue time: it stores runs as they come."""
    points = open_meteo.load_points(config_file(settings.points_file))
    return lambda conn, _issued_at: ingest_newest_run(client, conn, settings, points, issue_minute)


def ingest_newest_run(
    client: httpx.Client,
    conn: Conn,
    settings: RainForecastSettings,
    points: Sequence[GridPoint],
    issue_minute: int,
) -> int:
    """Stores the newest ICON-D2 run if it isn't stored yet. Returns the changed row count.

    The run is available from the issue slot of the fetch, so the run that fetched it may use it.

    Without a new run it only reads the small metadata file, no forecast request. Requests get
    one short try each, so a slow Open-Meteo can't hold up the level forecast.
    """
    run_at = open_meteo.latest_run(client)
    stored = newest_run_at(conn, catchment_series_id(settings.source))
    context = {"job": "rain_forecast", "run_at": run_at.isoformat()}
    if stored is not None and stored >= run_at:
        logger.info("no new rain forecast run", extra=context)
        return 0
    try:
        # One hour past the horizon, so check_run can tell this run from its neighbours.
        series = open_meteo.fetch_forecast(
            client,
            points,
            run_at + timedelta(hours=1),
            run_at + timedelta(hours=settings.horizon_hours + 1),
        )
    except open_meteo.RateLimitedError as error:
        logger.warning(
            "open-meteo rate limit, next run catches up", extra=context | {"error": str(error)}
        )
        return 0
    seen_at = issue_time(datetime.now(UTC), issue_minute)
    check_run(series, run_at, settings.horizon_hours)
    # check_run catches a whole answer from another run. This catches the next run finishing
    # while the answer was being built, which could mix both runs within one point's hours.
    if open_meteo.latest_run(client) != run_at:
        logger.warning("new run published during the fetch, next run catches up", extra=context)
        return 0
    values = run_values(
        settings.source,
        series,
        points,
        run_at,
        settings.horizon_hours,
        settings.ring_percentile,
        seen_at,
    )
    ensure_series(
        conn,
        forecast_series(
            settings.source,
            settings.ring_percentile,
            LIVE_NOTE,
            timedelta(minutes=settings.available_after_minutes),
        ),
    )
    changed = upsert_input_forecasts(conn, values, seen_at)
    logger.info(
        "stored rain forecast run", extra=context | {"values": len(values), "changed": changed}
    )
    return changed


@dataclass(frozen=True)
class ArchiveResult:
    changed: int
    calls: float
    # The first day not loaded when the call budget ran out or Open-Meteo refused, else None.
    resume_from: date | None


def backfill_archive(
    client: httpx.Client,
    conn: Conn,
    settings: RainForecastSettings,
    points: Sequence[GridPoint],
    first_day: date,
    end_day: date,
    issue_minute: int,
    *,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> ArchiveResult:
    """Loads Previous Runs values for the UTC days [first_day, end_day) in 14-day chunks.

    Each run gets the available_at the live system would have given it: the first hourly run
    (at `issue_minute`) after run_at + available_after.
    """
    source, percentile = settings.archive_source, settings.ring_percentile
    available_after = timedelta(minutes=settings.available_after_minutes)
    ensure_series(conn, forecast_series(source, percentile, ARCHIVE_NOTE, available_after))
    settled_until = now.astimezone(UTC) - ARCHIVE_SETTLE_TIME
    changed, calls = 0, 0.0
    chunk_start = first_day
    while chunk_start < end_day:
        chunk_end = min(chunk_start + timedelta(days=ARCHIVE_CHUNK_DAYS), end_day)
        days = (chunk_end - chunk_start).days
        weight = open_meteo.request_weight(len(points), days, len(ARCHIVE_VARIABLES))
        if calls + weight > ARCHIVE_MAX_CALLS:
            return ArchiveResult(changed, calls, chunk_start)
        if calls:
            sleep(ARCHIVE_SECONDS_BETWEEN_REQUESTS)
        try:
            by_variable = open_meteo.fetch_archive(
                client,
                points,
                list(ARCHIVE_VARIABLES),
                chunk_start,
                chunk_end - timedelta(days=1),
                sleep=sleep,
            )
        except open_meteo.RateLimitedError:
            logger.exception("open-meteo rate limit", extra={"job": "rain_forecast_backfill"})
            return ArchiveResult(changed, calls, chunk_start)
        calls += weight
        values = [
            value
            for variable, days_before in ARCHIVE_VARIABLES.items()
            for value in archive_values(
                source,
                by_variable[variable],
                points,
                days_before,
                percentile,
                available_after,
                issue_minute,
            )
            if value.valid_at <= settled_until
        ]
        seen_at = issue_time(datetime.now(UTC), issue_minute)
        chunk_changed = upsert_input_forecasts(conn, values, seen_at)
        changed += chunk_changed
        logger.info(
            "stored rain forecast archive chunk",
            extra={
                "job": "rain_forecast_backfill",
                "window_start": chunk_start.isoformat(),
                "window_end": chunk_end.isoformat(),
                "values": len(values),
                "changed": chunk_changed,
            },
        )
        chunk_start = chunk_end
    return ArchiveResult(changed, calls, None)

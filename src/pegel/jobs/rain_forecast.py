"""ICON-D2 rain forecasts: the newest run in the hourly job, and the run and archive backfills."""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx

from pegel.adapters.sources import open_meteo
from pegel.adapters.storage.input_forecasts import stored_runs_since, upsert_input_forecasts
from pegel.adapters.storage.series import ensure_series
from pegel.config import RainForecastSettings, config_file
from pegel.core.rain_forecast import (
    RUN_INTERVAL,
    GridPoint,
    RunMismatchError,
    archive_values,
    catchment_series_id,
    check_run,
    forecast_series,
    missing_runs,
    run_values,
)
from pegel.core.schedule import issue_time, scheduled_available_at
from pegel.jobs.pipeline import Conn, HourlyStep

logger = logging.getLogger(__name__)

LIVE_NOTE = "From Open-Meteo's Single Runs API; run_at is the run start."
ARCHIVE_NOTE = (
    "From the Previous Runs API; run_at is approximate: the newest 3-hourly run starting "
    "before valid_at (day 0) or before valid_at - 24 h (day 1), see docs/catchment.md."
)
# Catch up on runs missed by failed hourly runs, as long as they still cover most of the horizon.
CATCH_UP = timedelta(hours=24)
# Each run is one request of about 70 calls; four keep a long outage's catch-up from holding up
# the level forecast, and the next hours fetch the rest.
MAX_RUNS_PER_HOUR = 4
# No older run is started after this: on a slow Open-Meteo one run can take 125 s (2 x 60 s and
# the backoff), and four would push the 900 s Lambda past its limit and lose the level forecast.
CATCH_UP_BUDGET_SECONDS = 120.0
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
    return lambda conn, _issued_at: ingest_new_runs(client, conn, settings, points, issue_minute)


def ingest_new_runs(
    client: httpx.Client,
    conn: Conn,
    settings: RainForecastSettings,
    points: Sequence[GridPoint],
    issue_minute: int,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Stores the runs of the last CATCH_UP not stored yet, newest first: the level forecast
    needs the newest, older runs only matter for training. Returns the changed row count.

    A run is available from the issue slot of its fetch, so the run that fetched it may use it, and
    a run caught up late is honestly late. Without a new run it only reads the small metadata file.
    A failing run, or the time budget, stops the catch-up for this hour; the next hour goes on.
    """
    started = clock()
    newest = open_meteo.latest_run(client)
    stored = stored_runs_since(conn, catchment_series_id(settings.source), newest - CATCH_UP)
    runs = missing_runs(newest, stored, CATCH_UP)[:MAX_RUNS_PER_HOUR]
    if not runs:
        logger.info(
            "no new rain forecast run", extra={"job": "rain_forecast", "run_at": newest.isoformat()}
        )
        return 0
    ensure_series(conn, forecast_series(settings.source, settings.ring_percentile, LIVE_NOTE))
    changed = 0
    for run_at in runs:
        context = {"job": "rain_forecast", "run_at": run_at.isoformat()}
        if run_at != newest and clock() - started > CATCH_UP_BUDGET_SECONDS:
            logger.warning("rain forecast time budget used, next hour catches up", extra=context)
            break
        try:
            changed += ingest_run(client, conn, settings, points, issue_minute, run_at, context)
        except (open_meteo.OpenMeteoError, RunMismatchError):
            logger.exception("rain forecast run failed, next hour catches up", extra=context)
            break
    return changed


def ingest_run(
    client: httpx.Client,
    conn: Conn,
    settings: RainForecastSettings,
    points: Sequence[GridPoint],
    issue_minute: int,
    run_at: datetime,
    context: dict[str, str],
    *,
    available_at: datetime | None = None,
) -> int:
    """Fetches, checks and stores one run. Returns the changed row count.

    Without `available_at` the run is available from the issue slot of its fetch.
    """
    # One hour past the horizon, so check_run can tell a shortened answer from a whole run.
    series = open_meteo.fetch_run(client, points, run_at, settings.horizon_hours + 1)
    seen_at = issue_time(datetime.now(UTC), issue_minute)
    check_run(series, run_at, settings.horizon_hours)
    values = run_values(
        settings.source,
        series,
        points,
        run_at,
        settings.horizon_hours,
        settings.ring_percentile,
        available_at or seen_at,
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
    ensure_series(conn, forecast_series(source, percentile, ARCHIVE_NOTE))
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


@dataclass(frozen=True)
class RunsResult:
    changed: int
    calls: float
    failed: int
    # The first day not loaded when the call budget ran out or Open-Meteo refused, else None.
    resume_from: date | None


def backfill_runs(
    client: httpx.Client,
    conn: Conn,
    settings: RainForecastSettings,
    points: Sequence[GridPoint],
    first_day: date,
    end_day: date,
    issue_minute: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> RunsResult:
    """Loads the runs starting in the UTC days [first_day, end_day) that the live series doesn't
    have, oldest first, from Single Runs: every lead time, like the hourly job stores them.

    Each run gets the available_at the live system would have given it. The last CATCH_UP stays
    with the hourly job, which stamps runs by their fetch. A failing run is logged and skipped;
    a rerun tries it again.
    """
    start = datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC)
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=UTC)
    last = min(open_meteo.latest_run(client) - CATCH_UP, end - RUN_INTERVAL)
    if last < start:
        return RunsResult(0, 0.0, 0, None)
    stored = stored_runs_since(conn, catchment_series_id(settings.source), start)
    runs = missing_runs(last, stored, last - start)[::-1]
    ensure_series(conn, forecast_series(settings.source, settings.ring_percentile, LIVE_NOTE))
    available_after = timedelta(minutes=settings.available_after_minutes)
    # A run spans three calendar days but stays far below 14, so it weighs one call per point.
    weight = open_meteo.request_weight(len(points), 3, 1)
    changed, calls, failed = 0, 0.0, 0
    for run_at in runs:
        if calls + weight > ARCHIVE_MAX_CALLS:
            return RunsResult(changed, calls, failed, run_at.date())
        if calls:
            sleep(ARCHIVE_SECONDS_BETWEEN_REQUESTS)
        calls += weight
        context = {"job": "rain_forecast_backfill", "run_at": run_at.isoformat()}
        available_at = scheduled_available_at(run_at, available_after, issue_minute)
        try:
            changed += ingest_run(
                client,
                conn,
                settings,
                points,
                issue_minute,
                run_at,
                context,
                available_at=available_at,
            )
        except open_meteo.RateLimitedError:
            logger.exception("open-meteo rate limit", extra=context)
            return RunsResult(changed, calls, failed, run_at.date())
        except (open_meteo.OpenMeteoError, RunMismatchError):
            logger.exception("rain forecast run failed, a rerun tries it again", extra=context)
            failed += 1
    return RunsResult(changed, calls, failed, None)

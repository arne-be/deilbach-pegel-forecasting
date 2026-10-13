"""Radar rain jobs: the hourly step from the live folder and the backfill from DWD's archives."""

import logging
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import httpx

from pegel.adapters.sources.radolan import (
    RECENT_ARCHIVE_START,
    RadolanError,
    RadolanGrid,
    fetch_live,
    fetch_recent,
    historical_month,
    load_cells,
)
from pegel.adapters.storage.observations import upsert_values
from pegel.adapters.storage.series import ensure_series
from pegel.config import PegelConfig, config_file
from pegel.core.radar import radar_series, radar_values
from pegel.core.schedule import issue_time, monthly_windows, scheduled_available_at
from pegel.jobs.pipeline import Conn, HourlyStep

logger = logging.getLogger(__name__)

PRODUCT_MINUTE = 50


def product_times(start: datetime, end: datetime) -> list[datetime]:
    """The hourly RW product times (hh:50) with start <= time < end, oldest first."""
    first = start.replace(minute=PRODUCT_MINUTE, second=0, microsecond=0)
    if first < start:
        first += timedelta(hours=1)
    times = []
    while first < end:
        times.append(first)
        first += timedelta(hours=1)
    return times


def store_grids(
    conn: Conn,
    config: PegelConfig,
    grids: Iterable[RadolanGrid],
    job: str,
    live_slot: datetime | None,
) -> tuple[int, int]:
    """Aggregates each grid into the radar series and stores them in one batch.

    Live runs pass the issue slot in which they fetched the grids. Backfills pass None: each hour
    is then available at the first hourly run after its product time plus the radar delay, as
    live would have been. Returns the number of new or changed rows and the number of hours read.
    """
    cells = load_cells(config_file(config.rain.radar.cells_file))
    available_after = timedelta(minutes=config.rain.radar.available_after_minutes)
    series = radar_series(config.rain.radar.source, list(cells))
    ensure_series(conn, list(series.values()))
    values = []
    hours = 0
    for grid in grids:
        hours += 1
        available_at = live_slot or scheduled_available_at(
            grid.product_time, available_after, config.forecast.issue_minute
        )
        hour_values = radar_values(series, cells, grid.product_time, grid.rain_mm, available_at)
        missing = {one.id for one in series.values()} - {value.series_id for value in hour_values}
        if missing:
            logger.warning(
                "radar series without any cell with data",
                extra={
                    "job": job,
                    "valid_at": grid.product_time.isoformat(),
                    "series": sorted(missing),
                },
            )
        values.extend(hour_values)
    # After the loop, so a backfill's lazy grids have been fetched by now.
    seen_at = live_slot or issue_time(datetime.now(UTC), config.forecast.issue_minute)
    return upsert_values(conn, values, seen_at), hours


def radar_step(
    config: PegelConfig,
    client: httpx.Client,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> HourlyStep:
    """The hourly step: the last few RW products before the issue time from the live folder.

    Values are available from the issue slot of the fetch, so the run that fetched them may use
    them, even when it reruns a past issue time.
    """

    def step(conn: Conn, issued_at: datetime) -> int:
        lookback = timedelta(hours=config.rain.radar.ingest_lookback_hours)
        times = product_times(issued_at - lookback, issued_at)
        grids = list(_published(partial(fetch_live, client), times, "radar_rain"))
        seen_at = issue_time(now(), config.forecast.issue_minute)
        changed, _ = store_grids(conn, config, grids, "radar_rain", seen_at)
        logger.info(
            "ingested radar rain",
            extra={"job": "radar_rain", "issued_at": issued_at.isoformat(), "changed": changed},
        )
        return changed

    return step


def backfill_radar(
    conn: Conn,
    config: PegelConfig,
    client: httpx.Client,
    start: datetime,
    end: datetime,
    cache_dir: Path,
) -> int:
    """Stores [start, end) month by month: monthly tars before 2025, the recent archive after."""
    changed = 0
    for window_start, window_end in monthly_windows(start, end):
        if window_start < RECENT_ARCHIVE_START:
            month_start = window_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            grids: Iterable[RadolanGrid] = (
                grid
                for grid in historical_month(client, month_start, cache_dir)
                if window_start <= grid.product_time < window_end
            )
        else:
            fetch = partial(fetch_recent, client, cache_dir=cache_dir)
            grids = _published(fetch, product_times(window_start, window_end), "backfill_radar")
        month_changed, hours = store_grids(conn, config, grids, "backfill_radar", None)
        if hours == 0:
            # E.g. DWD moved the year from the recent archive to the monthly tars.
            raise RadolanError(
                f"no radar product found for {window_start:%Y-%m-%d} to {window_end:%Y-%m-%d}"
            )
        logger.info(
            "backfilled radar rain",
            extra={
                "job": "backfill_radar",
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "hours": hours,
                "changed": month_changed,
            },
        )
        changed += month_changed
    return changed


def _published(
    fetch: Callable[[datetime], RadolanGrid | None], times: Iterable[datetime], job: str
) -> Iterator[RadolanGrid]:
    """Fetches each product time; a missing or broken one is a warning and skipped.

    So one bad file can't cost the other hours; a later run or a backfill picks it up.
    """
    for product_time in times:
        context = {"job": job, "valid_at": product_time.isoformat()}
        try:
            grid = fetch(product_time)
        # Decompressors raise OSError, ValueError or EOFError on broken files.
        except (RadolanError, httpx.HTTPError, OSError, ValueError, EOFError) as error:
            logger.warning(
                "radar product unusable, skipping it", extra={**context, "error": str(error)}
            )
            continue
        if grid is None:
            logger.warning("radar product not published", extra=context)
            continue
        yield grid

"""Turns weather model point values into the stored rain forecast series. Pure, no I/O."""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pegel.core.observations import require_utc
from pegel.core.schedule import scheduled_available_at
from pegel.core.series import InputForecastValue, Series

# ICON-D2 starts a run every 3 hours, at 00, 03, ... 21 UTC.
RUN_INTERVAL = timedelta(hours=3)
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class GridPoint:
    lat: float
    lon: float
    in_catchment: bool


@dataclass(frozen=True)
class PointSeries:
    """One variable at every requested point. `values[point][hour]` belongs to `times[hour]`.

    `times` are the ends of the hours, as Open-Meteo stamps hourly sums.
    """

    times: Sequence[datetime]
    values: Sequence[Sequence[float | None]]


class RunMismatchError(Exception):
    """The forecast data doesn't come (only) from the run it was asked for."""


def catchment_series_id(source: str) -> str:
    return f"{source}:catchment:mean"


def ring_series_id(source: str, percentile: int) -> str:
    return f"{source}:ring:p{percentile}"


def forecast_series(source: str, percentile: int, note: str) -> list[Series]:
    """The two stored rain forecast series of one source. `note` says where runs come from."""
    return [
        Series(
            id=catchment_series_id(source),
            variable="rain",
            unit="mm",
            source=source,
            location="catchment",
            kind="forecast",
            aggregation="mean",
            period=HOUR,
            description=f"ICON-D2 rain, mean over the catchment points. {note}",
        ),
        Series(
            id=ring_series_id(source, percentile),
            variable="rain",
            unit="mm",
            source=source,
            location="ring_10km",
            kind="forecast",
            aggregation=f"p{percentile}",
            period=HOUR,
            description=f"ICON-D2 rain, {percentile}th percentile over the ring points. {note}",
        ),
    ]


def aggregate_hour(
    source: str,
    run_at: datetime,
    valid_at: datetime,
    values: Sequence[float],
    points: Sequence[GridPoint],
    percentile: int,
    available_at: datetime,
) -> list[InputForecastValue]:
    """The catchment mean and the ring percentile for one forecast hour."""
    if len(values) != len(points):
        raise ValueError(f"got {len(values)} values for {len(points)} points")
    catchment = [value for value, point in zip(values, points, strict=True) if point.in_catchment]
    if not catchment:
        raise ValueError("no point lies in the catchment")
    # quantiles needs two values; a single-point ring is its own percentile.
    ring = (
        statistics.quantiles(values, n=100, method="inclusive")[percentile - 1]
        if len(values) > 1
        else values[0]
    )
    return [
        InputForecastValue(
            catchment_series_id(source),
            run_at,
            valid_at,
            statistics.fmean(catchment),
            available_at,
        ),
        InputForecastValue(
            ring_series_id(source, percentile), run_at, valid_at, ring, available_at
        ),
    ]


def missing_runs(newest: datetime, stored: datetime | None, look_back: timedelta) -> list[datetime]:
    """The runs from newest - look_back to newest that start after `stored`, oldest first."""
    runs = [newest - RUN_INTERVAL * back for back in range(look_back // RUN_INTERVAL, -1, -1)]
    return [run for run in runs if stored is None or run > stored]


def check_run(series: PointSeries, run_at: datetime, horizon_hours: int) -> None:
    """Checks that every point has data from run_at + 1 h to run_at + horizon and none after.

    A run's data ends exactly at its horizon, so an older run ends earlier and a newer one later.
    This catches a server that still serves the previous run, or already the next one. The
    start check catches a shortened answer, which would otherwise be stored as a whole run.
    """
    last_hour = run_at + timedelta(hours=horizon_hours)
    if last_hour + HOUR not in series.times:
        raise ValueError("ask for at least one hour after the horizon to check the run")
    expected_times = [run_at + HOUR * (hour + 1) for hour in range(len(series.times))]
    if list(series.times) != expected_times:
        raise RunMismatchError(f"hours don't run without a gap from {run_at + HOUR}")
    for point_values in series.values:
        with_data = [
            time
            for time, value in zip(series.times, point_values, strict=True)
            if value is not None
        ]
        if not with_data or with_data[0] != run_at + HOUR:
            starts = with_data[0].isoformat() if with_data else "nowhere"
            raise RunMismatchError(f"data starts {starts}, run {run_at.isoformat()}")
        if with_data[-1] != last_hour:
            ends = with_data[-1].isoformat()
            raise RunMismatchError(f"data ends {ends}, run {run_at.isoformat()} ends {last_hour}")


def run_values(
    source: str,
    series: PointSeries,
    points: Sequence[GridPoint],
    run_at: datetime,
    horizon_hours: int,
    percentile: int,
    available_at: datetime,
) -> list[InputForecastValue]:
    """The series for each hour with run_at < valid_at <= run_at + horizon, all points required.

    `available_at` is the issue slot in which we fetched the run.
    """
    last_hour = run_at + timedelta(hours=horizon_hours)
    result = []
    for hour, valid_at in enumerate(series.times):
        if not run_at < valid_at <= last_hour:
            continue
        values = [point_values[hour] for point_values in series.values]
        if any(value is None for value in values):
            raise RunMismatchError(f"missing values at {valid_at.isoformat()}")
        complete = [v for v in values if v is not None]
        result += aggregate_hour(
            source, run_at, valid_at, complete, points, percentile, available_at
        )
    return result


def archive_run_at(valid_at: datetime, days_before: int) -> datetime:
    """The run an Open-Meteo Previous Runs value comes from (docs/catchment.md).

    `previous_dayN` holds the newest run that started strictly before valid_at - N days, so
    day 0 has lead times of 1 to 3 hours and day 1 of 25 to 27 hours.
    """
    require_utc(valid_at, "valid_at")
    latest_start = valid_at - timedelta(days=days_before) - HOUR
    hours_into_cycle = latest_start.hour % (RUN_INTERVAL // HOUR)
    return latest_start.replace(minute=0, second=0, microsecond=0) - hours_into_cycle * HOUR


def archive_values(
    source: str,
    series: PointSeries,
    points: Sequence[GridPoint],
    days_before: int,
    percentile: int,
    available_after: timedelta,
    issue_minute: int,
) -> list[InputForecastValue]:
    """The series for every hour of one Previous Runs variable. Hours with a gap are skipped.

    Each run counts as available at the first hourly run after run_at + available_after, as
    the live system would have used it.
    """
    result = []
    for hour, valid_at in enumerate(series.times):
        values = [point_values[hour] for point_values in series.values]
        complete = [value for value in values if value is not None]
        if len(complete) < len(values):
            continue
        run_at = archive_run_at(valid_at, days_before)
        available_at = scheduled_available_at(run_at, available_after, issue_minute)
        result += aggregate_hour(
            source, run_at, valid_at, complete, points, percentile, available_at
        )
    return result

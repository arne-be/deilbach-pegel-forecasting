"""Time series and their values: gauge levels, radar rain, soil moisture, rain forecasts."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pegel.config import Station
from pegel.core.observations import require_utc

LEVEL_UNIT = "cm"

# Observations go to the observations table, forecasts by others to input_forecasts.
# The database rejects a value written to a series of the other kind.
SeriesKind = Literal["observation", "forecast"]


@dataclass(frozen=True)
class Series:
    """What a series measures, where and how. Its values refer to it by `id`."""

    # Readable and stable, e.g. 'kupferdreh:level' or 'radolan_rw:zone:neviges'.
    id: str
    variable: str
    unit: str
    source: str
    location: str
    kind: SeriesKind
    # How long after valid_at (observations) or run_at (forecasts) values are reliably there.
    # Training uses only values available at the issue time. Comes from config/pegel.json.
    available_after: timedelta
    # How an area value combines cells or points, e.g. 'mean'. None for one gauge.
    aggregation: str | None = None
    # None for a reading at one moment; otherwise a total over the period ending at valid_at.
    period: timedelta | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("series id must not be empty")
        if self.period is not None and self.period <= timedelta(0):
            raise ValueError(f"period must be positive, got {self.period!r}")
        if self.available_after < timedelta(0):
            raise ValueError(f"available_after must not be negative, got {self.available_after!r}")


@dataclass(frozen=True)
class SeriesValue:
    """One observed value of a series. Negative values are real for levels."""

    series_id: str
    valid_at: datetime
    value: float
    # When the value was first there for us: the fetch time in live runs, the scheduled rule
    # for backfills (core.schedule.scheduled_available_at). Training uses it, not ingested_at.
    available_at: datetime
    # Share of the cells or points behind an area value that had data. None for one gauge.
    coverage: float | None = None

    def __post_init__(self) -> None:
        require_utc(self.valid_at, "valid_at")
        _require_available_after(self.available_at, self.valid_at, "valid_at")
        _require_finite(self.value)
        if self.coverage is not None and not 0 < self.coverage <= 1:
            raise ValueError(f"coverage must be in (0, 1], got {self.coverage!r}")


@dataclass(frozen=True)
class InputForecastValue:
    """One value of a forecast made by others, e.g. ICON-D2 rain, from the run at `run_at`."""

    series_id: str
    run_at: datetime
    valid_at: datetime
    value: float
    # When the run was first there for us, as for SeriesValue.available_at.
    available_at: datetime

    def __post_init__(self) -> None:
        require_utc(self.run_at, "run_at")
        require_utc(self.valid_at, "valid_at")
        _require_available_after(self.available_at, self.run_at, "run_at")
        _require_finite(self.value)
        if self.valid_at <= self.run_at:
            raise ValueError(f"valid_at {self.valid_at} must be after run_at {self.run_at}")


def level_series_id(station_id: str) -> str:
    return f"{station_id}:level"


def level_series(station: Station) -> Series:
    """The water level series of a configured gauge."""
    return Series(
        id=level_series_id(station.id),
        variable="level",
        unit=LEVEL_UNIT,
        source=station.source,
        location=station.id,
        kind="observation",
        available_after=timedelta(minutes=station.available_after_minutes),
        description=f"Water level at {station.name}",
    )


def _require_available_after(available_at: datetime, known_at: datetime, field_name: str) -> None:
    require_utc(available_at, "available_at")
    if available_at < known_at:
        raise ValueError(f"available_at {available_at} must not be before {field_name} {known_at}")


def _require_finite(value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"value must be finite, got {value!r}")

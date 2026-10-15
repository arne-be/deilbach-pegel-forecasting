"""Forecasts, the shared shape between the model, storage and the API."""

from dataclasses import dataclass
from datetime import datetime

from pegel.core.observations import require_utc


@dataclass(frozen=True)
class Band:
    """The observed level should lie between lower_cm and upper_cm in coverage_percent of cases."""

    coverage_percent: int
    lower_cm: float
    upper_cm: float

    def __post_init__(self) -> None:
        if not 0 < self.coverage_percent < 100:
            raise ValueError(f"coverage {self.coverage_percent} % is not between 0 and 100")
        if not self.lower_cm <= self.upper_cm:
            raise ValueError(f"band {self.lower_cm} to {self.upper_cm} cm is upside down")


@dataclass(frozen=True)
class ForecastPoint:
    valid_at: datetime
    level_cm: float
    # Narrowest coverage first; empty where the model has no error history (e.g. persistence).
    bands: tuple[Band, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.valid_at, "valid_at")


@dataclass(frozen=True)
class Forecast:
    """A forecast for one station, with its issue time and the newest observation it used."""

    station_id: str
    model: str
    issued_at: datetime
    newest_observation_at: datetime
    points: tuple[ForecastPoint, ...]
    # The situation that picked the bands, e.g. "dry"; None without bands.
    situation: str | None = None

    def __post_init__(self) -> None:
        require_utc(self.issued_at, "issued_at")
        require_utc(self.newest_observation_at, "newest_observation_at")

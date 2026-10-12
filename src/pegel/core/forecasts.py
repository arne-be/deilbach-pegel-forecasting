"""Forecasts, the shared shape between the model, storage and the API."""

from dataclasses import dataclass
from datetime import datetime

from pegel.core.observations import require_utc


@dataclass(frozen=True)
class ForecastPoint:
    valid_at: datetime
    level_m: float

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

    def __post_init__(self) -> None:
        require_utc(self.issued_at, "issued_at")
        require_utc(self.newest_observation_at, "newest_observation_at")

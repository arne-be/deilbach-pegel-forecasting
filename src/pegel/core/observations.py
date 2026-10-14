"""Observed water levels, the shared shape between sources, storage and the model."""

from dataclasses import dataclass
from datetime import UTC, datetime


def require_utc(value: datetime, field_name: str) -> None:
    if value.utcoffset() is None or value.utcoffset() != UTC.utcoffset(None):
        raise ValueError(f"{field_name} must be timezone-aware UTC, got {value!r}")


@dataclass(frozen=True)
class Observation:
    """One level reading in cm relative to the gauge zero."""

    station_id: str
    observed_at: datetime
    level_cm: float

    def __post_init__(self) -> None:
        require_utc(self.observed_at, "observed_at")

"""Persistence baseline: the newest level stays the same for the whole horizon.

Every real model has to beat this one, so it is reported alongside them.
"""

from datetime import datetime, timedelta

from pegel.core.forecasts import Forecast, ForecastPoint
from pegel.core.observations import Observation

MODEL_NAME = "persistence"


def persistence_forecast(newest: Observation, issued_at: datetime, horizon_hours: int) -> Forecast:
    if issued_at < newest.observed_at:
        raise ValueError(
            f"issued_at {issued_at.isoformat()} is before the newest observation "
            f"{newest.observed_at.isoformat()}"
        )
    if horizon_hours < 1:
        raise ValueError(f"horizon_hours must be at least 1, got {horizon_hours}")
    # Lead times count from the observation, not the issue time, so each point lands on
    # the same minute as a future reading and evaluation can match them exactly.
    points = tuple(
        ForecastPoint(newest.observed_at + timedelta(hours=lead), newest.level_m)
        for lead in range(1, horizon_hours + 1)
    )
    return Forecast(
        station_id=newest.station_id,
        model=MODEL_NAME,
        issued_at=issued_at,
        newest_observation_at=newest.observed_at,
        points=points,
    )

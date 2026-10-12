"""Highest expected level per summary horizon, as shown on the website."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pegel.config import Category
from pegel.core.categories import category_for
from pegel.core.forecasts import Forecast


@dataclass(frozen=True)
class HorizonSummary:
    horizon_hours: int
    max_level_m: float
    valid_at_of_max: datetime
    category: Category


def summarize(
    forecast: Forecast, horizons_hours: Sequence[int], categories: Sequence[Category]
) -> list[HorizonSummary]:
    return [_summarize_horizon(forecast, hours, categories) for hours in horizons_hours]


def _summarize_horizon(
    forecast: Forecast, horizon_hours: int, categories: Sequence[Category]
) -> HorizonSummary:
    # Leads count from the newest observation, the same reference the points were built on.
    end = forecast.newest_observation_at + timedelta(hours=horizon_hours)
    in_horizon = [point for point in forecast.points if point.valid_at <= end]
    if not in_horizon:
        raise ValueError(f"forecast has no points within {horizon_hours} h")
    # max() keeps the first of equal levels, so ties report the earliest time.
    highest = max(in_horizon, key=lambda point: point.level_m)
    return HorizonSummary(
        horizon_hours=horizon_hours,
        max_level_m=highest.level_m,
        valid_at_of_max=highest.valid_at,
        category=category_for(highest.level_m, categories),
    )

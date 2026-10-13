from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from pegel.core.observations import Observation
from pegel.core.persistence import persistence_forecast

OBSERVED_AT = datetime(2026, 10, 12, 12, 22, tzinfo=UTC)
NEWEST = Observation("kupferdreh", OBSERVED_AT, 68.0)


def test_forecast_has_one_point_per_hour_of_horizon() -> None:
    forecast = persistence_forecast(NEWEST, OBSERVED_AT, 48)
    assert len(forecast.points) == 48


def test_points_are_hourly_from_the_observation_time() -> None:
    forecast = persistence_forecast(NEWEST, OBSERVED_AT + timedelta(minutes=5), 48)
    expected = [OBSERVED_AT + timedelta(hours=lead) for lead in range(1, 49)]
    assert [point.valid_at for point in forecast.points] == expected


def test_every_point_carries_the_newest_level() -> None:
    forecast = persistence_forecast(NEWEST, OBSERVED_AT, 48)
    assert {point.level_cm for point in forecast.points} == {68.0}


def test_negative_level_is_forecast_unchanged() -> None:
    newest = Observation("kupferdreh", OBSERVED_AT, -25.0)
    forecast = persistence_forecast(newest, OBSERVED_AT, 48)
    assert {point.level_cm for point in forecast.points} == {-25.0}


def test_forecast_across_dst_change_has_no_gaps_or_duplicates() -> None:
    # Berlin leaves summer time at 2026-10-25 01:00 UTC.
    observed_at = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    newest = Observation("kupferdreh", observed_at, 50.0)
    forecast = persistence_forecast(newest, observed_at, 48)
    valid_times = [point.valid_at for point in forecast.points]
    steps = {later - earlier for earlier, later in pairwise(valid_times)}
    assert steps == {timedelta(hours=1)}


def test_stale_observation_keeps_its_observation_time() -> None:
    issued_at = OBSERVED_AT + timedelta(hours=5)
    forecast = persistence_forecast(NEWEST, issued_at, 48)
    assert forecast.newest_observation_at == OBSERVED_AT


def test_forecast_keeps_its_issue_time() -> None:
    issued_at = OBSERVED_AT + timedelta(minutes=5)
    forecast = persistence_forecast(NEWEST, issued_at, 48)
    assert forecast.issued_at == issued_at


def test_model_is_named_persistence() -> None:
    assert persistence_forecast(NEWEST, OBSERVED_AT, 48).model == "persistence"


def test_issue_time_before_observation_is_rejected() -> None:
    with pytest.raises(ValueError, match="before the newest observation"):
        persistence_forecast(NEWEST, OBSERVED_AT - timedelta(minutes=1), 48)


def test_horizon_below_one_hour_is_rejected() -> None:
    with pytest.raises(ValueError, match="horizon_hours"):
        persistence_forecast(NEWEST, OBSERVED_AT, 0)

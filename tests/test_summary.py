from datetime import UTC, datetime, timedelta

import pytest

from pegel.config import load_config
from pegel.core.forecasts import Forecast, ForecastPoint
from pegel.core.summary import HorizonSummary, summarize

CATEGORIES = load_config().categories
OBSERVED_AT = datetime(2026, 10, 12, 12, 22, tzinfo=UTC)


def _forecast(levels_by_lead: dict[int, float]) -> Forecast:
    points = tuple(
        ForecastPoint(OBSERVED_AT + timedelta(hours=lead), level)
        for lead, level in sorted(levels_by_lead.items())
    )
    return Forecast("kupferdreh", "test", OBSERVED_AT, OBSERVED_AT, points)


# Rising to a peak of 195 cm at lead 20, then falling back.
FORECAST = _forecast(
    {1: 105.0, 2: 115.0, 3: 135.0, 4: 155.0, 20: 195.0, 24: 175.0, 30: 235.0, 48: 125.0}
)


def _summary_for(hours: int) -> HorizonSummary:
    return summarize(FORECAST, [hours], CATEGORIES)[0]


def test_short_horizon_ignores_later_higher_points() -> None:
    assert _summary_for(3).max_level_cm == 135.0


def test_horizon_includes_the_point_at_its_end() -> None:
    forecast = _forecast({1: 50.0, 3: 110.0, 4: 160.0})
    assert summarize(forecast, [3], CATEGORIES)[0].max_level_cm == 110.0


def test_summary_reports_when_the_max_is_reached() -> None:
    assert _summary_for(24).valid_at_of_max == OBSERVED_AT + timedelta(hours=20)


def test_summary_category_matches_the_max_level() -> None:
    assert _summary_for(24).category.number == 4


def test_longest_horizon_finds_the_overall_peak() -> None:
    assert _summary_for(48).max_level_cm == 235.0


def test_one_summary_per_horizon_in_the_given_order() -> None:
    summaries = summarize(FORECAST, [3, 24, 48], CATEGORIES)
    assert [summary.horizon_hours for summary in summaries] == [3, 24, 48]


def test_equal_levels_report_the_earliest_time() -> None:
    forecast = _forecast({1: 100.0, 2: 100.0})
    summary = summarize(forecast, [3], CATEGORIES)[0]
    assert summary.valid_at_of_max == OBSERVED_AT + timedelta(hours=1)


def test_lead_counts_from_the_newest_observation_not_the_issue_time() -> None:
    late_issue = Forecast(
        "kupferdreh", "test", OBSERVED_AT + timedelta(hours=2), OBSERVED_AT, FORECAST.points
    )
    assert summarize(late_issue, [3], CATEGORIES)[0].max_level_cm == 135.0


def test_horizon_without_points_is_rejected() -> None:
    forecast = _forecast({5: 50.0})
    with pytest.raises(ValueError, match="no points"):
        summarize(forecast, [3], CATEGORIES)

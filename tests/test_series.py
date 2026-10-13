import math
from datetime import UTC, datetime, timedelta

import pytest

from pegel.config import load_config
from pegel.core.series import InputForecastValue, Series, SeriesValue, level_series

AT = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_level_series_of_a_station() -> None:
    series = level_series(load_config().station("langenberg"))
    assert (series.id, series.variable, series.source, series.location, series.period) == (
        "langenberg:level",
        "level",
        "lanuv",
        "langenberg",
        None,
    )
    assert series.kind == "observation"


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_value_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        SeriesValue("kupferdreh:level", AT, value, AT)


def test_negative_value_is_allowed() -> None:
    assert SeriesValue("kupferdreh:level", AT, -0.3, AT).value == -0.3


@pytest.mark.parametrize("coverage", [0.0, 1.01, -0.5])
def test_coverage_must_be_a_share(coverage: float) -> None:
    with pytest.raises(ValueError, match="coverage"):
        SeriesValue("zone:rain", AT, 1.0, AT, coverage)


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="UTC"):
        SeriesValue("kupferdreh:level", datetime(2026, 10, 12), 0.1, AT)  # noqa: DTZ001


def test_forecast_value_must_be_after_its_run() -> None:
    with pytest.raises(ValueError, match="after run_at"):
        InputForecastValue("icon_d2:rain", AT, AT, 0.1, AT)


def test_value_cannot_be_available_before_its_time() -> None:
    with pytest.raises(ValueError, match="available_at"):
        SeriesValue("kupferdreh:level", AT, 0.1, AT - timedelta(seconds=1))


def test_forecast_cannot_be_available_before_its_run() -> None:
    with pytest.raises(ValueError, match="available_at"):
        InputForecastValue(
            "icon_d2:rain", AT, AT + timedelta(hours=1), 0.1, AT - timedelta(seconds=1)
        )


def test_period_must_be_positive() -> None:
    with pytest.raises(ValueError, match="period"):
        Series("x", "rain", "mm", "radar", "zone", "observation", period=timedelta(0))

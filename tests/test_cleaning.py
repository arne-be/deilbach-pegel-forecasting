from datetime import UTC, datetime, timedelta

from pegel.config import load_config
from pegel.core.cleaning import outlier_flags
from pegel.core.series import SeriesValue

SETTINGS = load_config().cleaning
START = datetime(2026, 9, 1, 0, 22, tzinfo=UTC)
STEADY = [-26.0] * 6


def hourly(levels: list[float], start: datetime = START) -> list[SeriesValue]:
    times = [start + timedelta(hours=hour) for hour in range(len(levels))]
    return [
        SeriesValue("kupferdreh:level", time, level, time)
        for time, level in zip(times, levels, strict=True)
    ]


def flagged(levels: list[float]) -> list[float]:
    values = hourly(levels)
    return [
        v.value for v, flag in zip(values, outlier_flags(values, SETTINGS), strict=True) if flag
    ]


def test_single_spike_is_flagged() -> None:
    assert flagged([*STEADY, 30.0, -26.0, -25.0]) == [30.0]


def test_back_to_back_spikes_are_flagged() -> None:
    assert flagged([*STEADY, 51.0, 52.0, -26.0, -26.0]) == [51.0, 52.0]


def test_stuck_error_value_is_flagged_for_hours() -> None:
    assert flagged([*[20.0] * 6, *[298.0] * 13, 21.0, 22.0]) == [298.0] * 13


def test_fast_real_rise_is_kept() -> None:
    rise = [20.0 + 28.0 * hour for hour in range(6)]
    assert flagged([*[20.0] * 10, *rise, *[160.0] * 8]) == []


def test_true_level_after_a_spike_that_passed_is_kept() -> None:
    # -24 -> 1 cm looks like the start of a real rise, so the spike passes; the drop
    # straight back to -24 cm must then not be rejected.
    assert flagged([*[-24.0] * 6, 1.0, -24.0, -24.0, -23.0]) == []


def test_filter_restarts_after_a_long_gap() -> None:
    before = hourly([*STEADY])
    after = hourly([60.0, 61.0], start=before[-1].valid_at + timedelta(hours=17))
    assert outlier_flags([*before, *after], SETTINGS) == [False] * 8


def test_negative_levels_are_kept() -> None:
    assert flagged([-26.0, -27.0, -28.0, -27.5, -30.0]) == []


def test_flags_never_change_with_later_readings() -> None:
    values = hourly([*STEADY, 30.0, -26.0, 298.0, 298.0, -25.0, 10.0, 40.0, 60.0, -26.0])
    full = outlier_flags(values, SETTINGS)
    prefixes = [outlier_flags(values[:end], SETTINGS) for end in range(1, len(values))]
    assert all(prefix == full[: len(prefix)] for prefix in prefixes)

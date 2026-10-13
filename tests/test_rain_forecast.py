from datetime import UTC, datetime, timedelta

import pytest

from pegel.core.rain_forecast import (
    GridPoint,
    PointSeries,
    RunMismatchError,
    aggregate_hour,
    archive_run_at,
    archive_values,
    check_run,
    run_values,
)

SOURCE = "open_meteo_icon_d2"
RUN_AT = datetime(2026, 10, 13, 9, tzinfo=UTC)
HOUR = timedelta(hours=1)
POINTS = [GridPoint(51.3, 7.1, True), GridPoint(51.3, 7.14, True), GridPoint(51.22, 7.02, False)]


def hours_after_run(count: int) -> list[datetime]:
    return [RUN_AT + (hour + 1) * HOUR for hour in range(count)]


def test_aggregate_hour_means_catchment_and_takes_ring_percentile() -> None:
    catchment, ring = aggregate_hour(SOURCE, RUN_AT, RUN_AT + HOUR, [1.0, 3.0, 10.0], POINTS, 90)
    assert (catchment.series_id, catchment.value) == ("open_meteo_icon_d2:catchment:mean", 2.0)
    # Inclusive method on [1, 3, 10]: 3 + 0.8 * (10 - 3).
    assert ring.series_id == "open_meteo_icon_d2:ring:p90"
    assert ring.value == pytest.approx(8.6)


def test_ring_percentile_over_many_points() -> None:
    points = [GridPoint(0, 0, True)] + [GridPoint(0, 0, False)] * 100
    values = [float(value) for value in range(101)]
    _, ring = aggregate_hour(SOURCE, RUN_AT, RUN_AT + HOUR, values, points, 90)
    assert ring.value == pytest.approx(90.0)


def test_aggregate_hour_needs_a_catchment_point() -> None:
    with pytest.raises(ValueError):
        aggregate_hour(SOURCE, RUN_AT, RUN_AT + HOUR, [1.0], [GridPoint(0, 0, False)], 90)


def test_run_values_keeps_only_hours_of_the_run() -> None:
    times = [RUN_AT - HOUR, RUN_AT, *hours_after_run(4)]
    series = PointSeries(times, [[9.0, 9.0, 1.0, 2.0, 3.0, 9.0]] * 3)
    values = run_values(SOURCE, series, POINTS, RUN_AT, 3, 90)
    catchment = [value for value in values if value.series_id.endswith(":catchment:mean")]
    assert [value.valid_at for value in catchment] == hours_after_run(3)
    assert [value.value for value in catchment] == [1.0, 2.0, 3.0]
    assert {value.run_at for value in values} == {RUN_AT}


def test_run_values_rejects_a_gap_inside_the_horizon() -> None:
    series = PointSeries(hours_after_run(3), [[1.0, None, 1.0]] * 3)
    with pytest.raises(RunMismatchError):
        run_values(SOURCE, series, POINTS, RUN_AT, 3, 90)


def test_check_run_accepts_data_ending_at_the_horizon() -> None:
    check_run(PointSeries(hours_after_run(4), [[0.0, 0.0, 0.0, None]] * 3), RUN_AT, 3)


@pytest.mark.parametrize(
    "point_values",
    [
        [0.0, 0.0, None, None],  # still the previous run, which ends earlier
        [0.0, 0.0, 0.0, 0.0],  # already the next run, which ends later
        [None, None, None, None],
    ],
)
def test_check_run_rejects_data_from_another_run(point_values: list[float | None]) -> None:
    series = PointSeries(hours_after_run(4), [[0.0, 0.0, 0.0, None], point_values, [0.0] * 3])
    with pytest.raises(RunMismatchError):
        check_run(series, RUN_AT, 3)


def test_check_run_rejects_a_shortened_answer() -> None:
    series = PointSeries(hours_after_run(5)[1:], [[0.0, 0.0, None, None]] * 3)
    with pytest.raises(RunMismatchError):
        check_run(series, RUN_AT, 3)


def test_check_run_rejects_a_gap_in_hours() -> None:
    times = [*hours_after_run(1), *hours_after_run(5)[2:]]
    with pytest.raises(RunMismatchError):
        check_run(PointSeries(times, [[0.0, 0.0, 0.0, None]] * 3), RUN_AT, 3)


def test_check_run_rejects_a_point_starting_late() -> None:
    series = PointSeries(hours_after_run(4), [[0.0, 0.0, 0.0, None], [None, 0.0, 0.0, None]])
    with pytest.raises(RunMismatchError, match="starts"):
        check_run(series, RUN_AT, 3)


def test_check_run_needs_the_hour_after_the_horizon() -> None:
    with pytest.raises(ValueError):
        check_run(PointSeries(hours_after_run(3), [[0.0] * 3] * 3), RUN_AT, 3)


@pytest.mark.parametrize(
    ("valid_hour", "days_before", "run_at"),
    [
        (7, 0, datetime(2026, 10, 1, 6, tzinfo=UTC)),  # lead 1 h
        (9, 0, datetime(2026, 10, 1, 6, tzinfo=UTC)),  # lead 3 h
        (6, 0, datetime(2026, 10, 1, 3, tzinfo=UTC)),
        (0, 0, datetime(2026, 9, 30, 21, tzinfo=UTC)),
        (7, 1, datetime(2026, 9, 30, 6, tzinfo=UTC)),  # lead 25 h
        (6, 1, datetime(2026, 9, 30, 3, tzinfo=UTC)),  # lead 27 h
    ],
)
def test_archive_run_at(valid_hour: int, days_before: int, run_at: datetime) -> None:
    valid_at = datetime(2026, 10, 1, valid_hour, tzinfo=UTC)
    assert archive_run_at(valid_at, days_before) == run_at


def test_archive_values_skip_hours_with_a_gap() -> None:
    times = hours_after_run(2)
    series = PointSeries(times, [[1.0, None], [2.0, 2.0], [0.0, 0.0]])
    values = archive_values("open_meteo_previous_runs", series, POINTS, 1, 90)
    assert {value.valid_at for value in values} == {times[0]}
    assert all(value.valid_at - value.run_at > timedelta(hours=24) for value in values)

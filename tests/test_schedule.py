from datetime import UTC, datetime, timedelta

import pytest

from pegel.core.schedule import issue_time, monthly_windows, scheduled_available_at


def at(month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def test_run_on_schedule_issues_at_its_own_minute() -> None:
    assert issue_time(at(10, 12, 13, 30), issue_minute=30) == at(10, 12, 13, 30)


def test_late_run_keeps_the_scheduled_issue_time() -> None:
    assert issue_time(at(10, 12, 13, 59), issue_minute=30) == at(10, 12, 13, 30)


def test_run_before_the_minute_belongs_to_the_previous_hour() -> None:
    assert issue_time(at(10, 12, 13, 10), issue_minute=30) == at(10, 12, 12, 30)


def test_run_just_after_midnight_belongs_to_the_previous_day() -> None:
    assert issue_time(at(10, 12, 0, 5), issue_minute=30) == at(10, 11, 23, 30)


def test_monthly_windows_split_at_month_starts() -> None:
    assert monthly_windows(at(1, 15), at(3, 10)) == [
        (at(1, 15), at(2, 1)),
        (at(2, 1), at(3, 1)),
        (at(3, 1), at(3, 10)),
    ]


def test_monthly_windows_cross_the_year_end() -> None:
    start = datetime(2025, 12, 20, tzinfo=UTC)
    assert monthly_windows(start, at(1, 5)) == [
        (start, at(1, 1)),
        (at(1, 1), at(1, 5)),
    ]


def test_empty_range_has_no_windows() -> None:
    assert monthly_windows(at(1, 1), at(1, 1)) == []


ISSUE_MINUTE = 30


@pytest.mark.parametrize(
    ("known_at", "available_after", "expected"),
    [
        # Ready exactly at the run: that run uses it.
        (datetime(2026, 10, 12, 13, 10, tzinfo=UTC), timedelta(minutes=20), (13, 30)),
        # A microsecond late waits a whole hour.
        (
            datetime(2026, 10, 12, 13, 10, 0, 1, tzinfo=UTC),
            timedelta(minutes=20),
            (14, 30),
        ),
        (datetime(2026, 10, 12, 13, 29, 59, tzinfo=UTC), timedelta(0), (13, 30)),
        (datetime(2026, 10, 12, 13, 50, tzinfo=UTC), timedelta(minutes=35), (14, 30)),
        (datetime(2026, 10, 12, 13, 0, tzinfo=UTC), timedelta(minutes=90), (14, 30)),
    ],
)
def test_scheduled_available_at_is_the_first_run_after_the_delay(
    known_at: datetime, available_after: timedelta, expected: tuple[int, int]
) -> None:
    result = scheduled_available_at(known_at, available_after, ISSUE_MINUTE)
    assert (result.hour, result.minute, result.second, result.microsecond) == (*expected, 0, 0)


def test_scheduled_available_at_crosses_midnight_into_the_next_day() -> None:
    result = scheduled_available_at(
        datetime(2026, 10, 12, 23, 40, tzinfo=UTC), timedelta(minutes=5), ISSUE_MINUTE
    )
    assert result == datetime(2026, 10, 13, 0, 30, tzinfo=UTC)


def test_scheduled_available_at_rejects_naive_times() -> None:
    with pytest.raises(ValueError, match="UTC"):
        scheduled_available_at(datetime(2026, 10, 12), timedelta(0), ISSUE_MINUTE)  # noqa: DTZ001

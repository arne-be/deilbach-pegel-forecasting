from datetime import UTC, datetime

from pegel.core.schedule import issue_time, monthly_windows


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

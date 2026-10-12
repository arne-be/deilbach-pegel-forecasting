from datetime import UTC, date, datetime

import pytest

from pegel.core.history import history_days, utc_window

TODAY = date(2026, 10, 12)


def test_no_range_gives_the_default_days_up_to_today() -> None:
    assert history_days(None, None, TODAY, 7, 31) == (date(2026, 10, 6), TODAY)


def test_only_to_counts_the_default_days_back_from_it() -> None:
    assert history_days(None, date(2026, 9, 30), TODAY, 7, 31) == (
        date(2026, 9, 24),
        date(2026, 9, 30),
    )


def test_one_day_is_allowed() -> None:
    assert history_days(TODAY, TODAY, TODAY, 7, 31) == (TODAY, TODAY)


def test_max_days_is_allowed_and_one_more_is_not() -> None:
    assert history_days(date(2026, 9, 12), TODAY, TODAY, 7, 31)[0] == date(2026, 9, 12)
    with pytest.raises(ValueError, match="31 days"):
        history_days(date(2026, 9, 11), TODAY, TODAY, 7, 31)


@pytest.mark.parametrize(
    ("first_day", "last_day", "message"),
    [
        (date(2026, 10, 5), date(2026, 10, 4), "'from' must not be after 'to'"),
        (TODAY, date(2026, 10, 13), "'to' must not be after today"),
        (date(2026, 1, 1), None, "31 days"),
    ],
)
def test_bad_ranges_are_rejected(first_day: date, last_day: date | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        history_days(first_day, last_day, TODAY, 7, 31)


def test_window_follows_berlin_midnights() -> None:
    assert utc_window(date(2026, 10, 12), date(2026, 10, 12)) == (
        datetime(2026, 10, 11, 22, tzinfo=UTC),
        datetime(2026, 10, 12, 22, tzinfo=UTC),
    )


def test_window_over_the_autumn_clock_change_has_25_hours() -> None:
    start, end = utc_window(date(2026, 10, 25), date(2026, 10, 25))
    assert (start, end) == (
        datetime(2026, 10, 24, 22, tzinfo=UTC),
        datetime(2026, 10, 25, 23, tzinfo=UTC),
    )

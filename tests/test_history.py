from datetime import UTC, date, datetime

import pytest

from pegel.config import ApiSettings
from pegel.core.history import history_days, utc_window

TODAY = date(2026, 10, 12)
FIRST_DAY_WITH_DATA = date(2023, 3, 6)
SETTINGS = ApiSettings(
    history_first_day=FIRST_DAY_WITH_DATA, history_default_days=7, history_max_days=31
)


def test_no_range_gives_the_default_days_up_to_today() -> None:
    assert history_days(None, None, TODAY, SETTINGS) == (date(2026, 10, 6), TODAY)


def test_only_to_counts_the_default_days_back_from_it() -> None:
    assert history_days(None, date(2026, 9, 30), TODAY, SETTINGS) == (
        date(2026, 9, 24),
        date(2026, 9, 30),
    )


def test_default_range_starts_no_earlier_than_the_first_day_with_data() -> None:
    assert history_days(None, date(2023, 3, 8), TODAY, SETTINGS) == (
        FIRST_DAY_WITH_DATA,
        date(2023, 3, 8),
    )


def test_one_day_is_allowed() -> None:
    assert history_days(TODAY, TODAY, TODAY, SETTINGS) == (TODAY, TODAY)


def test_max_days_is_allowed_and_one_more_is_not() -> None:
    assert history_days(date(2026, 9, 12), TODAY, TODAY, SETTINGS)[0] == date(2026, 9, 12)
    with pytest.raises(ValueError, match="31 days"):
        history_days(date(2026, 9, 11), TODAY, TODAY, SETTINGS)


@pytest.mark.parametrize(
    ("first_day", "last_day", "message"),
    [
        (date(2026, 10, 5), date(2026, 10, 4), "'from' must not be after 'to'"),
        (TODAY, date(2026, 10, 13), "'to' must not be after today"),
        (date(2026, 1, 1), None, "31 days"),
        (date(2023, 3, 5), date(2023, 3, 10), "'from' must not be before 2023-03-06"),
        (None, date(2023, 3, 5), "'to' must not be before 2023-03-06"),
        (date(1, 1, 1), date(1, 1, 2), "'to' must not be before"),
        (None, date(1, 1, 1), "'to' must not be before"),
    ],
)
def test_bad_ranges_are_rejected(
    first_day: date | None, last_day: date | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        history_days(first_day, last_day, TODAY, SETTINGS)


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

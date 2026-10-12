"""Day ranges for the history API. Pure: today is passed in."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pegel.config import ApiSettings

# Days are calendar days as shown on the page, not UTC days.
DISPLAY_TIME_ZONE = ZoneInfo("Europe/Berlin")


def history_days(
    first_day: date | None, last_day: date | None, today: date, settings: ApiSettings
) -> tuple[date, date]:
    """The requested days, both included. Without a range, the default days up to today.

    Raises ValueError for a range that is reversed, outside the days with data or too long.
    """
    earliest_day = settings.history_first_day
    last_day = last_day or today
    if last_day > today:
        raise ValueError("'to' must not be after today")
    # Checked before any date arithmetic, which overflows near year 1.
    if last_day < earliest_day:
        raise ValueError(f"'to' must not be before {earliest_day}")
    default_first_day = last_day - timedelta(days=settings.history_default_days - 1)
    first_day = first_day or max(default_first_day, earliest_day)
    if first_day < earliest_day:
        raise ValueError(f"'from' must not be before {earliest_day}")
    if first_day > last_day:
        raise ValueError("'from' must not be after 'to'")
    if (last_day - first_day).days + 1 > settings.history_max_days:
        raise ValueError(f"at most {settings.history_max_days} days per request")
    return first_day, last_day


def utc_window(first_day: date, last_day: date) -> tuple[datetime, datetime]:
    """[midnight before first_day, midnight after last_day) in Europe/Berlin, as UTC."""
    start = datetime.combine(first_day, time(), DISPLAY_TIME_ZONE)
    end = datetime.combine(last_day + timedelta(days=1), time(), DISPLAY_TIME_ZONE)
    return start.astimezone(UTC), end.astimezone(UTC)

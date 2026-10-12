"""Day ranges for the history API. Pure: today is passed in."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Days are calendar days as shown on the page, not UTC days.
DISPLAY_TIME_ZONE = ZoneInfo("Europe/Berlin")


def history_days(
    first_day: date | None,
    last_day: date | None,
    today: date,
    default_days: int,
    max_days: int,
) -> tuple[date, date]:
    """The requested days, both included. Without a range, the last `default_days` up to today.

    Raises ValueError for a range that is reversed, reaches past today or is too long.
    """
    last_day = last_day or today
    first_day = first_day or last_day - timedelta(days=default_days - 1)
    if last_day > today:
        raise ValueError("'to' must not be after today")
    if first_day > last_day:
        raise ValueError("'from' must not be after 'to'")
    if (last_day - first_day).days + 1 > max_days:
        raise ValueError(f"at most {max_days} days per request")
    return first_day, last_day


def utc_window(first_day: date, last_day: date) -> tuple[datetime, datetime]:
    """[midnight before first_day, midnight after last_day) in Europe/Berlin, as UTC."""
    start = datetime.combine(first_day, time(), DISPLAY_TIME_ZONE)
    end = datetime.combine(last_day + timedelta(days=1), time(), DISPLAY_TIME_ZONE)
    return start.astimezone(UTC), end.astimezone(UTC)

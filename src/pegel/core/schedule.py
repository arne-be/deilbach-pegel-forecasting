"""Issue times and time windows for the jobs. Pure: the current time is passed in."""

from datetime import datetime, timedelta

from pegel.core.observations import require_utc


def issue_time(now: datetime, issue_minute: int) -> datetime:
    """The latest scheduled issue time (hh:issue_minute UTC) at or before `now`.

    A late or repeated run gets the same issue time as the scheduled one, so it overwrites
    that forecast instead of adding a new one.
    """
    require_utc(now, "now")
    candidate = now.replace(minute=issue_minute, second=0, microsecond=0)
    return candidate if candidate <= now else candidate - timedelta(hours=1)


def monthly_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Splits [start, end) into windows that end at the start of each calendar month (UTC)."""
    require_utc(start, "start")
    require_utc(end, "end")
    windows = []
    window_start = start
    while window_start < end:
        window_end = min(_start_of_next_month(window_start), end)
        windows.append((window_start, window_end))
        window_start = window_end
    return windows


def _start_of_next_month(moment: datetime) -> datetime:
    first_of_month = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (first_of_month + timedelta(days=32)).replace(day=1)

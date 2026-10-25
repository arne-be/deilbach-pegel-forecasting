"""Reads ICON-D2 rain forecasts from Open-Meteo: single runs, the run metadata and the archive.

Open-Meteo's free tier is for non-commercial use, data CC BY 4.0 (DWD via Open-Meteo).
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx

from pegel.core.rain_forecast import GridPoint, PointSeries

logger = logging.getLogger(__name__)

# Any run of the last months by its start time, from about May 2026 on.
SINGLE_RUNS_URL = "https://single-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
# The newest ICON-D2 run Open-Meteo serves. A small static file, not a forecast request.
META_URL = "https://api.open-meteo.com/data/dwd_icon_d2/static/meta.json"
MODEL = "icon_d2"
# Backfill requests: 70 points over 14 days can take a while, and retries are cheap there.
ARCHIVE_TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
# Live requests get a second try after a short wait: from Lambda, single requests timed out or got
# a 503 (2026-10-13). A request for a new run once took over 15 s. The Lambda has 900 s, so even a
# few runs at 2 x 60 s leave room for the level forecast.
LIVE_TIMEOUT_SECONDS = 60.0
LIVE_ATTEMPTS = 2
BACKOFF_BASE_SECONDS = 5.0


class OpenMeteoError(Exception):
    """Open-Meteo could not be read or answered with something we cannot trust."""


class RateLimitedError(OpenMeteoError):
    """Open-Meteo answered HTTP 429: the minute, hour or day limit is used up."""


def load_points(path: Path) -> list[GridPoint]:
    """The grid points to fetch, as written by scripts/build_catchment.py."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [GridPoint(p["lat"], p["lon"], p["in_catchment"]) for p in data["points"]]


def request_weight(points: int, days: int, variables: int) -> float:
    """Open-Meteo's count of API calls for one request, from its terms."""
    return points * max(1.0, days / 14) * max(1.0, variables / 10)


def latest_run(client: httpx.Client) -> datetime:
    """Start time of the newest ICON-D2 run Open-Meteo has finished loading."""
    meta = _get_json(client, META_URL, {}, LIVE_ATTEMPTS, LIVE_TIMEOUT_SECONDS)
    seconds = meta.get("last_run_initialisation_time") if isinstance(meta, dict) else None
    if not isinstance(seconds, int):
        raise OpenMeteoError("metadata has no last_run_initialisation_time")
    return datetime.fromtimestamp(seconds, UTC)


def fetch_run(
    client: httpx.Client,
    points: Sequence[GridPoint],
    run_at: datetime,
    hours: int,
) -> PointSeries:
    """Hourly precipitation of the run starting at run_at, for the hours ending run_at + 1 h ...
    run_at + hours, at every point. For the hourly job.
    """
    # Single Runs refuses start_hour; its answer starts at run_at.
    params = _params(points, "precipitation") | {
        "run": _hour_text(run_at),
        "forecast_hours": str(hours + 1),
    }
    body = _get_json(client, SINGLE_RUNS_URL, params, LIVE_ATTEMPTS, LIVE_TIMEOUT_SECONDS)
    series = parse_points(body, points, ["precipitation"])["precipitation"]
    # The hour ending at run_at has no rain sum in this run.
    return PointSeries(series.times[1:], [values[1:] for values in series.values])


def fetch_archive(
    client: httpx.Client,
    points: Sequence[GridPoint],
    variables: Sequence[str],
    first_day: date,
    last_day: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, PointSeries]:
    """Previous Runs values for the UTC days first_day ... last_day (both included)."""
    params = _params(points, ",".join(variables)) | {
        "start_date": first_day.isoformat(),
        "end_date": last_day.isoformat(),
    }
    body = _get_json(
        client, ARCHIVE_URL, params, MAX_ATTEMPTS, ARCHIVE_TIMEOUT_SECONDS, sleep=sleep
    )
    return parse_points(body, points, variables)


def parse_points(
    body: Any, points: Sequence[GridPoint], variables: Sequence[str]
) -> dict[str, PointSeries]:
    """Checks a multi-location answer has one location per requested point and reads each variable.

    Open-Meteo snaps each point to its own grid cell, so the returned coordinates may differ.
    """
    locations = [body] if isinstance(body, dict) else body
    if not isinstance(locations, list) or len(locations) != len(points):
        raise OpenMeteoError(f"expected {len(points)} locations")
    times: list[datetime] | None = None
    values: dict[str, list[list[float | None]]] = {variable: [] for variable in variables}
    for location in locations:
        hourly = _check_location(location, variables)
        location_times = _parse_times(hourly["time"])
        if times is None:
            times = location_times
        elif location_times != times:
            raise OpenMeteoError("locations have different hours")
        for variable in variables:
            values[variable].append(_parse_values(hourly[variable], len(location_times)))
    if times is None:
        raise OpenMeteoError("no locations")
    return {variable: PointSeries(times, values[variable]) for variable in variables}


def _check_location(location: Any, variables: Sequence[str]) -> dict[str, Any]:
    if not isinstance(location, dict):
        raise OpenMeteoError("location is not an object")
    if location.get("utc_offset_seconds") != 0:
        raise OpenMeteoError("answer is not in UTC")
    hourly, units = location.get("hourly"), location.get("hourly_units")
    if not isinstance(hourly, dict) or not isinstance(units, dict) or "time" not in hourly:
        raise OpenMeteoError("location has no hourly data")
    for variable in variables:
        if units.get(variable) != "mm" or variable not in hourly:
            raise OpenMeteoError(f"{variable} missing or not in mm")
    return hourly


def _parse_times(texts: Any) -> list[datetime]:
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise OpenMeteoError("hourly times are not a list of strings")
    try:
        times = [datetime.fromisoformat(text).replace(tzinfo=UTC) for text in texts]
    except ValueError:
        raise OpenMeteoError("bad hourly time") from None
    steps = {(later - earlier).total_seconds() for earlier, later in pairwise(times)}
    if steps - {3600.0}:
        raise OpenMeteoError("hourly times are not one hour apart")
    return times


def _parse_values(raw: Any, length: int) -> list[float | None]:
    if not isinstance(raw, list) or len(raw) != length:
        raise OpenMeteoError("values don't match the hours")
    for value in raw:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float) or value < 0
        ):
            raise OpenMeteoError(f"bad rain value {value!r}")
    return [None if value is None else float(value) for value in raw]


def _params(points: Sequence[GridPoint], hourly: str) -> dict[str, str]:
    return {
        "latitude": ",".join(str(point.lat) for point in points),
        "longitude": ",".join(str(point.lon) for point in points),
        "hourly": hourly,
        "models": MODEL,
        "timezone": "UTC",
        # Its default picks a neighbour with a better-matching elevation.
        "cell_selection": "nearest",
    }


def _hour_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def _get_json(
    client: httpx.Client,
    url: str,
    params: dict[str, str],
    attempts: int,
    timeout: float,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """GET with `timeout` as the whole time per attempt, including a slowly trickling body.

    Network errors and 5xx are retried with backoff up to `attempts`; 429 and other 4xx raise
    at once.
    """
    for attempt in range(1, attempts + 1):
        try:
            status, body = _get_within(client, url, params, timeout)
        except httpx.TransportError as error:
            failure = f"network error ({type(error).__name__})"
        else:
            if status == 429:
                raise RateLimitedError(f"rate limited: {_reason(body)}")
            if status < 400:
                try:
                    return json.loads(body)
                except ValueError:
                    raise OpenMeteoError("response body is not JSON") from None
            if status < 500:
                raise OpenMeteoError(f"HTTP {status}: {_reason(body)}")
            failure = f"HTTP {status}"
        if attempt == attempts:
            raise OpenMeteoError(f"unreachable after {attempts} attempt(s): {failure}")
        delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        logger.warning(
            "open-meteo request failed, retrying",
            extra={"attempt": attempt, "failure": failure, "retry_in_s": delay},
        )
        sleep(delay)
    raise AssertionError("unreachable")


def _get_within(
    client: httpx.Client, url: str, params: dict[str, str], timeout: float
) -> tuple[int, bytes]:
    """Status and body, or ReadTimeout once `timeout` has passed. httpx times each phase alone."""
    deadline = time.monotonic() + timeout
    with client.stream("GET", url, params=params, timeout=timeout) as response:
        chunks = []
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise httpx.ReadTimeout(f"no complete answer within {timeout} s")
            chunks.append(chunk)
        return response.status_code, b"".join(chunks)


def _reason(body: bytes) -> str:
    """Open-Meteo explains errors as {"error": true, "reason": "..."}."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return "no reason given"
    return str(parsed.get("reason")) if isinstance(parsed, dict) else "no reason given"

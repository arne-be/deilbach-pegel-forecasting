"""Reads water levels published by LANUV NRW (live portal and open data files)."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from pegel.config import Station
from pegel.core.observations import Observation, require_utc

logger = logging.getLogger(__name__)

# The public portal's last seven days of 5-minute readings. Public data, no credentials.
WEEK_URL = "https://www.hochwasserportal.nrw/data/internet/stations/100/{station_no}/S/week.json"
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0

# LANUV marks gaps with "NA" in its CSV files and with null in its JSON files.
_MISSING_VALUES = (None, "NA", "")


class LanuvError(Exception):
    """The portal could not be read or answered with something we cannot trust."""


def parse_lanuv_value(
    station_id: str, timestamp_text: str, value: str | float | None
) -> Observation | None:
    """One LANUV reading as an observation in metres and UTC, or None for a gap.

    LANUV timestamps carry a fixed +01:00 offset all year, and values are centimetres.
    """
    observed_at = datetime.fromisoformat(timestamp_text)
    if observed_at.utcoffset() is None:
        raise ValueError(f"LANUV timestamp without offset: {timestamp_text!r}")
    if value in _MISSING_VALUES:
        return None
    return Observation(
        station_id=station_id,
        observed_at=observed_at.astimezone(UTC),
        level_m=float(value) / 100,
    )


def parse_week(response_json: Any, station: Station) -> list[Observation]:
    """Turns a week.json answer into observations, skipping gaps. Rejects anything unexpected."""
    if not isinstance(response_json, list) or len(response_json) != 1:
        raise LanuvError("expected a list with exactly one time series")
    series = response_json[0]
    if not isinstance(series, dict):
        raise LanuvError("time series is not an object")
    if series.get("station_no") != station.source_label:
        raise LanuvError(f"answer is for station {series.get('station_no')!r}")
    if series.get("ts_unitsymbol") != "cm":
        raise LanuvError(f"unexpected unit {series.get('ts_unitsymbol')!r}")
    rows = series.get("data")
    if not isinstance(rows, list):
        raise LanuvError("data is not a list")
    observations = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str):
            raise LanuvError(f"malformed row: {row!r}")
        if row[1] is not None and (not isinstance(row[1], int | float) or isinstance(row[1], bool)):
            raise LanuvError(f"level is not a number: {row!r}")
        try:
            observation = parse_lanuv_value(station.id, row[0], row[1])
        except ValueError as error:
            raise LanuvError(f"bad timestamp in row {row!r}") from error
        if observation is not None:
            observations.append(observation)
    return observations


def fetch_levels(
    station: Station,
    start: datetime,
    end: datetime,
    client: httpx.Client | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Observation]:
    """Fetches the station's levels in the half-open window [start, end).

    The portal only serves the last seven days, so older parts of the window come back empty.
    Retries network errors and 5xx answers with exponential backoff, then raises.
    """
    require_utc(start, "start")
    require_utc(end, "end")
    if start >= end:
        raise ValueError("start must be before end")
    if client is None:
        with httpx.Client() as own_client:
            observations = _fetch_with_retries(own_client, station, sleep)
    else:
        observations = _fetch_with_retries(client, station, sleep)
    return [obs for obs in observations if start <= obs.observed_at < end]


def _fetch_with_retries(
    client: httpx.Client, station: Station, sleep: Callable[[float], None]
) -> list[Observation]:
    url = WEEK_URL.format(station_no=station.source_label)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.get(url, timeout=TIMEOUT_SECONDS)
        except httpx.TransportError as error:
            failure = f"network error ({type(error).__name__})"
        else:
            if response.status_code < 400:
                return parse_week(_decode_json(response), station)
            if response.status_code < 500:
                raise LanuvError(f"portal answered HTTP {response.status_code}")
            failure = f"HTTP {response.status_code}"
        if attempt == MAX_ATTEMPTS:
            raise LanuvError(f"portal unreachable after {MAX_ATTEMPTS} attempts: {failure}")
        delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        logger.warning(
            "lanuv request failed, retrying",
            extra={
                "station": station.id,
                "attempt": attempt,
                "failure": failure,
                "retry_in_s": delay,
            },
        )
        sleep(delay)
    raise AssertionError("unreachable")


def _decode_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise LanuvError("response body is not JSON") from None

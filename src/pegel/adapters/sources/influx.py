"""Reads water levels from the client's InfluxDB 1.8 (read-only, GET /query only)."""

import json
import logging
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from pegel.config import Station
from pegel.core.observations import Observation, require_utc

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 2.0

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_REQUIRED_VARIABLES = (
    "INFLUX_URL",
    "INFLUX_DATABASE",
    "INFLUX_CLIENT_CERT",
    "INFLUX_CLIENT_KEY",
    "INFLUX_USERNAME",
    "INFLUX_PASSWORD",
)
# Bind parameters keep the label and times out of the query text, so nothing can inject InfluxQL.
_LEVELS_QUERY = (
    'SELECT "level" FROM "level" WHERE "label" = $label AND time >= $start AND time < $end'
)


class InfluxError(Exception):
    """The source could not be read or answered with something we cannot trust."""


@dataclass(frozen=True)
class InfluxSettings:
    url: str
    database: str
    client_cert: Path
    client_key: Path
    username: str
    password: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def influx_settings_from_env(environ: Mapping[str, str]) -> InfluxSettings:
    """Builds settings from INFLUX_* variables. Errors name the variable, never its value."""
    missing = [name for name in _REQUIRED_VARIABLES if not environ.get(name, "").strip()]
    if missing:
        raise ValueError(f"missing environment variable(s): {', '.join(missing)}")
    url = environ["INFLUX_URL"].strip().rstrip("/")
    if not url.startswith("https://"):
        raise ValueError("INFLUX_URL must start with https:// (the source requires mutual TLS)")
    return InfluxSettings(
        url=url,
        database=environ["INFLUX_DATABASE"].strip(),
        client_cert=Path(environ["INFLUX_CLIENT_CERT"].strip()).expanduser(),
        client_key=Path(environ["INFLUX_CLIENT_KEY"].strip()).expanduser(),
        username=environ["INFLUX_USERNAME"],
        password=environ["INFLUX_PASSWORD"],
        timeout_seconds=_parse_timeout(environ.get("INFLUX_TIMEOUT", "")),
    )


def _parse_timeout(raw: str) -> float:
    if not raw.strip():
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        raise ValueError("INFLUX_TIMEOUT must be a number of seconds") from None
    if timeout <= 0:
        raise ValueError("INFLUX_TIMEOUT must be positive")
    return timeout


def parse_levels(response_json: Any, station_id: str) -> list[Observation]:
    """Turns an InfluxDB /query answer with epoch=ms into observations in centimetres.

    Rows with a null level are skipped and counted in a warning: a missing reading is a gap,
    and gaps are handled downstream, not filled here.
    """
    if not isinstance(response_json, dict):
        raise InfluxError("response is not a JSON object")
    if "error" in response_json:
        raise InfluxError(f"query failed: {response_json['error']}")
    results = response_json.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise InfluxError("expected exactly one statement result")
    result = results[0]
    if not isinstance(result, dict):
        raise InfluxError("statement result is not an object")
    if "error" in result:
        raise InfluxError(f"statement failed: {result['error']}")
    if result.get("partial"):
        raise InfluxError("result is partial; the server cut it off")

    observations: list[Observation] = []
    null_count = 0
    for series in result.get("series", []):
        if not isinstance(series, dict):
            raise InfluxError("series is not an object")
        if series.get("partial"):
            raise InfluxError("series is partial; the server cut it off")
        columns = series.get("columns")
        if not isinstance(columns, list) or "time" not in columns or "level" not in columns:
            raise InfluxError(f"unexpected columns: {columns!r}")
        time_index, level_index = columns.index("time"), columns.index("level")
        for row in series.get("values", []):
            if not isinstance(row, list) or len(row) != len(columns):
                raise InfluxError(f"malformed row: {row!r}")
            level_mm = row[level_index]
            if level_mm is None:
                null_count += 1
                continue
            observations.append(
                Observation(
                    station_id=station_id,
                    observed_at=_parse_epoch_ms(row[time_index]),
                    level_cm=_millimetres_to_centimetres(level_mm),
                )
            )
    if null_count:
        logger.warning(
            "skipped rows without a level",
            extra={"station": station_id, "skipped_rows": null_count},
        )
    return observations


def _parse_epoch_ms(value: Any) -> datetime:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InfluxError(f"time is not epoch milliseconds: {value!r}")
    return _EPOCH + timedelta(milliseconds=value)


def _millimetres_to_centimetres(value: Any) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InfluxError(f"level is not a number: {value!r}")
    # Whole millimetres divide cleanly, but a fractional one doesn't (-399.9 / 10 gives
    # -39.989999999999995). 0.001 cm is finer than any reading, so rounding changes none.
    return round(value / 10, 3)


def fetch_levels(
    settings: InfluxSettings,
    station: Station,
    start: datetime,
    end: datetime,
    client: httpx.Client | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Observation]:
    """Fetches the station's levels in the half-open window [start, end).

    Retries network errors and 5xx answers with exponential backoff, then raises. A 4xx is
    not retried: it means bad credentials or a bad query, which waiting will not fix.
    """
    require_utc(start, "start")
    require_utc(end, "end")
    if start >= end:
        raise ValueError("start must be before end")
    if client is None:
        with httpx.Client(verify=ssl_context(settings)) as own_client:
            return _fetch_with_retries(own_client, settings, station, start, end, sleep)
    return _fetch_with_retries(client, settings, station, start, end, sleep)


def ssl_context(settings: InfluxSettings) -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.load_cert_chain(certfile=settings.client_cert, keyfile=settings.client_key)
    return context


def _fetch_with_retries(
    client: httpx.Client,
    settings: InfluxSettings,
    station: Station,
    start: datetime,
    end: datetime,
    sleep: Callable[[float], None],
) -> list[Observation]:
    context = {
        "station": station.id,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = _request_levels(client, settings, station, start, end)
        except httpx.TransportError as error:
            # Log only the error type: messages and requests can carry the non-public host.
            failure = f"network error ({type(error).__name__})"
        else:
            if response.status_code < 400:
                return parse_levels(_decode_json(response), station.id)
            if response.status_code < 500:
                raise InfluxError(f"source answered HTTP {response.status_code}")
            failure = f"HTTP {response.status_code}"
        if attempt == MAX_ATTEMPTS:
            raise InfluxError(f"source unreachable after {MAX_ATTEMPTS} attempts: {failure}")
        delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        logger.warning(
            "influx request failed, retrying",
            extra={**context, "attempt": attempt, "failure": failure, "retry_in_s": delay},
        )
        sleep(delay)
    raise AssertionError("unreachable")


def _request_levels(
    client: httpx.Client,
    settings: InfluxSettings,
    station: Station,
    start: datetime,
    end: datetime,
) -> httpx.Response:
    bind_parameters = {
        "label": station.source_label,
        "start": _rfc3339(start),
        "end": _rfc3339(end),
    }
    return client.get(
        f"{settings.url}/query",
        params={
            "db": settings.database,
            "q": _LEVELS_QUERY,
            "params": json.dumps(bind_parameters),
            "epoch": "ms",
        },
        auth=httpx.BasicAuth(settings.username, settings.password),
        timeout=settings.timeout_seconds,
    )


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _decode_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise InfluxError("response body is not JSON") from None

"""The published files equal what the API answers from the database: one serializer, no drift."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import TupleRow

from pegel.adapters.api_files import FORECAST_KEY, RECENT_KEY
from pegel.adapters.storage.forecasts import newest_forecast
from pegel.api.app import app, get_database_url, get_read_file
from pegel.config import Station, load_config
from pegel.core.observations import Observation
from pegel.core.schedule import issue_time
from pegel.jobs.pipeline import run_hourly

Conn = psycopg.Connection[TupleRow]
CONFIG = load_config()
# Now, so the readings fall into the default history range the files hold.
ISSUED_AT = issue_time(datetime.now(UTC), CONFIG.forecast.issue_minute)


def source(station: Station, start: datetime, end: datetime) -> list[Observation]:
    newest = ISSUED_AT - timedelta(minutes=8)
    readings = [newest - timedelta(hours=hours) for hours in range(3)]
    return [Observation(station.id, at, 30.0) for at in readings if start <= at < end]


@pytest.fixture
def api(database_url: str) -> Iterator[TestClient]:
    app.dependency_overrides[get_database_url] = lambda: lambda: database_url
    app.dependency_overrides[get_read_file] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("key", "path"), [(FORECAST_KEY, "/api/forecast"), (RECENT_KEY, "/api/history")]
)
def test_published_file_equals_the_database_answer(
    conn: Conn, api: TestClient, key: str, path: str
) -> None:
    files: dict[str, bytes] = {}
    run_hourly(source, conn, CONFIG, ISSUED_AT, publish=files.__setitem__)
    answer = api.get(path).json()
    assert json.loads(files[key]) == answer
    assert answer.get("points") or answer.get("observations")


def test_failing_publish_keeps_the_forecast(conn: Conn) -> None:
    def broken(key: str, body: bytes) -> None:
        raise OSError("s3 down")

    result = run_hourly(source, conn, CONFIG, ISSUED_AT, publish=broken)
    assert newest_forecast(conn, CONFIG.forecast.station_id, result.model) == result

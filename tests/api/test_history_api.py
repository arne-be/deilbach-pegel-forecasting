"""The history endpoint against the throwaway Postgres from conftest.py."""

from collections.abc import Iterator
from datetime import UTC, date, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import TupleRow

from pegel.adapters.storage.observations import upsert_values
from pegel.adapters.storage.series import ensure_series
from pegel.api.app import app, get_database_url, get_today
from pegel.config import load_config
from pegel.core.series import SeriesValue, level_series

Conn = psycopg.Connection[TupleRow]
STATION = "kupferdreh"
TODAY = date(2026, 10, 12)


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    app.dependency_overrides[get_database_url] = lambda: database_url
    app.dependency_overrides[get_today] = lambda: TODAY
    yield TestClient(app)
    app.dependency_overrides.clear()


def observation(observed_at: datetime, level_cm: float) -> SeriesValue:
    return SeriesValue(f"{STATION}:level", observed_at, level_cm, observed_at)


def test_returns_readings_of_whole_berlin_days(client: TestClient, conn: Conn) -> None:
    ensure_series(conn, [level_series(load_config().station(STATION))])
    upsert_values(
        conn,
        [
            observation(datetime(2026, 10, 9, 21, 59, tzinfo=UTC), 10.0),  # Oct 9, 23:59 Berlin
            observation(datetime(2026, 10, 9, 22, 22, tzinfo=UTC), -20.0),  # Oct 10, 00:22 Berlin
            observation(datetime(2026, 10, 10, 21, 22, tzinfo=UTC), 30.0),  # Oct 10, 23:22 Berlin
            observation(datetime(2026, 10, 10, 22, 0, tzinfo=UTC), 40.0),  # Oct 11, 00:00 Berlin
        ],
    )
    response = client.get("/api/history", params={"from": "2026-10-10", "to": "2026-10-10"})
    assert response.status_code == 200
    assert response.json() == {
        "station_id": STATION,
        "from": "2026-10-10",
        "to": "2026-10-10",
        "observations": [
            {"observed_at": "2026-10-09T22:22:00Z", "level_cm": -20.0},
            {"observed_at": "2026-10-10T21:22:00Z", "level_cm": 30.0},
        ],
    }


def test_without_range_returns_the_last_seven_days(client: TestClient) -> None:
    body = client.get("/api/history").json()
    assert (body["from"], body["to"], body["observations"]) == ("2026-10-06", "2026-10-12", [])


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-09-10", "to": "2026-10-11"},  # 32 days
        {"from": "2026-10-05", "to": "2026-10-04"},
        {"to": "2026-10-13"},
        {"from": "2026-10-10T05:00", "to": "2026-10-10"},
        {"from": "2026-10-10T00:00", "to": "2026-10-10"},
        {"from": "1760054400"},
        {"from": "2026-02-30", "to": "2026-03-01"},
        {"from": "0001-01-01", "to": "0001-01-02"},
        {"from": "gestern"},
    ],
)
def test_bad_ranges_are_rejected_before_the_database(params: dict[str, str]) -> None:
    # An unreachable database proves validation fails before any connection is made.
    app.dependency_overrides[get_database_url] = lambda: "postgresql://nobody@127.0.0.1:1/none"
    app.dependency_overrides[get_today] = lambda: TODAY
    try:
        status = TestClient(app).get("/api/history", params=params).status_code
    finally:
        app.dependency_overrides.clear()
    assert status == 422


def test_max_days_is_allowed(client: TestClient) -> None:
    response = client.get("/api/history", params={"from": "2026-09-11", "to": "2026-10-11"})
    assert response.status_code == 200

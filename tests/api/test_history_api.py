"""The history endpoint against the throwaway Postgres from conftest.py."""

from collections.abc import Iterator
from datetime import UTC, date, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import TupleRow

from pegel.adapters.api_files import RECENT_KEY
from pegel.adapters.storage.observations import upsert_values
from pegel.adapters.storage.series import ensure_series
from pegel.api.app import app, get_database_url, get_read_file, get_today
from pegel.api.responses import matches_range
from pegel.config import load_config
from pegel.core.series import SeriesValue, cleaned_level_series, level_series, level_series_id

Conn = psycopg.Connection[TupleRow]
STATION = "kupferdreh"
TODAY = date(2026, 10, 12)


@pytest.fixture
def files() -> dict[str, bytes]:
    return {}


@pytest.fixture
def client(database_url: str, files: dict[str, bytes]) -> Iterator[TestClient]:
    app.dependency_overrides[get_database_url] = lambda: lambda: database_url
    app.dependency_overrides[get_read_file] = lambda: files.__getitem__
    app.dependency_overrides[get_today] = lambda: TODAY
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def series(conn: Conn) -> None:
    station = load_config().station(STATION)
    ensure_series(conn, [level_series(station), cleaned_level_series(station)])


def cleaned(observed_at: datetime, level_cm: float) -> SeriesValue:
    return SeriesValue(
        cleaned_level_series(load_config().station(STATION)).id, observed_at, level_cm, observed_at
    )


def test_returns_readings_of_whole_berlin_days(client: TestClient, conn: Conn) -> None:
    upsert_values(
        conn,
        [
            cleaned(datetime(2026, 10, 9, 21, 59, tzinfo=UTC), 10.0),  # Oct 9, 23:59 Berlin
            cleaned(datetime(2026, 10, 9, 22, 22, tzinfo=UTC), -20.0),  # Oct 10, 00:22 Berlin
            cleaned(datetime(2026, 10, 10, 21, 22, tzinfo=UTC), 30.0),  # Oct 10, 23:22 Berlin
            cleaned(datetime(2026, 10, 10, 22, 0, tzinfo=UTC), 40.0),  # Oct 11, 00:00 Berlin
        ],
        datetime(2026, 10, 10, 22, 30, tzinfo=UTC),
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


def test_outlier_only_in_the_raw_series_is_not_returned(client: TestClient, conn: Conn) -> None:
    observed_at = datetime(2026, 10, 10, 8, 22, tzinfo=UTC)
    upsert_values(
        conn, [SeriesValue(level_series_id(STATION), observed_at, 298.0, observed_at)], observed_at
    )
    body = client.get("/api/history", params={"from": "2026-10-10", "to": "2026-10-10"}).json()
    assert body["observations"] == []


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
    app.dependency_overrides[get_database_url] = lambda: (
        lambda: "postgresql://nobody@127.0.0.1:1/none"
    )
    app.dependency_overrides[get_today] = lambda: TODAY
    try:
        status = TestClient(app).get("/api/history", params=params).status_code
    finally:
        app.dependency_overrides.clear()
    assert status == 422


def test_max_days_is_allowed(client: TestClient) -> None:
    response = client.get("/api/history", params={"from": "2026-09-11", "to": "2026-10-11"})
    assert response.status_code == 200


def recent_file(first_day: str, last_day: str) -> bytes:
    return (
        f'{{"station_id": "{STATION}", "from": "{first_day}", "to": "{last_day}", '
        '"observations": [{"observed_at": "2026-10-12T08:22:00Z", "level_cm": 99.0}]}'
    ).encode()


def no_database() -> str:
    raise AssertionError("the database was asked")


@pytest.mark.parametrize("params", [{}, {"from": "2026-10-06", "to": "2026-10-12"}])
def test_default_range_is_served_from_the_file(
    client: TestClient, files: dict[str, bytes], params: dict[str, str]
) -> None:
    files[RECENT_KEY] = recent_file("2026-10-06", "2026-10-12")
    app.dependency_overrides[get_database_url] = lambda: no_database
    body = client.get("/api/history", params=params).json()
    assert body["observations"][0]["level_cm"] == 99.0


def test_file_of_yesterday_falls_back_to_the_database(
    client: TestClient, files: dict[str, bytes]
) -> None:
    # Just after midnight: the newest file still ends yesterday.
    files[RECENT_KEY] = recent_file("2026-10-05", "2026-10-11")
    body = client.get("/api/history").json()
    assert (body["from"], body["to"], body["observations"]) == ("2026-10-06", "2026-10-12", [])


def test_older_range_comes_from_the_database(client: TestClient, files: dict[str, bytes]) -> None:
    files[RECENT_KEY] = recent_file("2026-10-06", "2026-10-12")
    body = client.get("/api/history", params={"from": "2026-10-01", "to": "2026-10-07"}).json()
    assert (body["from"], body["to"], body["observations"]) == ("2026-10-01", "2026-10-07", [])


@pytest.mark.parametrize("body", [b"not json", b"[]", b"{}", b'{"from": "2026-10-06"}'])
def test_matches_range_is_false_for_a_bad_body(body: bytes) -> None:
    assert not matches_range(body, date(2026, 10, 6), date(2026, 10, 12))


@pytest.mark.parametrize(
    ("last_day", "cache_control"),
    [
        ("2026-10-12", "public, max-age=300, stale-if-error=86400"),
        ("2026-10-11", "public, max-age=300, stale-if-error=86400"),
        ("2026-10-10", "public, max-age=86400, stale-if-error=86400"),
    ],
)
def test_cache_lifetime_depends_on_the_last_day(
    client: TestClient, last_day: str, cache_control: str
) -> None:
    response = client.get("/api/history", params={"from": "2026-10-01", "to": last_day})
    assert response.headers["cache-control"] == cache_control


def test_history_file_is_cached_briefly(client: TestClient, files: dict[str, bytes]) -> None:
    files[RECENT_KEY] = recent_file("2026-10-06", "2026-10-12")
    response = client.get("/api/history")
    assert response.headers["cache-control"] == "public, max-age=300, stale-if-error=86400"

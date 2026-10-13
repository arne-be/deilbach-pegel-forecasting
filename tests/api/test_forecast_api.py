"""The forecast endpoint against the throwaway Postgres from conftest.py."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import save_forecast
from pegel.api.app import app, get_database_url
from pegel.core.forecasts import Forecast, ForecastPoint

Conn = psycopg.Connection[TupleRow]
STATION = "kupferdreh"
OBSERVED_AT = datetime(2026, 10, 12, 15, 22, tzinfo=UTC)


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    app.dependency_overrides[get_database_url] = lambda: database_url
    yield TestClient(app)
    app.dependency_overrides.clear()


def forecast(observed_at: datetime, levels: list[float], model: str = "persistence") -> Forecast:
    points = tuple(
        ForecastPoint(observed_at + timedelta(hours=lead), level)
        for lead, level in enumerate(levels, start=1)
    )
    return Forecast(STATION, model, observed_at + timedelta(minutes=8), observed_at, points)


def test_returns_the_newest_forecast(client: TestClient, conn: Conn) -> None:
    save_forecast(conn, forecast(OBSERVED_AT - timedelta(hours=1), [0.5, 0.5]))
    save_forecast(conn, forecast(OBSERVED_AT, [-20.0, -10.0]))
    response = client.get("/api/forecast")
    assert response.status_code == 200
    assert response.json() == {
        "station_id": STATION,
        "model": "persistence",
        "issued_at": "2026-10-12T15:30:00Z",
        "newest_observation_at": "2026-10-12T15:22:00Z",
        "points": [
            {"valid_at": "2026-10-12T16:22:00Z", "level_cm": -20.0},
            {"valid_at": "2026-10-12T17:22:00Z", "level_cm": -10.0},
        ],
    }


def test_ignores_forecasts_of_other_models(client: TestClient, conn: Conn) -> None:
    save_forecast(conn, forecast(OBSERVED_AT, [10.0], model="persistence"))
    save_forecast(conn, forecast(OBSERVED_AT + timedelta(hours=1), [0.9], model="experiment"))
    assert client.get("/api/forecast").json()["points"][0]["level_cm"] == 10.0


def test_no_forecast_is_404(client: TestClient) -> None:
    response = client.get("/api/forecast")
    assert (response.status_code, response.json()) == (404, {"detail": "no forecast yet"})

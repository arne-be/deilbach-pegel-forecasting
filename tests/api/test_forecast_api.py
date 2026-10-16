"""The forecast endpoint against the throwaway Postgres from conftest.py."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import save_forecast
from pegel.api.app import app, get_config, get_database_url
from pegel.config import load_config
from pegel.core.forecasts import Band, Forecast, ForecastPoint

Conn = psycopg.Connection[TupleRow]
STATION = "kupferdreh"
RIDGE = "ridge:change:v2"
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
        "situation": None,
        "points": [
            {"valid_at": "2026-10-12T16:22:00Z", "level_cm": -20.0, "bands": []},
            {"valid_at": "2026-10-12T17:22:00Z", "level_cm": -10.0, "bands": []},
        ],
    }


def test_returns_the_bands_and_situation(client: TestClient, conn: Conn) -> None:
    bands = (Band(80, 40.0, 44.0), Band(95, 38.0, 47.0))
    point = ForecastPoint(OBSERVED_AT + timedelta(hours=1), 42.0, bands)
    save_forecast(
        conn, Forecast(STATION, "persistence", OBSERVED_AT, OBSERVED_AT, (point,), "calm")
    )
    body = client.get("/api/forecast").json()
    assert body["situation"] == "calm"
    assert body["points"][0]["bands"] == [
        {"coverage_percent": 80, "lower_cm": 40.0, "upper_cm": 44.0},
        {"coverage_percent": 95, "lower_cm": 38.0, "upper_cm": 47.0},
    ]


def test_ignores_forecasts_of_other_models(client: TestClient, conn: Conn) -> None:
    save_forecast(conn, forecast(OBSERVED_AT, [10.0], model="persistence"))
    save_forecast(conn, forecast(OBSERVED_AT + timedelta(hours=1), [0.9], model="experiment"))
    assert client.get("/api/forecast").json()["points"][0]["level_cm"] == 10.0


def test_no_forecast_is_404(client: TestClient) -> None:
    response = client.get("/api/forecast")
    assert (response.status_code, response.json()) == (404, {"detail": "no forecast yet"})


@pytest.fixture
def ridge_client(client: TestClient) -> Iterator[TestClient]:
    config = load_config()
    forecast_settings = config.forecast.model_copy(update={"model": RIDGE, "model_file": "m"})
    app.dependency_overrides[get_config] = lambda: config.model_copy(
        update={"forecast": forecast_settings}
    )
    yield client


def test_serves_the_configured_model(ridge_client: TestClient, conn: Conn) -> None:
    save_forecast(conn, forecast(OBSERVED_AT, [10.0]))
    save_forecast(conn, forecast(OBSERVED_AT, [12.0], model=RIDGE))
    assert ridge_client.get("/api/forecast").json()["model"] == RIDGE


@pytest.mark.parametrize("ridge_hours_back", [None, 1])
def test_falls_back_to_a_newer_persistence_forecast(
    ridge_client: TestClient, conn: Conn, ridge_hours_back: int | None
) -> None:
    save_forecast(conn, forecast(OBSERVED_AT, [10.0]))
    if ridge_hours_back is not None:
        observed_at = OBSERVED_AT - timedelta(hours=ridge_hours_back)
        save_forecast(conn, forecast(observed_at, [12.0], model=RIDGE))
    body = ridge_client.get("/api/forecast").json()
    assert (body["model"], body["points"][0]["level_cm"]) == ("persistence", 10.0)

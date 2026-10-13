from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.forecasts import newest_forecast, save_forecast
from pegel.core.forecasts import Forecast, ForecastPoint

STATION = "kupferdreh"
MODEL = "persistence"
ISSUED_AT = datetime(2026, 10, 12, 12, 30, tzinfo=UTC)

Conn = psycopg.Connection[TupleRow]


def forecast(levels: list[float], issued_at: datetime = ISSUED_AT) -> Forecast:
    points = tuple(
        ForecastPoint(issued_at + timedelta(hours=hour + 1), level)
        for hour, level in enumerate(levels)
    )
    return Forecast(STATION, MODEL, issued_at, issued_at - timedelta(minutes=8), points)


def test_saved_forecast_round_trips(conn: Conn) -> None:
    saved = forecast([40.0, -10.0, 60.0])
    save_forecast(conn, saved)
    assert newest_forecast(conn, STATION, MODEL) == saved


def test_rerun_replaces_points(conn: Conn) -> None:
    save_forecast(conn, forecast([40.0, 50.0, 60.0]))
    rerun = forecast([70.0, 80.0])
    save_forecast(conn, rerun)
    assert newest_forecast(conn, STATION, MODEL) == rerun


def test_rerun_keeps_one_forecast_row(conn: Conn) -> None:
    save_forecast(conn, forecast([40.0]))
    save_forecast(conn, forecast([50.0]))
    row = conn.execute("SELECT count(*) FROM forecasts").fetchone()
    assert row == (1,)


def test_newest_forecast_is_the_latest_issue(conn: Conn) -> None:
    later = forecast([0.9], issued_at=ISSUED_AT + timedelta(hours=1))
    save_forecast(conn, later)
    save_forecast(conn, forecast([40.0]))
    assert newest_forecast(conn, STATION, MODEL) == later


def test_newest_forecast_of_other_model_is_none(conn: Conn) -> None:
    save_forecast(conn, forecast([40.0]))
    assert newest_forecast(conn, STATION, "other") is None


def test_timestamps_come_back_utc_whatever_the_session_time_zone(conn: Conn) -> None:
    saved = forecast([40.0, 50.0])
    save_forecast(conn, saved)
    conn.execute("SET TIME ZONE 'Europe/Berlin'")
    assert newest_forecast(conn, STATION, MODEL) == saved


def test_jobs_role_can_save(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_jobs")
    save_forecast(conn, forecast([40.0]))
    assert newest_forecast(conn, STATION, MODEL) is not None


def test_api_role_cannot_save(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        save_forecast(conn, forecast([40.0]))

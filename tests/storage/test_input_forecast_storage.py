from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.input_forecasts import newest_run_at, upsert_input_forecasts
from pegel.adapters.storage.series import ensure_series
from pegel.core.series import InputForecastValue, Series

Conn = psycopg.Connection[TupleRow]
HOUR = timedelta(hours=1)
RAIN = Series(
    "icon_d2:catchment:mean", "rain", "mm", "icon_d2", "catchment", "forecast", HOUR, "mean"
)
RADAR = Series(
    "radar:catchment:mean", "rain", "mm", "radar", "catchment", "observation", HOUR, "mean"
)
RUN_AT = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def series(conn: Conn) -> None:
    ensure_series(conn, [RAIN, RADAR])


def run(
    run_at: datetime, values: list[float], available_at: datetime | None = None
) -> list[InputForecastValue]:
    return [
        InputForecastValue(
            RAIN.id, run_at, run_at + (hour + 1) * HOUR, value, available_at or run_at
        )
        for hour, value in enumerate(values)
    ]


def stored_available_at(conn: Conn) -> list[datetime]:
    rows = conn.execute("SELECT available_at FROM input_forecasts ORDER BY valid_at").fetchall()
    return [row[0] for row in rows]


def stored_values(conn: Conn) -> list[float]:
    rows = conn.execute("SELECT value FROM input_forecasts ORDER BY run_at, valid_at").fetchall()
    return [row[0] for row in rows]


def test_rerun_adds_nothing(conn: Conn) -> None:
    assert upsert_input_forecasts(conn, run(RUN_AT, [0.1, 0.2]), RUN_AT) == 2
    assert upsert_input_forecasts(conn, run(RUN_AT, [0.1, 0.2]), RUN_AT) == 0
    assert stored_values(conn) == [0.1, 0.2]


def test_changed_value_is_updated(conn: Conn) -> None:
    upsert_input_forecasts(conn, run(RUN_AT, [0.1, 0.2]), RUN_AT)
    assert upsert_input_forecasts(conn, run(RUN_AT, [0.1, 0.3]), RUN_AT) == 1
    assert stored_values(conn) == [0.1, 0.3]


def test_unchanged_value_keeps_its_first_available_at(conn: Conn) -> None:
    upsert_input_forecasts(conn, run(RUN_AT, [0.1], RUN_AT + HOUR), RUN_AT)
    upsert_input_forecasts(conn, run(RUN_AT, [0.1], RUN_AT + 2 * HOUR), RUN_AT)
    assert stored_available_at(conn) == [RUN_AT + HOUR]


def test_changed_value_takes_the_new_available_at(conn: Conn) -> None:
    upsert_input_forecasts(conn, run(RUN_AT, [0.1], RUN_AT + HOUR), RUN_AT)
    upsert_input_forecasts(conn, run(RUN_AT, [0.2], RUN_AT + 2 * HOUR), RUN_AT)
    assert stored_available_at(conn) == [RUN_AT + 2 * HOUR]


def test_backfilled_revision_is_not_dated_back(conn: Conn) -> None:
    upsert_input_forecasts(conn, run(RUN_AT, [0.1], RUN_AT + HOUR), RUN_AT)
    upsert_input_forecasts(conn, run(RUN_AT, [0.2], RUN_AT + HOUR), RUN_AT + 5 * HOUR)
    upsert_input_forecasts(conn, run(RUN_AT, [0.2], RUN_AT + HOUR), RUN_AT + 9 * HOUR)
    assert stored_available_at(conn) == [RUN_AT + 5 * HOUR]


def test_runs_are_kept_side_by_side(conn: Conn) -> None:
    upsert_input_forecasts(conn, run(RUN_AT, [0.1]), RUN_AT)
    upsert_input_forecasts(conn, run(RUN_AT + 3 * HOUR, [0.5]), RUN_AT)
    assert stored_values(conn) == [0.1, 0.5]


def test_newest_run_at(conn: Conn) -> None:
    upsert_input_forecasts(conn, run(RUN_AT + 3 * HOUR, [0.5]), RUN_AT)
    upsert_input_forecasts(conn, run(RUN_AT, [0.1]), RUN_AT)
    conn.execute("SET TIME ZONE 'Europe/Berlin'")
    assert newest_run_at(conn, RAIN.id) == RUN_AT + 3 * HOUR


def test_newest_run_at_of_empty_series_is_none(conn: Conn) -> None:
    assert newest_run_at(conn, RAIN.id) is None


def test_unknown_series_is_rejected(conn: Conn) -> None:
    unknown = InputForecastValue("nowhere:rain", RUN_AT, RUN_AT + HOUR, 0.1, RUN_AT)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        upsert_input_forecasts(conn, [unknown], RUN_AT)


def test_api_role_cannot_insert(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        upsert_input_forecasts(conn, run(RUN_AT, [0.1]), RUN_AT)


def test_forecast_value_for_an_observation_series_is_rejected(conn: Conn) -> None:
    value = InputForecastValue(RADAR.id, RUN_AT, RUN_AT + HOUR, 0.1, RUN_AT)
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="forecast"):
        upsert_input_forecasts(conn, [value], RUN_AT)

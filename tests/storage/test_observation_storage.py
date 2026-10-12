from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.observations import (
    fetch_observations,
    newest_observation,
    upsert_observations,
)
from pegel.core.observations import Observation

STATION = "kupferdreh"
START = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)

Conn = psycopg.Connection[TupleRow]


def hourly(levels: list[float]) -> list[Observation]:
    return [
        Observation(STATION, START + timedelta(hours=hour), level)
        for hour, level in enumerate(levels)
    ]


def row_count(conn: Conn) -> int:
    row = conn.execute("SELECT count(*) FROM raw_observations").fetchone()
    assert row is not None
    return int(row[0])


def test_rerun_adds_no_duplicates(conn: Conn) -> None:
    observations = hourly([0.4, 0.5, 0.6])
    upsert_observations(conn, observations, "influx")
    upsert_observations(conn, observations, "influx")
    assert row_count(conn) == 3


def test_rerun_with_same_values_reports_no_changes(conn: Conn) -> None:
    observations = hourly([0.4, 0.5, 0.6])
    upsert_observations(conn, observations, "influx")
    assert upsert_observations(conn, observations, "influx") == 0


def test_changed_value_is_updated(conn: Conn) -> None:
    upsert_observations(conn, hourly([0.4, 0.5]), "influx")
    changed = upsert_observations(conn, hourly([0.4, 0.55]), "influx")
    stored = fetch_observations(conn, STATION, START, START + timedelta(hours=2))
    assert (changed, [o.level_m for o in stored]) == (1, [0.4, 0.55])


def test_negative_levels_are_kept(conn: Conn) -> None:
    upsert_observations(conn, hourly([-0.25, -0.3]), "influx")
    stored = fetch_observations(conn, STATION, START, START + timedelta(hours=2))
    assert [o.level_m for o in stored] == [-0.25, -0.3]


def test_window_includes_start_and_excludes_end(conn: Conn) -> None:
    upsert_observations(conn, hourly([0.1, 0.2, 0.3, 0.4]), "influx")
    stored = fetch_observations(
        conn, STATION, START + timedelta(hours=1), START + timedelta(hours=3)
    )
    assert [o.level_m for o in stored] == [0.2, 0.3]


def test_window_comes_back_oldest_first(conn: Conn) -> None:
    upsert_observations(conn, list(reversed(hourly([0.1, 0.2, 0.3]))), "influx")
    stored = fetch_observations(conn, STATION, START, START + timedelta(hours=3))
    assert [o.observed_at for o in stored] == [START + timedelta(hours=h) for h in range(3)]


def test_timestamps_come_back_utc_whatever_the_session_time_zone(conn: Conn) -> None:
    upsert_observations(conn, hourly([0.1]), "influx")
    conn.execute("SET TIME ZONE 'Europe/Berlin'")
    stored = newest_observation(conn, STATION)
    assert stored == Observation(STATION, START, 0.1)


def test_newest_observation_is_the_latest(conn: Conn) -> None:
    upsert_observations(conn, hourly([0.1, 0.2, 0.3]), "influx")
    assert newest_observation(conn, STATION) == hourly([0.1, 0.2, 0.3])[-1]


def test_newest_observation_of_empty_station_is_none(conn: Conn) -> None:
    assert newest_observation(conn, STATION) is None


def test_naive_window_is_rejected(conn: Conn) -> None:
    naive_start = datetime(2026, 10, 12)  # noqa: DTZ001
    with pytest.raises(ValueError, match="UTC"):
        fetch_observations(conn, STATION, naive_start, START)


def test_api_role_cannot_insert(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        upsert_observations(conn, hourly([0.1]), "influx")


def test_jobs_role_can_upsert(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_jobs")
    assert upsert_observations(conn, hourly([0.1, 0.2]), "influx") == 2

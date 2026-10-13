from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.observations import (
    delete_values,
    fetch_observations,
    fetch_values,
    newest_observation,
    upsert_values,
)
from pegel.adapters.storage.series import ensure_series
from pegel.config import load_config
from pegel.core.observations import Observation
from pegel.core.series import Series, SeriesValue, level_series

STATION = "kupferdreh"
START = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)

Conn = psycopg.Connection[TupleRow]
RAIN = Series("radar:zone:test", "rain", "mm", "radar", "zone:test", "observation", "mean")
LEVEL = f"{STATION}:level"
ICON = Series("icon_d2:zone:test", "rain", "mm", "icon_d2", "zone:test", "forecast", "mean")


@pytest.fixture(autouse=True)
def series(conn: Conn) -> None:
    ensure_series(conn, [level_series(load_config().station(STATION)), RAIN, ICON])


def hourly(levels: list[float]) -> list[Observation]:
    return [
        Observation(STATION, START + timedelta(hours=hour), level)
        for hour, level in enumerate(levels)
    ]


def upsert_observations(
    conn: Conn, observations: list[Observation], available_at: datetime = FAR_FUTURE
) -> int:
    values = [
        SeriesValue(f"{o.station_id}:level", o.observed_at, o.level_cm, available_at)
        for o in observations
    ]
    return upsert_values(conn, values, START)


def stored_available_at(conn: Conn) -> list[datetime]:
    rows = conn.execute("SELECT available_at FROM observations ORDER BY valid_at").fetchall()
    return [row[0] for row in rows]


def row_count(conn: Conn) -> int:
    row = conn.execute("SELECT count(*) FROM observations").fetchone()
    assert row is not None
    return int(row[0])


def test_rerun_adds_no_duplicates(conn: Conn) -> None:
    observations = hourly([40.0, 50.0, 60.0])
    upsert_observations(conn, observations)
    upsert_observations(conn, observations)
    assert row_count(conn) == 3


def test_rerun_with_same_values_reports_no_changes(conn: Conn) -> None:
    observations = hourly([40.0, 50.0, 60.0])
    upsert_observations(conn, observations)
    assert upsert_observations(conn, observations) == 0


def test_unchanged_value_keeps_its_first_available_at(conn: Conn) -> None:
    upsert_observations(conn, hourly([40.0]), available_at=START + HOUR)
    upsert_observations(conn, hourly([40.0]), available_at=START + 2 * HOUR)
    assert stored_available_at(conn) == [START + HOUR]


def test_changed_value_takes_the_new_available_at(conn: Conn) -> None:
    upsert_observations(conn, hourly([40.0]), available_at=START + HOUR)
    upsert_observations(conn, hourly([41.0]), available_at=START + 2 * HOUR)
    assert stored_available_at(conn) == [START + 2 * HOUR]


def test_backfilled_revision_is_not_dated_back(conn: Conn) -> None:
    upsert_observations(conn, hourly([40.0]), available_at=START + HOUR)
    upsert_values(conn, [SeriesValue(LEVEL, START, 41.0, START + HOUR)], START + 5 * HOUR)
    upsert_values(conn, [SeriesValue(LEVEL, START, 41.0, START + HOUR)], START + 9 * HOUR)
    assert stored_available_at(conn) == [START + 5 * HOUR]


def test_changed_value_is_updated(conn: Conn) -> None:
    upsert_observations(conn, hourly([40.0, 50.0]))
    changed = upsert_observations(conn, hourly([40.0, 55.0]))
    stored = fetch_observations(conn, STATION, START, START + timedelta(hours=2))
    assert (changed, [o.level_cm for o in stored]) == (1, [40.0, 55.0])


def test_negative_levels_are_kept(conn: Conn) -> None:
    upsert_observations(conn, hourly([-25.0, -30.0]))
    stored = fetch_observations(conn, STATION, START, START + timedelta(hours=2))
    assert [o.level_cm for o in stored] == [-25.0, -30.0]


def test_window_includes_start_and_excludes_end(conn: Conn) -> None:
    upsert_observations(conn, hourly([10.0, 20.0, 30.0, 40.0]))
    stored = fetch_observations(
        conn, STATION, START + timedelta(hours=1), START + timedelta(hours=3)
    )
    assert [o.level_cm for o in stored] == [20.0, 30.0]


def test_window_comes_back_oldest_first(conn: Conn) -> None:
    upsert_observations(conn, list(reversed(hourly([10.0, 20.0, 30.0]))))
    stored = fetch_observations(conn, STATION, START, START + timedelta(hours=3))
    assert [o.observed_at for o in stored] == [START + timedelta(hours=h) for h in range(3)]


def test_timestamps_come_back_utc_whatever_the_session_time_zone(conn: Conn) -> None:
    upsert_observations(conn, hourly([10.0]))
    conn.execute("SET TIME ZONE 'Europe/Berlin'")
    stored = newest_observation(conn, STATION, FAR_FUTURE)
    assert stored == Observation(STATION, START, 10.0)


def test_newest_observation_is_the_latest(conn: Conn) -> None:
    upsert_observations(conn, hourly([10.0, 20.0, 30.0]))
    assert newest_observation(conn, STATION, FAR_FUTURE) == hourly([10.0, 20.0, 30.0])[-1]


def test_newest_observation_of_empty_station_is_none(conn: Conn) -> None:
    assert newest_observation(conn, STATION, FAR_FUTURE) is None


def test_naive_window_is_rejected(conn: Conn) -> None:
    naive_start = datetime(2026, 10, 12)  # noqa: DTZ001
    with pytest.raises(ValueError, match="UTC"):
        fetch_observations(conn, STATION, naive_start, START)


def test_api_role_cannot_insert(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        upsert_observations(conn, hourly([10.0]))


def test_jobs_role_can_upsert(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_jobs")
    assert upsert_observations(conn, hourly([10.0, 20.0])) == 2


def test_newest_observation_ignores_readings_after_the_bound(conn: Conn) -> None:
    upsert_observations(conn, hourly([10.0, 20.0, 30.0]))
    bound = START + timedelta(hours=1)
    assert newest_observation(conn, STATION, bound) == hourly([10.0, 20.0])[-1]


def test_values_of_an_unknown_series_are_rejected(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        upsert_values(conn, [SeriesValue("nowhere:level", START, 10.0, START)], START)


def test_values_round_trip_with_coverage(conn: Conn) -> None:
    values = [
        SeriesValue(RAIN.id, START, 1.5, START + HOUR, 0.75),
        SeriesValue(RAIN.id, START + HOUR, 0.0, START + 2 * HOUR),
    ]
    upsert_values(conn, values, START)
    assert fetch_values(conn, RAIN.id, START, FAR_FUTURE) == values


def test_changed_coverage_counts_as_a_change(conn: Conn) -> None:
    upsert_values(conn, [SeriesValue(RAIN.id, START, 1.5, START, 0.75)], START)
    assert upsert_values(conn, [SeriesValue(RAIN.id, START, 1.5, START, 0.75)], START) == 0
    assert upsert_values(conn, [SeriesValue(RAIN.id, START, 1.5, START, 1.0)], START) == 1


def test_series_are_kept_apart(conn: Conn) -> None:
    upsert_values(conn, [SeriesValue(RAIN.id, START, 1.5, START)], START)
    upsert_observations(conn, hourly([40.0]))
    assert [o.level_cm for o in fetch_observations(conn, STATION, START, FAR_FUTURE)] == [40.0]


def test_observed_value_for_a_forecast_series_is_rejected(conn: Conn) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation, match="observation"):
        upsert_values(conn, [SeriesValue(ICON.id, START, 1.5, START)], START)


def test_delete_values_removes_only_the_given_times(conn: Conn) -> None:
    values = [
        SeriesValue(RAIN.id, START + hour * HOUR, 1.0, START + hour * HOUR) for hour in range(3)
    ]
    upsert_values(conn, values, START)
    deleted = delete_values(conn, RAIN.id, [START + HOUR, START + 5 * HOUR])
    assert (deleted, fetch_values(conn, RAIN.id, START, FAR_FUTURE)) == (1, values[::2])


def test_jobs_role_can_delete_values(conn: Conn) -> None:
    upsert_values(conn, [SeriesValue(RAIN.id, START, 1.0, START)], START)
    conn.execute("SET ROLE pegel_jobs")
    assert delete_values(conn, RAIN.id, [START]) == 1

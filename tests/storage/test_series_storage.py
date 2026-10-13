from dataclasses import astuple
from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.series import ensure_series
from pegel.core.series import Series

Conn = psycopg.Connection[TupleRow]
RAIN = Series(
    "radolan_rw:zone:neviges",
    "rain",
    "mm",
    "radolan_rw",
    "zone:neviges",
    "mean",
    timedelta(hours=1),
)


def stored(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT id, variable, unit, source, location, aggregation, period, description FROM series"
    ).fetchall()


def test_new_series_is_stored(conn: Conn) -> None:
    assert ensure_series(conn, [RAIN]) == 1
    assert stored(conn) == [(*astuple(RAIN),)]


def test_ensuring_again_changes_nothing(conn: Conn) -> None:
    ensure_series(conn, [RAIN])
    assert ensure_series(conn, [RAIN]) == 0


def test_changed_metadata_is_updated(conn: Conn) -> None:
    ensure_series(conn, [RAIN])
    changed = Series(RAIN.id, "rain", "mm", "radolan_rw", "zone:neviges", "p90", RAIN.period)
    assert ensure_series(conn, [changed]) == 1
    assert stored(conn)[0][5] == "p90"


def test_nothing_to_ensure(conn: Conn) -> None:
    assert ensure_series(conn, []) == 0


def test_api_role_cannot_ensure(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ensure_series(conn, [RAIN])


def test_jobs_role_can_ensure(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_jobs")
    assert ensure_series(conn, [RAIN]) == 1

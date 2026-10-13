from dataclasses import astuple, replace
from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.storage.series import SeriesDefinitionChangeError, ensure_series
from pegel.core.series import Series

Conn = psycopg.Connection[TupleRow]
RAIN = Series(
    "radolan_rw:zone:neviges",
    "rain",
    "mm",
    "radolan_rw",
    "zone:neviges",
    "observation",
    "mean",
    timedelta(hours=1),
)


def stored(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT id, variable, unit, source, location, kind, aggregation, period, description"
        " FROM series"
    ).fetchall()


def test_new_series_is_stored(conn: Conn) -> None:
    assert ensure_series(conn, [RAIN]) == 1
    assert stored(conn) == [(*astuple(RAIN),)]


def test_ensuring_again_changes_nothing(conn: Conn) -> None:
    ensure_series(conn, [RAIN])
    assert ensure_series(conn, [RAIN]) == 0


def test_changed_metadata_is_updated(conn: Conn) -> None:
    ensure_series(conn, [RAIN])
    changed = replace(RAIN, aggregation="p90")
    assert ensure_series(conn, [changed]) == 1
    assert stored(conn)[0][6] == "p90"


def test_nothing_to_ensure(conn: Conn) -> None:
    assert ensure_series(conn, []) == 0


def test_api_role_cannot_ensure(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        ensure_series(conn, [RAIN])


def test_jobs_role_can_ensure(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_jobs")
    assert ensure_series(conn, [RAIN]) == 1


@pytest.mark.parametrize(
    "changes", [{"kind": "forecast"}, {"unit": "cm"}, {"variable": "soil_moisture"}]
)
def test_kind_variable_and_unit_of_a_stored_series_cannot_change(
    conn: Conn, changes: dict[str, str]
) -> None:
    ensure_series(conn, [RAIN])
    with pytest.raises(SeriesDefinitionChangeError, match="radolan_rw:zone:neviges"):
        ensure_series(conn, [replace(RAIN, description="changed", **changes)])  # type: ignore[arg-type]
    assert stored(conn) == [(*astuple(RAIN),)]


def test_other_metadata_may_change(conn: Conn) -> None:
    ensure_series(conn, [RAIN])
    changed = replace(RAIN, source="radolan_yw", location="zone:velbert", description="new")
    assert ensure_series(conn, [changed]) == 1
    assert stored(conn) == [(*astuple(changed),)]

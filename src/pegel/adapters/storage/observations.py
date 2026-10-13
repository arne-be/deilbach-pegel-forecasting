"""Observed values of any series, plus the level wrappers the jobs and the API use."""

from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg
from psycopg.rows import TupleRow, class_row

from pegel.adapters.storage.records import ObservationRecord
from pegel.core.observations import Observation, require_utc
from pegel.core.series import SeriesValue, level_series_id

# One statement for the whole batch keeps backfills of a month to one round trip.
# Unchanged rows are skipped, so the returned count says what actually changed, and an
# unchanged value keeps its first available_at. A revised value is stamped no earlier than the
# issue slot that saw it, so a backfill can't date a revision back to the original value.
UPSERT_SQL = """
    INSERT INTO observations (series_id, valid_at, value, coverage, available_at)
    SELECT *
    FROM unnest(%s::text[], %s::timestamptz[], %s::double precision[], %s::double precision[],
                %s::timestamptz[])
    ON CONFLICT (series_id, valid_at) DO UPDATE
    SET value = excluded.value, coverage = excluded.coverage,
        available_at = greatest(excluded.available_at, %s::timestamptz), ingested_at = now()
    WHERE (observations.value, observations.coverage)
        IS DISTINCT FROM (excluded.value, excluded.coverage)
"""

FETCH_SQL = """
    SELECT series_id, valid_at, value, coverage, ingested_at, kind, available_at
    FROM observations
    WHERE series_id = %s AND valid_at >= %s AND valid_at < %s
    ORDER BY valid_at
"""

DELETE_SQL = "DELETE FROM observations WHERE series_id = %s AND valid_at = ANY(%s::timestamptz[])"

NEWEST_SQL = """
    SELECT series_id, valid_at, value, coverage, ingested_at, kind, available_at
    FROM observations
    WHERE series_id = %s AND valid_at <= %s
    ORDER BY valid_at DESC
    LIMIT 1
"""


def upsert_values(
    conn: psycopg.Connection[TupleRow], values: Sequence[SeriesValue], seen_at: datetime
) -> int:
    """Insert or update values of existing series; return how many rows were new or changed.

    `seen_at` is the current issue slot; a changed value gets at least that as available_at.
    Rerunning with the same values changes nothing and returns 0.
    """
    if not values:
        return 0
    params = (
        [value.series_id for value in values],
        [value.valid_at for value in values],
        [value.value for value in values],
        [value.coverage for value in values],
        [value.available_at for value in values],
        seen_at,
    )
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(UPSERT_SQL, params)
        return cursor.rowcount


def delete_values(
    conn: psycopg.Connection[TupleRow], series_id: str, valid_ats: Sequence[datetime]
) -> int:
    """Delete a series' values at these times; return how many rows were deleted."""
    if not valid_ats:
        return 0
    for valid_at in valid_ats:
        require_utc(valid_at, "valid_at")
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(DELETE_SQL, (series_id, list(valid_ats)))
        return cursor.rowcount


def fetch_values(
    conn: psycopg.Connection[TupleRow], series_id: str, start: datetime, end: datetime
) -> list[SeriesValue]:
    """Values with start <= valid_at < end, oldest first."""
    require_utc(start, "start")
    require_utc(end, "end")
    with conn.cursor(row_factory=class_row(ObservationRecord)) as cursor:
        cursor.execute(FETCH_SQL, (series_id, start, end))
        return [_to_value(record) for record in cursor]


def newest_value(
    conn: psycopg.Connection[TupleRow], series_id: str, at_or_before: datetime
) -> SeriesValue | None:
    """The newest value no later than `at_or_before`.

    The bound keeps reruns for past issue times from using data that wasn't there yet.
    """
    require_utc(at_or_before, "at_or_before")
    with conn.cursor(row_factory=class_row(ObservationRecord)) as cursor:
        cursor.execute(NEWEST_SQL, (series_id, at_or_before))
        record = cursor.fetchone()
    return None if record is None else _to_value(record)


def fetch_observations(
    conn: psycopg.Connection[TupleRow], station_id: str, start: datetime, end: datetime
) -> list[Observation]:
    """A station's levels with start <= observed_at < end, oldest first."""
    values = fetch_values(conn, level_series_id(station_id), start, end)
    return [Observation(station_id, value.valid_at, value.value) for value in values]


def newest_observation(
    conn: psycopg.Connection[TupleRow], station_id: str, at_or_before: datetime
) -> Observation | None:
    """A station's newest level no later than `at_or_before`."""
    value = newest_value(conn, level_series_id(station_id), at_or_before)
    return None if value is None else Observation(station_id, value.valid_at, value.value)


def _to_value(record: ObservationRecord) -> SeriesValue:
    # psycopg returns timestamps in the session time zone, which we don't control
    # through Neon's pooler, so convert explicitly.
    return SeriesValue(
        record.series_id,
        record.valid_at.astimezone(UTC),
        record.value,
        record.available_at.astimezone(UTC),
        record.coverage,
    )

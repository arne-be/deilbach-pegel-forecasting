"""Raw observations: idempotent upserts and time-window reads."""

from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg
from psycopg.rows import TupleRow, class_row

from pegel.adapters.storage.records import RawObservationRecord
from pegel.core.observations import Observation, require_utc

# One statement for the whole batch keeps backfills of a month to one round trip.
# Unchanged rows are skipped, so the returned count says what actually changed.
UPSERT_SQL = """
    INSERT INTO raw_observations (station_id, observed_at, level_m, source)
    SELECT station_id, observed_at, level_m, %(source)s
    FROM unnest(%(station_ids)s::text[], %(observed_ats)s::timestamptz[],
                %(levels)s::double precision[]) AS batch (station_id, observed_at, level_m)
    ON CONFLICT (station_id, observed_at) DO UPDATE
    SET level_m = excluded.level_m, source = excluded.source, ingested_at = now()
    WHERE (raw_observations.level_m, raw_observations.source)
        IS DISTINCT FROM (excluded.level_m, excluded.source)
"""

FETCH_SQL = """
    SELECT station_id, observed_at, level_m, source, ingested_at
    FROM raw_observations
    WHERE station_id = %s AND observed_at >= %s AND observed_at < %s
    ORDER BY observed_at
"""

NEWEST_SQL = """
    SELECT station_id, observed_at, level_m, source, ingested_at
    FROM raw_observations
    WHERE station_id = %s
    ORDER BY observed_at DESC
    LIMIT 1
"""


def upsert_observations(
    conn: psycopg.Connection[TupleRow],
    observations: Sequence[Observation],
    source: str,
) -> int:
    """Insert or update observations; return how many rows were new or changed.

    Rerunning with the same observations changes nothing and returns 0.
    """
    if not observations:
        return 0
    params = {
        "source": source,
        "station_ids": [observation.station_id for observation in observations],
        "observed_ats": [observation.observed_at for observation in observations],
        "levels": [observation.level_m for observation in observations],
    }
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(UPSERT_SQL, params)
        return cursor.rowcount


def fetch_observations(
    conn: psycopg.Connection[TupleRow],
    station_id: str,
    start: datetime,
    end: datetime,
) -> list[Observation]:
    """Observations with start <= observed_at < end, oldest first."""
    require_utc(start, "start")
    require_utc(end, "end")
    with conn.cursor(row_factory=class_row(RawObservationRecord)) as cursor:
        cursor.execute(FETCH_SQL, (station_id, start, end))
        return [_to_observation(record) for record in cursor]


def newest_observation(conn: psycopg.Connection[TupleRow], station_id: str) -> Observation | None:
    with conn.cursor(row_factory=class_row(RawObservationRecord)) as cursor:
        cursor.execute(NEWEST_SQL, (station_id,))
        record = cursor.fetchone()
    return None if record is None else _to_observation(record)


def _to_observation(record: RawObservationRecord) -> Observation:
    # psycopg returns timestamps in the session time zone, which we don't control
    # through Neon's pooler, so convert explicitly.
    return Observation(record.station_id, record.observed_at.astimezone(UTC), record.level_m)

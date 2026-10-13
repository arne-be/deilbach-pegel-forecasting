"""Forecasts made by others, e.g. ICON-D2 rain: idempotent upserts and the newest run."""

from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg
from psycopg.rows import TupleRow

from pegel.core.series import InputForecastValue

# Unchanged rows are skipped, so the returned count says what actually changed.
UPSERT_SQL = """
    INSERT INTO input_forecasts (series_id, run_at, valid_at, value)
    SELECT *
    FROM unnest(%s::text[], %s::timestamptz[], %s::timestamptz[], %s::double precision[])
    ON CONFLICT (series_id, run_at, valid_at) DO UPDATE
    SET value = excluded.value, fetched_at = now()
    WHERE input_forecasts.value IS DISTINCT FROM excluded.value
"""

NEWEST_RUN_SQL = "SELECT max(run_at) FROM input_forecasts WHERE series_id = %s"


def upsert_input_forecasts(
    conn: psycopg.Connection[TupleRow], values: Sequence[InputForecastValue]
) -> int:
    """Insert or update forecast values; return how many rows were new or changed."""
    if not values:
        return 0
    params = (
        [value.series_id for value in values],
        [value.run_at for value in values],
        [value.valid_at for value in values],
        [value.value for value in values],
    )
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(UPSERT_SQL, params)
        return cursor.rowcount


def newest_run_at(conn: psycopg.Connection[TupleRow], series_id: str) -> datetime | None:
    """The start of the newest stored run of this series, or None if there is none."""
    row = conn.execute(NEWEST_RUN_SQL, (series_id,)).fetchone()
    if row is None or row[0] is None:
        return None
    # Timestamps come back in the session time zone; the core types require UTC.
    run_at: datetime = row[0]
    return run_at.astimezone(UTC)

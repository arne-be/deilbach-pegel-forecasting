"""Forecasts made by others, e.g. ICON-D2 rain: idempotent upserts and the stored runs."""

from collections.abc import Sequence
from datetime import UTC, datetime

import psycopg
from psycopg.rows import TupleRow, class_row

from pegel.adapters.storage.records import InputForecastRecord
from pegel.core.observations import require_utc
from pegel.core.series import InputForecastValue

# Unchanged rows are skipped, so the returned count says what actually changed, and an
# unchanged value keeps its first available_at. A revised value is stamped no earlier than the
# issue slot that saw it, so a backfill can't date a revision back to the original value.
UPSERT_SQL = """
    INSERT INTO input_forecasts (series_id, run_at, valid_at, value, available_at)
    SELECT *
    FROM unnest(%s::text[], %s::timestamptz[], %s::timestamptz[], %s::double precision[],
                %s::timestamptz[])
    ON CONFLICT (series_id, run_at, valid_at) DO UPDATE
    SET value = excluded.value, available_at = greatest(excluded.available_at, %s::timestamptz),
        fetched_at = now()
    WHERE input_forecasts.value IS DISTINCT FROM excluded.value
"""

FETCH_SQL = """
    SELECT series_id, run_at, valid_at, value, fetched_at, kind, available_at
    FROM input_forecasts
    WHERE series_id = %s AND valid_at >= %s AND valid_at < %s
    ORDER BY valid_at, run_at
"""

RUNS_SINCE_SQL = "SELECT DISTINCT run_at FROM input_forecasts WHERE series_id = %s AND run_at >= %s"


def upsert_input_forecasts(
    conn: psycopg.Connection[TupleRow], values: Sequence[InputForecastValue], seen_at: datetime
) -> int:
    """Insert or update forecast values; return how many rows were new or changed.

    `seen_at` is the current issue slot; a changed value gets at least that as available_at.
    """
    if not values:
        return 0
    params = (
        [value.series_id for value in values],
        [value.run_at for value in values],
        [value.valid_at for value in values],
        [value.value for value in values],
        [value.available_at for value in values],
        seen_at,
    )
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(UPSERT_SQL, params)
        return cursor.rowcount


def stored_runs_since(
    conn: psycopg.Connection[TupleRow], series_id: str, since: datetime
) -> set[datetime]:
    """The starts of the stored runs of this series from `since` on."""
    rows = conn.execute(RUNS_SINCE_SQL, (series_id, since)).fetchall()
    # Timestamps come back in the session time zone; the core types require UTC.
    return {row[0].astimezone(UTC) for row in rows}


def fetch_input_forecasts(
    conn: psycopg.Connection[TupleRow], series_id: str, start: datetime, end: datetime
) -> list[InputForecastValue]:
    """Values of every stored run with start <= valid_at < end, by valid_at, then run_at."""
    require_utc(start, "start")
    require_utc(end, "end")
    with conn.cursor(row_factory=class_row(InputForecastRecord)) as cursor:
        cursor.execute(FETCH_SQL, (series_id, start, end))
        # Timestamps come back in the session time zone; the core types require UTC.
        return [
            InputForecastValue(
                record.series_id,
                record.run_at.astimezone(UTC),
                record.valid_at.astimezone(UTC),
                record.value,
                record.available_at.astimezone(UTC),
            )
            for record in cursor
        ]

"""Series metadata. Jobs ensure their series exist before they write values."""

from collections.abc import Sequence

import psycopg
from psycopg.rows import TupleRow

from pegel.core.series import Series

# Unchanged rows are skipped, so the returned count says what actually changed.
# Kind, variable and unit are never updated here: ensure_series rejects a change first.
ENSURE_SQL = """
    INSERT INTO series (id, variable, unit, source, location, kind, aggregation, period,
                        description)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::text[],
                %s::text[], %s::interval[], %s::text[])
    ON CONFLICT (id) DO UPDATE
    SET source = excluded.source, location = excluded.location,
        aggregation = excluded.aggregation, period = excluded.period,
        description = excluded.description
    WHERE (series.source, series.location, series.aggregation, series.period, series.description)
        IS DISTINCT FROM (excluded.source, excluded.location, excluded.aggregation,
                          excluded.period, excluded.description)
"""

STORED_DEFINITIONS_SQL = (
    "SELECT id, kind, variable, unit FROM series WHERE id = ANY(%s) ORDER BY id FOR UPDATE"
)


class SeriesDefinitionChangeError(Exception):
    """A stored series differs in kind, variable or unit.

    Changing any of them would relabel the stored values without converting them.
    Migrate the values instead.
    """


def ensure_series(conn: psycopg.Connection[TupleRow], series: Sequence[Series]) -> int:
    """Insert or update series rows; return how many were new or changed.

    Source, location, aggregation, period and description may change. Raises
    SeriesDefinitionChangeError, and changes nothing, if a stored series has another kind,
    variable or unit.
    """
    if not series:
        return 0
    params = (
        [one.id for one in series],
        [one.variable for one in series],
        [one.unit for one in series],
        [one.source for one in series],
        [one.location for one in series],
        [one.kind for one in series],
        [one.aggregation for one in series],
        [one.period for one in series],
        [one.description for one in series],
    )
    wanted = {one.id: (one.kind, one.variable, one.unit) for one in series}
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(STORED_DEFINITIONS_SQL, (list(wanted),))
        for series_id, *stored in cursor.fetchall():
            if tuple(stored) != wanted[series_id]:
                raise SeriesDefinitionChangeError(
                    f"series {series_id!r} is stored as (kind, variable, unit) "
                    f"{tuple(stored)!r}, not {wanted[series_id]!r}"
                )
        cursor.execute(ENSURE_SQL, params)
        return cursor.rowcount

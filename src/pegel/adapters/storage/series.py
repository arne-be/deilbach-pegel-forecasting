"""Series metadata. Jobs ensure their series exist before they write values."""

from collections.abc import Sequence

import psycopg
from psycopg.rows import TupleRow

from pegel.core.series import Series

# Unchanged rows are skipped, so the returned count says what actually changed.
ENSURE_SQL = """
    INSERT INTO series (id, variable, unit, source, location, aggregation, period, description)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::text[],
                %s::interval[], %s::text[])
    ON CONFLICT (id) DO UPDATE
    SET variable = excluded.variable, unit = excluded.unit, source = excluded.source,
        location = excluded.location, aggregation = excluded.aggregation,
        period = excluded.period, description = excluded.description
    WHERE (series.variable, series.unit, series.source, series.location, series.aggregation,
           series.period, series.description)
        IS DISTINCT FROM (excluded.variable, excluded.unit, excluded.source, excluded.location,
                          excluded.aggregation, excluded.period, excluded.description)
"""


def ensure_series(conn: psycopg.Connection[TupleRow], series: Sequence[Series]) -> int:
    """Insert or update series rows; return how many were new or changed."""
    if not series:
        return 0
    params = (
        [one.id for one in series],
        [one.variable for one in series],
        [one.unit for one in series],
        [one.source for one in series],
        [one.location for one in series],
        [one.aggregation for one in series],
        [one.period for one in series],
        [one.description for one in series],
    )
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(ENSURE_SQL, params)
        return cursor.rowcount

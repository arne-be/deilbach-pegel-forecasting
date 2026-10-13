"""Series metadata. Jobs ensure their series exist before they write values."""

from collections.abc import Sequence

import psycopg
from psycopg.rows import TupleRow

from pegel.core.series import Series

# Unchanged rows are skipped, so the returned count says what actually changed.
# The kind is never updated here: ensure_series rejects a change before this runs.
ENSURE_SQL = """
    INSERT INTO series (id, variable, unit, source, location, kind, aggregation, period,
                        description)
    SELECT *
    FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s::text[],
                %s::text[], %s::interval[], %s::text[])
    ON CONFLICT (id) DO UPDATE
    SET variable = excluded.variable, unit = excluded.unit, source = excluded.source,
        location = excluded.location, aggregation = excluded.aggregation,
        period = excluded.period, description = excluded.description
    WHERE (series.variable, series.unit, series.source, series.location, series.aggregation,
           series.period, series.description)
        IS DISTINCT FROM (excluded.variable, excluded.unit, excluded.source, excluded.location,
                          excluded.aggregation, excluded.period, excluded.description)
"""

STORED_KINDS_SQL = "SELECT id, kind FROM series WHERE id = ANY(%s) FOR UPDATE"


class SeriesKindChangeError(Exception):
    """A series exists with the other kind. Changing it would orphan or mislabel its values."""


def ensure_series(conn: psycopg.Connection[TupleRow], series: Sequence[Series]) -> int:
    """Insert or update series rows; return how many were new or changed.

    Raises SeriesKindChangeError, and changes nothing, if a series exists with another kind.
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
    wanted_kinds = {one.id: one.kind for one in series}
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(STORED_KINDS_SQL, (list(wanted_kinds),))
        for series_id, stored_kind in cursor.fetchall():
            if stored_kind != wanted_kinds[series_id]:
                raise SeriesKindChangeError(
                    f"series {series_id!r} is stored with kind {stored_kind!r}, "
                    f"not {wanted_kinds[series_id]!r}"
                )
        cursor.execute(ENSURE_SQL, params)
        return cursor.rowcount

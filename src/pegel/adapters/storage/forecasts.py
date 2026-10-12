"""Forecasts and their points: idempotent saves and the newest forecast per model."""

from datetime import UTC

import psycopg
from psycopg.rows import TupleRow, class_row

from pegel.adapters.storage.records import ForecastPointRecord, ForecastRecord
from pegel.core.forecasts import Forecast, ForecastPoint

UPSERT_FORECAST_SQL = """
    INSERT INTO forecasts (station_id, model, issued_at, newest_observation_at)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (station_id, model, issued_at) DO UPDATE
    SET newest_observation_at = excluded.newest_observation_at
    RETURNING id
"""

DELETE_POINTS_SQL = "DELETE FROM forecast_points WHERE forecast_id = %s"

INSERT_POINTS_SQL = """
    INSERT INTO forecast_points (forecast_id, valid_at, level_m)
    SELECT %s, valid_at, level_m
    FROM unnest(%s::timestamptz[], %s::double precision[]) AS batch (valid_at, level_m)
"""

NEWEST_FORECAST_SQL = """
    SELECT id, station_id, model, issued_at, newest_observation_at, created_at
    FROM forecasts
    WHERE station_id = %s AND model = %s
    ORDER BY issued_at DESC
    LIMIT 1
"""

POINTS_SQL = """
    SELECT forecast_id, valid_at, level_m
    FROM forecast_points
    WHERE forecast_id = %s
    ORDER BY valid_at
"""


def save_forecast(conn: psycopg.Connection[TupleRow], forecast: Forecast) -> None:
    """Store a forecast. A rerun for the same station, model and issue time replaces it."""
    with conn.transaction(), conn.cursor() as cursor:
        cursor.execute(
            UPSERT_FORECAST_SQL,
            (
                forecast.station_id,
                forecast.model,
                forecast.issued_at,
                forecast.newest_observation_at,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("forecast upsert returned no id")
        forecast_id = row[0]
        # Replacing all points is simpler than diffing them, and a rerun may
        # produce a different set of lead times.
        cursor.execute(DELETE_POINTS_SQL, (forecast_id,))
        cursor.execute(
            INSERT_POINTS_SQL,
            (
                forecast_id,
                [point.valid_at for point in forecast.points],
                [point.level_m for point in forecast.points],
            ),
        )


def newest_forecast(
    conn: psycopg.Connection[TupleRow], station_id: str, model: str
) -> Forecast | None:
    """The forecast with the latest issue time for this station and model."""
    with conn.cursor(row_factory=class_row(ForecastRecord)) as cursor:
        cursor.execute(NEWEST_FORECAST_SQL, (station_id, model))
        forecast_record = cursor.fetchone()
    if forecast_record is None:
        return None
    with conn.cursor(row_factory=class_row(ForecastPointRecord)) as cursor:
        cursor.execute(POINTS_SQL, (forecast_record.id,))
        points = tuple(
            ForecastPoint(record.valid_at.astimezone(UTC), record.level_m) for record in cursor
        )
    # Timestamps come back in the session time zone; the core types require UTC.
    return Forecast(
        station_id=forecast_record.station_id,
        model=forecast_record.model,
        issued_at=forecast_record.issued_at.astimezone(UTC),
        newest_observation_at=forecast_record.newest_observation_at.astimezone(UTC),
        points=points,
    )

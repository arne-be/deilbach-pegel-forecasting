"""Forecasts, their points and bands: idempotent saves and the newest forecast per model."""

from collections import defaultdict
from datetime import UTC, datetime

import psycopg
from psycopg.rows import TupleRow, class_row

from pegel.adapters.storage.records import (
    ForecastBandRecord,
    ForecastPointRecord,
    ForecastRecord,
)
from pegel.core.forecasts import Band, Forecast, ForecastPoint

UPSERT_FORECAST_SQL = """
    INSERT INTO forecasts (station_id, model, issued_at, newest_observation_at, situation)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (station_id, model, issued_at) DO UPDATE
    SET newest_observation_at = excluded.newest_observation_at, situation = excluded.situation
    RETURNING id
"""

# Deleting the points deletes their bands too (ON DELETE CASCADE).
DELETE_POINTS_SQL = "DELETE FROM forecast_points WHERE forecast_id = %s"

INSERT_POINTS_SQL = """
    INSERT INTO forecast_points (forecast_id, valid_at, level_cm)
    SELECT %s, valid_at, level_cm
    FROM unnest(%s::timestamptz[], %s::double precision[]) AS batch (valid_at, level_cm)
"""

INSERT_BANDS_SQL = """
    INSERT INTO forecast_bands (forecast_id, valid_at, coverage_percent, lower_cm, upper_cm)
    SELECT %s, valid_at, coverage_percent, lower_cm, upper_cm
    FROM unnest(%s::timestamptz[], %s::integer[], %s::double precision[], %s::double precision[])
        AS batch (valid_at, coverage_percent, lower_cm, upper_cm)
"""

NEWEST_FORECAST_SQL = """
    SELECT id, station_id, model, issued_at, newest_observation_at, created_at, situation
    FROM forecasts
    WHERE station_id = %s AND model = %s
    ORDER BY issued_at DESC
    LIMIT 1
"""

POINTS_SQL = """
    SELECT forecast_id, valid_at, level_cm
    FROM forecast_points
    WHERE forecast_id = %s
    ORDER BY valid_at
"""

BANDS_SQL = """
    SELECT forecast_id, valid_at, coverage_percent, lower_cm, upper_cm
    FROM forecast_bands
    WHERE forecast_id = %s
    ORDER BY valid_at, coverage_percent
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
                forecast.situation,
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
                [point.level_cm for point in forecast.points],
            ),
        )
        bands = [(point.valid_at, band) for point in forecast.points for band in point.bands]
        cursor.execute(
            INSERT_BANDS_SQL,
            (
                forecast_id,
                [valid_at for valid_at, _ in bands],
                [band.coverage_percent for _, band in bands],
                [band.lower_cm for _, band in bands],
                [band.upper_cm for _, band in bands],
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
    bands: defaultdict[datetime, list[Band]] = defaultdict(list)
    with conn.cursor(row_factory=class_row(ForecastBandRecord)) as cursor:
        cursor.execute(BANDS_SQL, (forecast_record.id,))
        for band in cursor:
            bands[band.valid_at].append(Band(band.coverage_percent, band.lower_cm, band.upper_cm))
    with conn.cursor(row_factory=class_row(ForecastPointRecord)) as cursor:
        cursor.execute(POINTS_SQL, (forecast_record.id,))
        points = tuple(
            ForecastPoint(
                record.valid_at.astimezone(UTC), record.level_cm, tuple(bands[record.valid_at])
            )
            for record in cursor
        )
    # Timestamps come back in the session time zone; the core types require UTC.
    return Forecast(
        station_id=forecast_record.station_id,
        model=forecast_record.model,
        issued_at=forecast_record.issued_at.astimezone(UTC),
        newest_observation_at=forecast_record.newest_observation_at.astimezone(UTC),
        points=points,
        situation=forecast_record.situation,
    )

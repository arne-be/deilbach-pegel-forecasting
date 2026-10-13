"""Migrations that move data, run up and down on their own throwaway database."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from conftest import MIGRATIONS_DIR, migrate_down_section, migrate_up_section
from psycopg.rows import TupleRow

Conn = psycopg.Connection[TupleRow]
SERIES_MIGRATION = "20261013150000"
AT = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
INGESTED_AT = datetime(2026, 10, 12, 9, 5, tzinfo=UTC)
RAW_ROWS = [
    ("kupferdreh", AT, -0.21, "influx", INGESTED_AT),
    ("kupferdreh", AT.replace(hour=10), 0.28, "influx", INGESTED_AT),
    ("langenberg", AT, 0.4, "lanuv", INGESTED_AT),
]


@pytest.fixture
def empty_conn(database_url: str) -> Iterator[Conn]:
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS migration_test")
        admin.execute("CREATE DATABASE migration_test")
    with psycopg.connect(database_url.rsplit("/", 1)[0] + "/migration_test") as connection:
        connection.execute("SET TIME ZONE 'UTC'")
        yield connection


def migration(version: str) -> Path:
    return next(MIGRATIONS_DIR.glob(f"{version}_*.sql"))


def up(conn: Conn, path: Path) -> None:
    with conn.transaction():
        conn.execute(migrate_up_section(path.read_text(encoding="utf-8")))


def down(conn: Conn, path: Path) -> None:
    with conn.transaction():
        conn.execute(migrate_down_section(path.read_text(encoding="utf-8")))


@pytest.fixture
def before_series(empty_conn: Conn) -> Conn:
    """A database migrated up to just before the series tables, with a few raw rows."""
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name < SERIES_MIGRATION:
            up(empty_conn, path)
    with empty_conn.cursor() as cursor:
        cursor.executemany("INSERT INTO raw_observations VALUES (%s, %s, %s, %s, %s)", RAW_ROWS)
    return empty_conn


def raw_rows(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT station_id, observed_at, level_m, source, ingested_at FROM raw_observations"
        " ORDER BY station_id, observed_at"
    ).fetchall()


def test_series_migration_moves_levels(before_series: Conn) -> None:
    up(before_series, migration(SERIES_MIGRATION))
    series = before_series.execute(
        "SELECT id, variable, unit, source, location FROM series ORDER BY id"
    ).fetchall()
    observations = before_series.execute(
        "SELECT series_id, valid_at, value, coverage, ingested_at FROM observations"
        " ORDER BY series_id, valid_at"
    ).fetchall()
    assert series == [
        ("kupferdreh:level", "level", "m", "influx", "kupferdreh"),
        ("langenberg:level", "level", "m", "lanuv", "langenberg"),
    ]
    assert observations == [
        (f"{station}:level", observed_at, level, None, ingested_at)
        for station, observed_at, level, _, ingested_at in RAW_ROWS
    ]


def test_series_migration_down_restores_raw_observations(before_series: Conn) -> None:
    up(before_series, migration(SERIES_MIGRATION))
    down(before_series, migration(SERIES_MIGRATION))
    assert raw_rows(before_series) == RAW_ROWS


CENTIMETRES_MIGRATION = "20261013160000"


@pytest.fixture
def before_centimetres(before_series: Conn) -> Conn:
    """Levels in metres in the series tables, a rain series and a forecast point."""
    up(before_series, migration(SERIES_MIGRATION))
    before_series.execute(
        "INSERT INTO series (id, variable, unit, source, location)"
        " VALUES ('radar:zone', 'rain', 'mm', 'radar', 'zone')"
    )
    before_series.execute("INSERT INTO observations VALUES ('radar:zone', %s, 1.5, 0.5)", (AT,))
    before_series.execute(
        "INSERT INTO forecasts (station_id, model, issued_at, newest_observation_at)"
        " VALUES ('kupferdreh', 'persistence', %s, %s)",
        (AT, AT),
    )
    before_series.execute(
        "INSERT INTO forecast_points SELECT id, %s, 0.229 FROM forecasts", (AT.replace(hour=10),)
    )
    return before_series


def values(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT o.series_id, s.unit, o.value FROM observations o"
        " JOIN series s ON s.id = o.series_id"
        " ORDER BY o.series_id, o.valid_at"
    ).fetchall()


def test_centimetres_migration_scales_levels_only(before_centimetres: Conn) -> None:
    up(before_centimetres, migration(CENTIMETRES_MIGRATION))
    points = before_centimetres.execute("SELECT level_cm FROM forecast_points").fetchall()
    assert values(before_centimetres) == [
        ("kupferdreh:level", "cm", -21.0),
        ("kupferdreh:level", "cm", 28.0),
        ("langenberg:level", "cm", 40.0),
        ("radar:zone", "mm", 1.5),
    ]
    # 0.229 * 100 is 22.900000000000002 in floating point; the migration rounds it off.
    assert points == [(22.9,)]


def test_centimetres_migration_down_restores_metres(before_centimetres: Conn) -> None:
    before = values(before_centimetres)
    up(before_centimetres, migration(CENTIMETRES_MIGRATION))
    down(before_centimetres, migration(CENTIMETRES_MIGRATION))
    points = before_centimetres.execute("SELECT level_m FROM forecast_points").fetchall()
    assert (values(before_centimetres), points) == (before, [(0.229,)])

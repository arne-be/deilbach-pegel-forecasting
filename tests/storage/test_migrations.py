"""Migrations that move data, run up and down on their own throwaway database."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from conftest import MIGRATIONS_DIR, migrate_down_section, migrate_up_section
from psycopg.rows import TupleRow

from pegel.core.schedule import scheduled_available_at

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


KIND_MIGRATION = "20261013170000"


@pytest.fixture
def before_kind(before_centimetres: Conn) -> Conn:
    up(before_centimetres, migration(CENTIMETRES_MIGRATION))
    return before_centimetres


def add_forecast_series(conn: Conn, series_id: str) -> None:
    conn.execute(
        "INSERT INTO series (id, variable, unit, source, location)"
        " VALUES (%s, 'rain', 'mm', 'icon_d2', 'catchment')",
        (series_id,),
    )
    conn.execute(
        "INSERT INTO input_forecasts (series_id, run_at, valid_at, value) VALUES (%s, %s, %s, 0.4)",
        (series_id, AT, AT.replace(hour=10)),
    )


def test_kind_migration_sets_the_kind_from_the_data(before_kind: Conn) -> None:
    add_forecast_series(before_kind, "icon_d2:catchment")
    up(before_kind, migration(KIND_MIGRATION))
    kinds = before_kind.execute("SELECT id, kind FROM series ORDER BY id").fetchall()
    assert kinds == [
        ("icon_d2:catchment", "forecast"),
        ("kupferdreh:level", "observation"),
        ("langenberg:level", "observation"),
        ("radar:zone", "observation"),
    ]


def test_kind_migration_stops_on_a_series_in_both_tables(before_kind: Conn) -> None:
    before_kind.execute(
        "INSERT INTO input_forecasts (series_id, run_at, valid_at, value)"
        " VALUES ('radar:zone', %s, %s, 0.4)",
        (AT, AT.replace(hour=10)),
    )
    with pytest.raises(psycopg.errors.RaiseException, match="radar:zone"):
        up(before_kind, migration(KIND_MIGRATION))


def test_kind_migration_rejects_forecasts_of_observation_series(before_kind: Conn) -> None:
    up(before_kind, migration(KIND_MIGRATION))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        before_kind.execute(
            "INSERT INTO input_forecasts (series_id, run_at, valid_at, value)"
            " VALUES ('radar:zone', %s, %s, 1.0)",
            (AT, AT.replace(hour=10)),
        )


def test_kind_migration_down_restores_the_tables(before_kind: Conn) -> None:
    def columns() -> list[tuple[object, ...]]:
        return before_kind.execute(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
        ).fetchall()

    add_forecast_series(before_kind, "icon_d2:catchment")
    before = (columns(), values(before_kind))
    up(before_kind, migration(KIND_MIGRATION))
    down(before_kind, migration(KIND_MIGRATION))
    assert (columns(), values(before_kind)) == before
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        before_kind.execute("INSERT INTO observations VALUES ('nowhere', %s, 1.0)", (AT,))


AVAILABLE_AFTER_MIGRATION = "20261013180000"
# The delays the migration gives existing rows, copied from config/pegel.json at the time.
INFLUX_MINUTES = 5
LANUV_MINUTES = 15
LANGENBERG_MINUTES = 75
RADOLAN_MINUTES = 35
OPEN_METEO_MINUTES = 120
# The issue minute in config/pegel.json when the migration was written; it's fixed in its SQL.
MIGRATION_ISSUE_MINUTE = 30


@pytest.fixture
def before_available_after(before_kind: Conn) -> Conn:
    """Every known source, with radar:zone renamed from the old test source to radolan_rw."""
    up(before_kind, migration(KIND_MIGRATION))
    before_kind.execute("UPDATE series SET source = 'radolan_rw' WHERE id = 'radar:zone'")
    before_kind.execute(
        "INSERT INTO series (id, variable, unit, source, location, kind) VALUES"
        " ('nierenhof:level', 'level', 'cm', 'lanuv', 'nierenhof', 'observation'),"
        " ('langenberg:cleaned', 'level', 'cm', 'pegel', 'langenberg', 'observation')"
    )
    for source in ("open_meteo_icon_d2", "open_meteo_previous_runs"):
        before_kind.execute(
            "INSERT INTO series (id, variable, unit, source, location, kind)"
            " VALUES (%s, 'rain', 'mm', %s, 'catchment', 'forecast')",
            (f"{source}:catchment", source),
        )
    return before_kind


def test_available_after_migration_fills_it_by_source(before_available_after: Conn) -> None:
    up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))
    delays = before_available_after.execute(
        "SELECT id, available_after FROM series ORDER BY id"
    ).fetchall()
    assert delays == [
        ("kupferdreh:level", timedelta(minutes=INFLUX_MINUTES)),
        # Derived from the Langenberg level in the same run, so as late as that level.
        ("langenberg:cleaned", timedelta(minutes=LANGENBERG_MINUTES)),
        ("langenberg:level", timedelta(minutes=LANGENBERG_MINUTES)),
        ("nierenhof:level", timedelta(minutes=LANUV_MINUTES)),
        ("open_meteo_icon_d2:catchment", timedelta(minutes=OPEN_METEO_MINUTES)),
        ("open_meteo_previous_runs:catchment", timedelta(minutes=OPEN_METEO_MINUTES)),
        ("radar:zone", timedelta(minutes=RADOLAN_MINUTES)),
    ]


def test_available_after_migration_stops_on_a_derived_series_without_its_level(
    before_available_after: Conn,
) -> None:
    before_available_after.execute(
        "UPDATE series SET location = 'nowhere' WHERE id = 'langenberg:cleaned'"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="langenberg:cleaned"):
        up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))


def test_available_after_migration_stops_on_an_unknown_source(
    before_available_after: Conn,
) -> None:
    before_available_after.execute("UPDATE series SET source = 'radar' WHERE id = 'radar:zone'")
    with pytest.raises(psycopg.errors.RaiseException, match=r"radar:zone \(radar\)"):
        up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))


def test_available_after_migration_rejects_a_negative_delay(
    before_available_after: Conn,
) -> None:
    up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))
    with pytest.raises(psycopg.errors.CheckViolation):
        before_available_after.execute(
            "UPDATE series SET available_after = interval '-1 minute' WHERE id = 'radar:zone'"
        )


def test_available_after_migration_down_drops_the_column(before_available_after: Conn) -> None:
    def series_rows() -> list[tuple[object, ...]]:
        return before_available_after.execute("SELECT * FROM series ORDER BY id").fetchall()

    before = series_rows()
    up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))
    down(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))
    assert series_rows() == before


def test_available_at_migration_matches_the_python_rule(before_available_after: Conn) -> None:
    delay = timedelta(minutes=INFLUX_MINUTES)
    on_the_run = AT.replace(minute=30) - delay
    valid_times = [
        on_the_run,
        on_the_run + timedelta(microseconds=1),
        on_the_run - timedelta(seconds=1),
        AT.replace(hour=23, minute=59),
    ]
    with before_available_after.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO observations (series_id, valid_at, value)"
            " VALUES ('kupferdreh:level', %s, 1)",
            [(valid_at,) for valid_at in valid_times],
        )
    before_available_after.execute(
        "INSERT INTO input_forecasts (series_id, run_at, valid_at, value)"
        " VALUES ('open_meteo_icon_d2:catchment', %s, %s, 0.4)",
        (AT, AT.replace(hour=12)),
    )
    up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))
    rows = before_available_after.execute(
        "SELECT o.valid_at, s.available_after, o.available_at FROM observations o"
        " JOIN series s ON s.id = o.series_id"
        " UNION ALL"
        " SELECT f.run_at, s.available_after, f.available_at FROM input_forecasts f"
        " JOIN series s ON s.id = f.series_id"
    ).fetchall()
    assert len(rows) == len(RAW_ROWS) + 1 + len(valid_times) + 1
    for known_at, available_after, available_at in rows:
        expected = scheduled_available_at(known_at, available_after, MIGRATION_ISSUE_MINUTE)
        assert available_at == expected, known_at


def test_available_at_migration_rejects_values_available_before_their_time(
    before_available_after: Conn,
) -> None:
    up(before_available_after, migration(AVAILABLE_AFTER_MIGRATION))
    with pytest.raises(psycopg.errors.CheckViolation):
        before_available_after.execute(
            "UPDATE observations SET available_at = valid_at - interval '1 second'"
        )

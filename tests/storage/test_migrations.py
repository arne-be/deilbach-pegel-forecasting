"""Migrations that move data, run up and down on their own throwaway database."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from conftest import MIGRATIONS_DIR, migrate_down_section, migrate_up_section
from psycopg.rows import TupleRow

from pegel.config import load_config
from pegel.core.schedule import scheduled_available_at
from pegel.core.series import level_series_id

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


AVAILABLE_AT_MIGRATION = "20261013180000"
LANGENBERG_MIGRATION = "20261014130000"
LANUV_MIGRATION = "20261014150000"
LATER_DELAYS = {
    "langenberg:level": timedelta(minutes=25),  # LANGENBERG_MIGRATION
    "nierenhof:level": timedelta(minutes=25),  # LANUV_MIGRATION
    "neviges:level": timedelta(minutes=25),  # LANUV_MIGRATION
}
# The issue minute in config/pegel.json when the migration was written; it's fixed in its SQL.
MIGRATION_ISSUE_MINUTE = 30


def migration_delays() -> dict[str, timedelta]:
    """The migration's delay table, by series id or source."""
    sql = migration(AVAILABLE_AT_MIGRATION).read_text(encoding="utf-8")
    pairs = re.findall(r"\('([^']+)', interval '(\d+) minutes'\)", sql)
    return {key: timedelta(minutes=int(minutes)) for key, minutes in pairs}


def test_available_at_migration_delays_match_the_config() -> None:
    config = load_config()
    expected = {
        level_series_id(station.id): timedelta(minutes=station.available_after_minutes)
        for station in config.stations
    }
    for rain in (config.rain.radar, config.rain.forecast):
        expected[rain.source] = timedelta(minutes=rain.available_after_minutes)
    expected[config.rain.forecast.archive_source] = timedelta(
        minutes=config.rain.forecast.available_after_minutes
    )
    # Delays changed later move stored rows in their own migration.
    assert migration_delays() | LATER_DELAYS == expected


@pytest.fixture
def before_available_at(before_kind: Conn) -> Conn:
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


def test_available_at_migration_matches_the_python_rule(before_available_at: Conn) -> None:
    delays = migration_delays()
    series_delays = {
        "kupferdreh:level": delays["kupferdreh:level"],
        # Derived from the Langenberg level in the same run, so as late as that level.
        "langenberg:cleaned": delays["langenberg:level"],
        "langenberg:level": delays["langenberg:level"],
        "nierenhof:level": delays["nierenhof:level"],
        "open_meteo_icon_d2:catchment": delays["open_meteo_icon_d2"],
        "open_meteo_previous_runs:catchment": delays["open_meteo_previous_runs"],
        "radar:zone": delays["radolan_rw"],
    }
    with before_available_at.cursor() as cursor:
        for series_id, delay in series_delays.items():
            # Exactly on a run, just after it and just before it: a delay off by any amount
            # moves one of them to another run.
            on_the_run = AT.replace(minute=30) - delay
            for known_at in (
                on_the_run,
                on_the_run + timedelta(microseconds=1),
                on_the_run - timedelta(seconds=1),
                AT.replace(hour=23, minute=59),
            ):
                if series_id.startswith("open_meteo"):
                    cursor.execute(
                        "INSERT INTO input_forecasts (series_id, run_at, valid_at, value)"
                        " VALUES (%s, %s, %s, 0.4)",
                        (series_id, known_at, known_at + timedelta(hours=1)),
                    )
                else:
                    cursor.execute(
                        "INSERT INTO observations (series_id, valid_at, value)"
                        " VALUES (%s, %s, 1) ON CONFLICT DO NOTHING",
                        (series_id, known_at),
                    )
    up(before_available_at, migration(AVAILABLE_AT_MIGRATION))
    rows = before_available_at.execute(
        "SELECT series_id, valid_at, available_at FROM observations"
        " UNION ALL SELECT series_id, run_at, available_at FROM input_forecasts"
    ).fetchall()
    assert len(rows) >= 4 * len(series_delays)
    for series_id, known_at, available_at in rows:
        expected = scheduled_available_at(
            known_at, series_delays[series_id], MIGRATION_ISSUE_MINUTE
        )
        assert available_at == expected, (series_id, known_at)


def test_available_at_migration_stops_on_a_derived_series_without_its_level(
    before_available_at: Conn,
) -> None:
    before_available_at.execute(
        "UPDATE series SET location = 'nowhere' WHERE id = 'langenberg:cleaned'"
    )
    with pytest.raises(psycopg.errors.RaiseException, match="langenberg:cleaned"):
        up(before_available_at, migration(AVAILABLE_AT_MIGRATION))


def test_available_at_migration_stops_on_an_unknown_source(before_available_at: Conn) -> None:
    before_available_at.execute("UPDATE series SET source = 'radar' WHERE id = 'radar:zone'")
    with pytest.raises(psycopg.errors.RaiseException, match=r"radar:zone \(radar\)"):
        up(before_available_at, migration(AVAILABLE_AT_MIGRATION))


def test_available_at_migration_down_drops_the_columns(before_available_at: Conn) -> None:
    def tables() -> list[list[tuple[object, ...]]]:
        return [
            before_available_at.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()
            for table in ("series", "observations", "input_forecasts")
        ]

    before = tables()
    up(before_available_at, migration(AVAILABLE_AT_MIGRATION))
    down(before_available_at, migration(AVAILABLE_AT_MIGRATION))
    assert tables() == before


def test_available_at_migration_rejects_values_available_before_their_time(
    before_available_at: Conn,
) -> None:
    up(before_available_at, migration(AVAILABLE_AT_MIGRATION))
    with pytest.raises(psycopg.errors.CheckViolation):
        before_available_at.execute(
            "UPDATE observations SET available_at = valid_at - interval '1 second'"
        )


SHIFT_MIGRATION = "20261014120000"
SHIFT_AT = datetime(2026, 10, 13, 9, 22, tzinfo=UTC)
SHIFT_STAMP = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


def migration_offset() -> float:
    """The offset the shift migration adds, read from its SQL."""
    sql = migration(SHIFT_MIGRATION).read_text(encoding="utf-8")
    up_sql = migrate_up_section(sql)
    [offset] = set(re.findall(r"::numeric \+ (\d+), 3\)", up_sql))
    return float(offset)


def test_shift_migration_offset_matches_the_config() -> None:
    assert migration_offset() == load_config().station("kupferdreh").level_offset_cm


@pytest.fixture
def before_shift(before_available_at: Conn) -> Conn:
    """Every migration before the shift, with Kupferdreh raw, cleaned and LANUV levels."""
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if AVAILABLE_AT_MIGRATION <= path.name < SHIFT_MIGRATION:
            up(before_available_at, path)
    before_available_at.execute("DELETE FROM observations")
    before_available_at.execute(
        "INSERT INTO series (id, variable, unit, source, location, kind) VALUES"
        " ('kupferdreh:cleaned_kalman', 'level', 'cm', 'pegel', 'kupferdreh', 'observation')"
    )
    with before_available_at.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO observations (series_id, valid_at, value, available_at)"
            " VALUES (%s, %s, %s, %s)",
            [
                ("kupferdreh:level", SHIFT_AT, -39.2, SHIFT_STAMP),
                ("kupferdreh:level", SHIFT_AT - timedelta(hours=1), 12.345, SHIFT_STAMP),
                ("kupferdreh:cleaned_kalman", SHIFT_AT, -39.2, SHIFT_STAMP),
                ("langenberg:level", SHIFT_AT, -3.5, SHIFT_STAMP),
            ],
        )
    return before_available_at


def shifted_rows(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT series_id, valid_at, value, available_at, ingested_at FROM observations"
        " UNION ALL SELECT 'forecast', valid_at, level_cm, NULL, NULL FROM forecast_points"
        " ORDER BY 1, 2"
    ).fetchall()


def test_shift_migration_moves_kupferdreh_levels_only(before_shift: Conn) -> None:
    before = shifted_rows(before_shift)
    up(before_shift, migration(SHIFT_MIGRATION))
    after = shifted_rows(before_shift)
    assert [row[2] for row in after] == [67.9, 5.8, 57.345, 5.8, -3.5]
    assert [row[:2] + row[3:] for row in after] == [row[:2] + row[3:] for row in before]


def test_shift_migration_matches_the_ingest_rounding(empty_conn: Conn) -> None:
    # The ingest must store the very same double, or the next run revises every row.
    levels = [round(i * 0.1 - 60, 1) for i in range(2000)] + [
        round(i * 0.007 - 40, 3) for i in range(2000)
    ]
    shifted = empty_conn.execute(
        "SELECT array_agg(round(level::numeric + 45, 3)::double precision ORDER BY n)"
        " FROM unnest(%s::double precision[]) WITH ORDINALITY AS t (level, n)",
        (levels,),
    ).fetchone()
    assert shifted is not None
    assert shifted[0] == [round(level + 45, 3) for level in levels]


def test_shift_migration_stops_when_already_shifted(before_shift: Conn) -> None:
    up(before_shift, migration(SHIFT_MIGRATION))
    with pytest.raises(psycopg.errors.RaiseException, match="already shifted"):
        up(before_shift, migration(SHIFT_MIGRATION))


def test_shift_migration_down_restores_the_levels(before_shift: Conn) -> None:
    before = shifted_rows(before_shift)
    up(before_shift, migration(SHIFT_MIGRATION))
    down(before_shift, migration(SHIFT_MIGRATION))
    assert shifted_rows(before_shift) == before


def test_langenberg_migration_moves_only_rows_on_the_old_schedule(
    before_available_at: Conn,
) -> None:
    up(before_available_at, migration(AVAILABLE_AT_MIGRATION))
    before_available_at.execute("DELETE FROM observations")
    backfilled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    # valid_at, available_at, ingested_at, expected available_at
    rows = [
        # Backfilled on the old 75-minute schedule: moves to the 25-minute one.
        (AT, AT.replace(hour=10, minute=30), backfilled_at, AT.replace(minute=30)),
        # Live run first saw it in the old slot: keeps it.
        (
            AT.replace(minute=5),
            AT.replace(hour=10, minute=30),
            AT.replace(hour=10, minute=30, second=5),
            AT.replace(hour=10, minute=30),
        ),
        # Live run saw it in time, and a revision seen later: both stay.
        (AT.replace(minute=10), AT.replace(minute=30), AT.replace(minute=30, second=5), None),
        (AT.replace(minute=15), AT.replace(hour=12, minute=30), backfilled_at, None),
    ]
    with before_available_at.cursor() as cursor:
        for valid_at, available_at, ingested_at, _ in rows:
            for series_id in ("langenberg:level", "nierenhof:level"):
                cursor.execute(
                    "INSERT INTO observations (series_id, valid_at, value, available_at,"
                    " ingested_at) VALUES (%s, %s, 1, %s, %s)",
                    (series_id, valid_at, available_at, ingested_at),
                )
    for _ in range(2):
        up(before_available_at, migration(LANGENBERG_MIGRATION))
    stored = before_available_at.execute(
        "SELECT series_id, available_at FROM observations ORDER BY series_id, valid_at"
    ).fetchall()
    assert stored == [
        ("langenberg:level", expected or available_at) for _, available_at, _, expected in rows
    ] + [("nierenhof:level", available_at) for _, available_at, _, _ in rows]
    assert rows[0][3] == scheduled_available_at(
        AT, LATER_DELAYS["langenberg:level"], MIGRATION_ISSUE_MINUTE
    )


def test_lanuv_migration_moves_only_rows_on_the_old_schedule(
    before_available_at: Conn,
) -> None:
    up(before_available_at, migration(AVAILABLE_AT_MIGRATION))
    before_available_at.execute("DELETE FROM observations")
    before_available_at.execute(
        "INSERT INTO series (id, variable, unit, source, location, kind) VALUES"
        " ('neviges:level', 'level', 'cm', 'lanuv', 'neviges', 'observation')"
    )
    backfilled_at = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    # valid_at, available_at, ingested_at, expected available_at
    rows = [
        # Backfilled on the old 15-minute schedule: moves to the 25-minute one.
        (
            AT.replace(minute=10),
            AT.replace(minute=30),
            backfilled_at,
            AT.replace(hour=10, minute=30),
        ),
        # Live run first saw it in the old slot: keeps it.
        (
            AT.replace(minute=15),
            AT.replace(minute=30),
            AT.replace(minute=30, second=5),
            None,
        ),
        # Same slot on both schedules, and a revision seen later: both stay.
        (AT, AT.replace(minute=30), backfilled_at, None),
        (AT.replace(minute=12), AT.replace(hour=11, minute=30), backfilled_at, None),
    ]
    moved_series = ("neviges:level", "nierenhof:level")
    with before_available_at.cursor() as cursor:
        for valid_at, available_at, ingested_at, _ in rows:
            for series_id in ("langenberg:level", *moved_series):
                cursor.execute(
                    "INSERT INTO observations (series_id, valid_at, value, available_at,"
                    " ingested_at) VALUES (%s, %s, 1, %s, %s)",
                    (series_id, valid_at, available_at, ingested_at),
                )
    for _ in range(2):
        up(before_available_at, migration(LANUV_MIGRATION))
    stored = before_available_at.execute(
        "SELECT series_id, available_at FROM observations ORDER BY series_id, valid_at"
    ).fetchall()
    by_valid_at = sorted(rows)
    assert stored == [
        ("langenberg:level", available_at) for _, available_at, _, _ in by_valid_at
    ] + [
        (series_id, expected or available_at)
        for series_id in moved_series
        for _, available_at, _, expected in by_valid_at
    ]
    assert rows[0][3] == scheduled_available_at(
        rows[0][0], LATER_DELAYS["nierenhof:level"], MIGRATION_ISSUE_MINUTE
    )

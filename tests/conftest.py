"""A throwaway Postgres for storage tests, migrated like production. Never Neon."""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import TupleRow
from testcontainers.community.postgres import PostgresContainer

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"
# Same image as scripts/refresh-schema.sh.
POSTGRES_IMAGE = (
    "postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"
)


def migrate_up_section(migration: str) -> str:
    """The SQL between `-- migrate:up` and `-- migrate:down`, as dbmate runs it."""
    up_and_down = migration.split("-- migrate:up", 1)[1]
    return up_and_down.split("-- migrate:down", 1)[0]


def migrate_down_section(migration: str) -> str:
    """The SQL after `-- migrate:down`, as dbmate runs it on rollback."""
    return migration.split("-- migrate:down", 1)[1]


def apply_migrations(conn: psycopg.Connection[TupleRow]) -> None:
    # dbmate runs each file in its own transaction, in file name order.
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        with conn.transaction():
            conn.execute(migrate_up_section(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as postgres:
        url = postgres.get_connection_url()
        with psycopg.connect(url, autocommit=True) as conn:
            # In Neon these roles are created by hand (docs/setup-neon.md).
            conn.execute("CREATE ROLE pegel_jobs NOLOGIN")
            conn.execute("CREATE ROLE pegel_api NOLOGIN")
            conn.execute("CREATE ROLE pegel_grafana NOLOGIN")
            apply_migrations(conn)
        yield url


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection[TupleRow]]:
    with psycopg.connect(database_url, autocommit=True) as connection:
        yield connection
        connection.execute("RESET ROLE")
        connection.execute(
            "TRUNCATE series, observations, input_forecasts, forecasts, forecast_points"
        )

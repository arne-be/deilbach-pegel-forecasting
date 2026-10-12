"""Opens Postgres connections for jobs and the API."""

import psycopg
from psycopg.rows import TupleRow

CONNECT_TIMEOUT_SECONDS = 10


def connect(database_url: str) -> psycopg.Connection[TupleRow]:
    """Connect to the database behind `database_url` (e.g. JOBS_DATABASE_URL).

    The timeout covers Neon waking a suspended compute. Prepared statements are
    off because jobs and the API go through Neon's pooler in transaction mode.
    """
    return psycopg.connect(
        database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS, prepare_threshold=None
    )

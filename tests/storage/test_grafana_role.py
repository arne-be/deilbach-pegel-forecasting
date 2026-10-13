"""The Grafana role can read every table its dashboards use, and nothing else."""

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import TupleRow

Conn = psycopg.Connection[TupleRow]
DASHBOARD_TABLES = ["series", "observations", "input_forecasts", "forecasts", "forecast_points"]


@pytest.mark.parametrize("table", DASHBOARD_TABLES)
def test_grafana_role_can_read(conn: Conn, table: str) -> None:
    conn.execute("SET ROLE pegel_grafana")
    conn.execute(sql.SQL("SELECT * FROM {} LIMIT 1").format(sql.Identifier(table)))


def test_grafana_role_cannot_write(conn: Conn) -> None:
    conn.execute("SET ROLE pegel_grafana")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM series")

"""Export the raw Kupferdreh levels to a CSV for the outlier exploration.

Read only. Run with a connection string in DATABASE_URL (see README.md).
"""

import csv
import os
import sys

import psycopg

SQL = """
select observed_at, level_m from raw_observations
where station_id = 'kupferdreh' order by observed_at
"""

with psycopg.connect(os.environ["DATABASE_URL"]) as conn, open(sys.argv[1], "w", newline="") as f:
    conn.read_only = True
    writer = csv.writer(f)
    writer.writerow(["observed_at", "level_m"])
    writer.writerows(conn.execute(SQL))
print(f"wrote {sys.argv[1]}")

from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import TupleRow

from pegel.adapters.sources.lanuv_files import LevelFiles, read_levels
from pegel.config import load_config
from pegel.jobs.pipeline import backfill

FIXTURES = Path(__file__).parent / "fixtures"
NIERENHOF = load_config().station("nierenhof")
HEADER = "station_name;station_no;dateTime;value[cm]\n"


def test_levels_of_all_decades_are_read_in_metres_and_utc_without_gaps() -> None:
    observations = read_levels(FIXTURES / "lanuv", NIERENHOF)
    assert [o.observed_at for o in observations] == [
        datetime(2019, 12, 31, 22, 50, tzinfo=UTC),
        datetime(2019, 12, 31, 23, 0, tzinfo=UTC),
        datetime(2020, 1, 31, 22, 30, tzinfo=UTC),
        datetime(2020, 2, 1, 0, 0, tzinfo=UTC),
    ]
    assert [o.level_m for o in observations] == pytest.approx([0.322, 0.321, -0.035, 0.40])


def test_wrong_header_fails() -> None:
    with pytest.raises(ValueError, match="unexpected header"):
        read_levels(FIXTURES / "lanuv_bad_header", NIERENHOF)


def test_missing_files_fail(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_levels(tmp_path, NIERENHOF)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("Neviges;2769629000100;2020-01-01T00:00:00+01:00;30", "station_no"),
        ("Nierenhof;2769649000100;2020-01-01T00:00:00+01:00;abc", ":2:"),
        ("Nierenhof;2769649000100;2020-01-01T00:00:00;30", "without offset"),
        ("Nierenhof;2769649000100;30", "4 fields"),
    ],
)
def test_bad_row_fails_with_its_line(tmp_path: Path, row: str, message: str) -> None:
    path = tmp_path / "2769649000100_Nierenhof_2020-2025_Wasserstand_cm.csv"
    path.write_text(HEADER + row + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_levels(tmp_path, NIERENHOF)


def test_duplicate_times_fail(tmp_path: Path) -> None:
    row = "Nierenhof;2769649000100;2020-01-01T00:00:00+01:00;30\n"
    for decade in ("2010-2019", "2020-2025"):
        path = tmp_path / f"2769649000100_Nierenhof_{decade}_Wasserstand_cm.csv"
        path.write_text(HEADER + row, encoding="utf-8")
    with pytest.raises(ValueError, match="two readings"):
        read_levels(tmp_path, NIERENHOF)


def test_source_returns_the_window_only() -> None:
    fetch = LevelFiles(FIXTURES / "lanuv")
    start, end = datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 2, 1, tzinfo=UTC)
    assert [o.level_m for o in fetch(NIERENHOF, start, end)] == [pytest.approx(-0.035)]


def test_backfill_from_files_is_idempotent(conn: psycopg.Connection[TupleRow]) -> None:
    fetch = LevelFiles(FIXTURES / "lanuv")
    start, end = datetime(2019, 12, 1, tzinfo=UTC), datetime(2020, 3, 1, tzinfo=UTC)
    assert backfill(fetch, conn, NIERENHOF, start, end) == 4
    assert backfill(fetch, conn, NIERENHOF, start, end) == 0
    sources = conn.execute("SELECT DISTINCT source FROM raw_observations").fetchall()
    assert sources == [("lanuv",)]

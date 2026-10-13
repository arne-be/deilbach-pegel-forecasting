import bz2
import gzip
import io
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg.rows import TupleRow
from radolan_factory import rw_file

from pegel.adapters.sources.radolan import RadolanError, load_cells
from pegel.adapters.storage.observations import fetch_values
from pegel.config import config_file, load_config
from pegel.core.schedule import issue_time
from pegel.jobs.radar import backfill_radar, product_times, radar_step

Conn = psycopg.Connection[TupleRow]
CONFIG = load_config()
CELLS = load_cells(config_file(CONFIG.rain.radar.cells_file))
ISSUED_AT = datetime(2026, 10, 13, 13, 30, tzinfo=UTC)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
MINUTE = CONFIG.forecast.issue_minute


def wet_file(product_time: datetime) -> bytes:
    """1.0 mm in every catchment cell, 3.0 mm in one cell, one no-data cell in zone neviges."""
    words = dict.fromkeys(CELLS["catchment"], 10)
    words[CELLS["catchment"][0]] = 30
    words[CELLS["neviges"][-1]] = 0x2000 | 2500
    return rw_file(product_time, words)


def dwd(files: dict[str, bytes | int]) -> tuple[httpx.Client, list[str]]:
    """A fake DWD server that serves `files` by name (an int is an HTTP status), else 404."""
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[1]
        asked.append(name)
        answer = files.get(name, 404)
        if isinstance(answer, int):
            return httpx.Response(answer)
        return httpx.Response(200, content=answer)

    return httpx.Client(transport=httpx.MockTransport(handle)), asked


def stored(conn: Conn, series_id: str) -> list[tuple[datetime, float, float | None]]:
    values = fetch_values(conn, series_id, LONG_AGO, FAR_FUTURE)
    return [(value.valid_at, round(value.value, 6), value.coverage) for value in values]


def test_product_times_are_the_hourly_50_minute_products_in_the_window() -> None:
    times = product_times(ISSUED_AT - timedelta(hours=3), ISSUED_AT)
    assert times == [datetime(2026, 10, 13, hour, 50, tzinfo=UTC) for hour in (10, 11, 12)]


def test_hourly_step_stores_six_series_for_published_hours_and_reruns_change_nothing(
    conn: Conn,
) -> None:
    at_1250 = datetime(2026, 10, 13, 12, 50, tzinfo=UTC)
    client, asked = dwd(
        {"raa01-rw_10000-2610131250-dwd---bin.bz2": bz2.compress(wet_file(at_1250))}
    )
    step = radar_step(CONFIG, client)

    assert step(conn, ISSUED_AT) == 6
    assert len(asked) == CONFIG.rain.radar.ingest_lookback_hours
    assert stored(conn, "radolan_rw:catchment:max") == [(at_1250, 3.0, 1 - 1 / 119)]
    neviges = CELLS["neviges"]
    mean = (3.0 + 1.0 * (len(neviges) - 2)) / (len(neviges) - 1)
    assert neviges[0] == CELLS["catchment"][0]  # the wet cell lies in neviges
    assert stored(conn, "radolan_rw:zone:neviges") == [
        (at_1250, round(mean, 6), (len(neviges) - 1) / len(neviges))
    ]
    assert stored(conn, "radolan_rw:zone:lower") == [(at_1250, 1.0, 1.0)]
    assert step(conn, ISSUED_AT) == 0


def available_at(conn: Conn) -> list[datetime]:
    rows = conn.execute(
        "SELECT available_at FROM observations"
        " WHERE series_id = 'radolan_rw:zone:lower' ORDER BY valid_at"
    ).fetchall()
    return [row[0] for row in rows]


def test_hourly_step_stamps_the_slot_after_the_fetch(conn: Conn) -> None:
    at_1250 = datetime(2026, 10, 13, 12, 50, tzinfo=UTC)
    content = bz2.compress(wet_file(at_1250))
    clock = [datetime(2026, 10, 13, 13, 29, 59, tzinfo=UTC)]
    served_at: list[datetime] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("-2610131250-dwd---bin.bz2"):
            return httpx.Response(404)
        served_at.append(clock[0])
        # The download ends after the 13:30 slot began, so the stamp must be taken after it.
        clock[0] += timedelta(seconds=2)
        return httpx.Response(200, content=content)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    radar_step(CONFIG, client, now=lambda: clock[0])(conn, ISSUED_AT)
    [stamp] = available_at(conn)
    assert issue_time(served_at[0], MINUTE) < stamp == issue_time(clock[0], MINUTE)


def tar_of(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_backfill_uses_monthly_tars_before_2025_and_the_recent_archive_after(
    conn: Conn, tmp_path: Path
) -> None:
    in_tar = [datetime(2024, 12, 31, hour, 50, tzinfo=UTC) for hour in (21, 22, 23)]
    recent = datetime(2025, 1, 1, 0, 50, tzinfo=UTC)
    monthly = tar_of({f"raa01-rw_10000-{t:%y%m%d%H%M}-dwd---bin": wet_file(t) for t in in_tar})
    client, asked = dwd(
        {
            "RW202412.tar.gz": monthly,
            "raa01-rw_10000-2501010050-dwd---bin.gz": gzip.compress(wet_file(recent)),
        }
    )
    start = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)
    end = datetime(2025, 1, 1, 2, 0, tzinfo=UTC)

    assert backfill_radar(conn, CONFIG, client, start, end, tmp_path) == 3 * 6
    assert [row[0] for row in stored(conn, "radolan_rw:zone:lower")] == [*in_tar[1:], recent]
    # Each hh:50 product is there 35 minutes later, so the :30 run of the next hour has it.
    assert CONFIG.rain.radar.available_after_minutes == 35
    assert available_at(conn) == [t + timedelta(minutes=40) for t in [*in_tar[1:], recent]]
    # 01:50 is missing in the archive: a warning, not an error.
    assert asked == [
        "RW202412.tar.gz",
        "raa01-rw_10000-2501010050-dwd---bin.gz",
        "raa01-rw_10000-2501010150-dwd---bin.gz",
    ]

    # The rerun reads the cache and changes nothing; only the missing hour is asked again.
    assert backfill_radar(conn, CONFIG, client, start, end, tmp_path) == 0
    assert asked[3:] == ["raa01-rw_10000-2501010150-dwd---bin.gz"]


def test_one_broken_or_failing_live_file_does_not_cost_the_other_hours(conn: Conn) -> None:
    at_1250 = datetime(2026, 10, 13, 12, 50, tzinfo=UTC)
    client, _ = dwd(
        {
            "raa01-rw_10000-2610131250-dwd---bin.bz2": bz2.compress(wet_file(at_1250)),
            "raa01-rw_10000-2610131150-dwd---bin.bz2": b"not bzip2",
            "raa01-rw_10000-2610131050-dwd---bin.bz2": 500,
        }
    )
    assert radar_step(CONFIG, client)(conn, ISSUED_AT) == 6
    assert [row[0] for row in stored(conn, "radolan_rw:zone:lower")] == [at_1250]


def test_backfill_fails_when_a_month_has_no_product_at_all(conn: Conn, tmp_path: Path) -> None:
    client, _ = dwd({})
    start = datetime(2025, 3, 1, tzinfo=UTC)
    with pytest.raises(RadolanError, match="no radar product found for 2025-03-01"):
        backfill_radar(conn, CONFIG, client, start, start + timedelta(hours=3), tmp_path)

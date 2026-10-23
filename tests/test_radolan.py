import bz2
import gzip
import io
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from radolan_factory import CELLS, rw_file

from pegel.adapters.sources import radolan
from pegel.adapters.sources.radolan import (
    RadolanError,
    fetch_live,
    fetch_recent,
    load_cells,
    parse_rw,
    read_tar,
)
from pegel.config import config_file, load_config

FIXTURES = Path(__file__).parent / "fixtures" / "radolan"
PRODUCT_TIME = datetime(2026, 10, 13, 9, 50, tzinfo=UTC)


def test_values_and_flags_follow_the_dwd_bits() -> None:
    words = {1: 25, 2: 0x1000 | 7, 3: 0x2000 | 2500, 4: 0x4000 | 1, 5: 0x8000 | 2490}
    grid = parse_rw(rw_file(PRODUCT_TIME, words), PRODUCT_TIME)
    assert grid.product_time == PRODUCT_TIME
    assert grid.rain_mm(0) == 0
    assert grid.rain_mm(1) == pytest.approx(2.5)
    # Interpolated from rain gauges: a valid value without the flag bit.
    assert grid.rain_mm(2) == pytest.approx(0.7)
    assert grid.rain_mm(3) is None  # no data
    assert grid.rain_mm(4) is None  # negative
    assert grid.rain_mm(5) is None  # clutter


def test_cells_are_little_endian_from_the_south_west_corner() -> None:
    last = CELLS - 1
    grid = parse_rw(rw_file(PRODUCT_TIME, {900: 0x0102, last: 3}), PRODUCT_TIME)
    assert grid.rain_mm(900) == pytest.approx(25.8)  # 0x0102 = 258, first cell of row 1
    assert grid.rain_mm(last) == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (rw_file(PRODUCT_TIME, product="RX"), "expected product RW"),
        (rw_file(datetime(2026, 10, 13, 8, 50, tzinfo=UTC)), "expected product time"),
        (rw_file(PRODUCT_TIME, version=5), "WGS84"),
        (rw_file(PRODUCT_TIME, version=6), "VS 6"),
        (rw_file(PRODUCT_TIME, grid="1100x 900"), "900x900 grid"),
        (rw_file(PRODUCT_TIME, cells=CELLS - 1), "bytes"),
        (rw_file(PRODUCT_TIME)[:-1], "bytes"),
        (b"RW no end of header", "no end of header"),
    ],
)
def test_untrusted_files_fail(raw: bytes, message: str) -> None:
    with pytest.raises(RadolanError, match=message):
        parse_rw(raw, PRODUCT_TIME)


def test_real_file_parses_and_covers_the_catchment() -> None:
    raw = bz2.decompress((FIXTURES / "raa01-rw_10000-2610130950-dwd---bin.bz2").read_bytes())
    grid = parse_rw(raw, PRODUCT_TIME)
    assert grid.precision_mm == pytest.approx(0.1)
    cells = load_cells(config_file(load_config().rain.radar.cells_file))
    rains = [grid.rain_mm(cell) for cell in cells["catchment"]]
    assert all(rain is not None and 0 <= rain < 100 for rain in rains)


def tar_of(files: dict[str, bytes], compress: bool = False) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz" if compress else "w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def test_tar_reads_nested_daily_tars_and_gzipped_files_and_keeps_only_hourly_products() -> None:
    at_0850 = datetime(2024, 11, 19, 8, 50, tzinfo=UTC)
    at_0950 = datetime(2024, 11, 19, 9, 50, tzinfo=UTC)
    daily = tar_of(
        {
            "raa01-rw_10000-2411190840-dwd---bin": b"rolling sum, skipped unparsed",
            "raa01-rw_10000-2411190850-dwd---bin": rw_file(at_0850, {1: 5}),
        },
        compress=True,
    )
    monthly = tar_of(
        {
            "RW_20241119.tar.gz": daily,
            "raa01-rw_10000-2411190950-dwd---bin.gz": gzip.compress(rw_file(at_0950)),
        }
    )
    with tarfile.open(fileobj=io.BytesIO(monthly)) as archive:
        grids = list(read_tar(archive))
    assert [grid.product_time for grid in grids] == [at_0850, at_0950]
    assert grids[0].rain_mm(1) == pytest.approx(0.5)


def client_answering(*responses: httpx.Response) -> tuple[httpx.Client, list[str]]:
    urls: list[str] = []
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return queue.pop(0)

    return httpx.Client(transport=httpx.MockTransport(handle)), urls


def test_live_file_is_fetched() -> None:
    body = gzip.compress(rw_file(PRODUCT_TIME))
    client, urls = client_answering(httpx.Response(200, content=body))
    grid = fetch_live(client, PRODUCT_TIME)
    assert grid is not None and grid.product_time == PRODUCT_TIME
    assert urls == [
        "https://opendata.dwd.de/climate_environment/CDC/grids_germany/hourly/radolan"
        "/recent/bin/raa01-rw_10000-2610130950-dwd---bin.gz"
    ]


def test_live_file_is_tried_once_so_a_slow_dwd_cannot_hold_the_hourly_run() -> None:
    client, urls = client_answering(httpx.Response(503), httpx.Response(200))
    with pytest.raises(RadolanError, match="after 1 attempt"):
        fetch_live(client, PRODUCT_TIME)
    assert len(urls) == 1


def test_live_body_over_its_time_budget_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(radolan, "LIVE_BUDGET_SECONDS", 0.0)
    client, _ = client_answering(httpx.Response(200, content=iter([b"first", b"second"])))
    with pytest.raises(RadolanError, match="TimeoutError"):
        fetch_live(client, PRODUCT_TIME)


def test_unpublished_live_file_is_none() -> None:
    client, _ = client_answering(httpx.Response(404))
    assert fetch_live(client, PRODUCT_TIME) is None


def test_archive_file_is_retried_after_server_errors_then_cached(tmp_path: Path) -> None:
    body = gzip.compress(rw_file(PRODUCT_TIME))
    client, urls = client_answering(httpx.Response(503), httpx.Response(200, content=body))
    sleeps: list[float] = []
    grid = fetch_recent(client, PRODUCT_TIME, tmp_path, sleep=sleeps.append)
    assert grid is not None and grid.product_time == PRODUCT_TIME
    assert sleeps == [2.0]
    assert fetch_recent(client, PRODUCT_TIME, tmp_path) is not None
    assert len(urls) == 2


def test_persistent_archive_server_errors_fail(tmp_path: Path) -> None:
    client, urls = client_answering(*[httpx.Response(500)] * 3)
    with pytest.raises(RadolanError, match="after 3 attempt"):
        fetch_recent(client, PRODUCT_TIME, tmp_path, sleep=lambda _: None)
    assert len(urls) == 3

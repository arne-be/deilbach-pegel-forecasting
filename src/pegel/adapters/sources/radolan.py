"""Reads DWD RADOLAN RW files, the hourly gauge-adjusted radar rain (DWD Open Data, CC BY 4.0).

Format: "RADOLAN/RADVOR Beschreibung des Kompositformats", version 2.6, DWD, chapters 1.1 to 1.4:
https://opendata.dwd.de/climate_environment/CDC/help/RADOLAN/Unterstuetzungsdokumente/RADOLAN-RADVOR-Kompositformat_2.6.pdf
An ASCII header ends with ETX (0x03). Then 900 x 900 little-endian 16-bit words follow, starting
with the south-west cell and going east, then north row by row (chapter 1.2).
"""

import gzip
import json
import logging
import re
import sys
import tarfile
import time
from array import array
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import httpx

from pegel.core.observations import require_utc

logger = logging.getLogger(__name__)

# The hourly run reads the recent archive: DWD's live folder (weather/radar/radolan/rw) switched
# to HDF5 on 2026-10-20, while the archive keeps this binary format and gets each hh:50 product
# 27 to 32 minutes later (346 products, 2026-10-09 to 23).
_ARCHIVE_URL = "https://opendata.dwd.de/climate_environment/CDC/grids_germany/hourly/radolan"
RECENT_URL = _ARCHIVE_URL + "/recent/bin/raa01-rw_10000-{stamp}-dwd---bin.gz"
HISTORICAL_URL = _ARCHIVE_URL + "/historical/bin/{year}/RW{year}{month:02d}.tar.gz"
# Single files in the recent archive start with this month; earlier months are monthly tars.
RECENT_ARCHIVE_START = datetime(2025, 1, 1, tzinfo=UTC)
TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
# The hourly run must not wait on a slow DWD: one try per live file, a short timeout per phase
# and a budget for the whole body, so a trickling answer can't hold it either. A missed file
# is fetched by the next run, which looks back several hours.
LIVE_TIMEOUT_SECONDS = 5.0
LIVE_BUDGET_SECONDS = 10.0
BACKOFF_BASE_SECONDS = 2.0
# Files are named after their product time; the hourly RW product is the one at :50.
_FILE_NAME = re.compile(r"raa01-rw_10000-(\d{8}50)-dwd---bin(\.gz)?")

GRID_SIZE = 900
END_OF_HEADER = b"\x03"
# The bits of each word (chapter 1.2): bits 1-12 hold the value in units of the header's PR.
VALUE_MASK = 0x0FFF
# Bit 13: the value comes from interpolated rain gauges, not radar. Still a valid value.
INTERPOLATED_FLAG = 0x1000
NO_DATA_FLAG = 0x2000  # bit 14
NEGATIVE_FLAG = 0x4000  # bit 15, should not occur in RW
CLUTTER_FLAG = 0x8000  # bit 16, should not occur in RW
UNUSABLE_FLAGS = NO_DATA_FLAG | NEGATIVE_FLAG | CLUTTER_FLAG
# VS 5 marks composites on the WGS84 ellipsoid, whose corners differ by about 1 km from the
# sphere grid the cells file is built on (chapter 1.4.2). RW used VS 2 and 3 so far; newer
# versions are rejected too until someone checks what they change.
WGS84_VERSION = 5

_HEADER = re.compile(
    r"^(?P<product>[A-Z]{2})(?P<day>\d{2})(?P<hour>\d{2})(?P<minute>\d{2})\d{5}"
    r"(?P<month>\d{2})(?P<year>\d{2})BY\s*(?P<bytes>\d+)VS\s*(?P<version>\d+)"
)
_PRECISION = re.compile(r"PR\s*E-(\d{2})")
_GRID = re.compile(r"GP\s*(\d+)x\s*(\d+)")


class RadolanError(Exception):
    """A RADOLAN file we cannot trust: wrong product, time, grid or size."""


@dataclass(frozen=True)
class RadolanGrid:
    """One RW product: rain over the hour ending at `product_time`, per 1 km cell."""

    product_time: datetime
    # mm per unit of the stored values, e.g. 0.1 for PR E-01.
    precision_mm: float
    words: array[int]

    def rain_mm(self, cell: int) -> float | None:
        """Rain in the cell at flat index row * 900 + col (row 0 in the south), None if unusable."""
        word = self.words[cell]
        if word & UNUSABLE_FLAGS:
            return None
        return (word & VALUE_MASK) * self.precision_mm


def parse_rw(raw: bytes, expected_time: datetime) -> RadolanGrid:
    """Parses one RW file and checks it is the product for `expected_time`."""
    require_utc(expected_time, "expected_time")
    header_end = raw.find(END_OF_HEADER)
    if header_end < 0:
        raise RadolanError("no end of header (ETX) found")
    header = raw[:header_end].decode("ascii", errors="replace")
    match = _HEADER.match(header)
    if match is None:
        raise RadolanError(f"unexpected header start {header[:40]!r}")
    if match["product"] != "RW":
        raise RadolanError(f"expected product RW, got {match['product']!r}")
    product_time = datetime(
        2000 + int(match["year"]),
        int(match["month"]),
        int(match["day"]),
        int(match["hour"]),
        int(match["minute"]),
        tzinfo=UTC,
    )
    if product_time != expected_time:
        raise RadolanError(f"expected product time {expected_time}, got {product_time}")
    if int(match["version"]) >= WGS84_VERSION:
        raise RadolanError(
            f"composite version VS {match['version']} (WGS84 or newer); the cells assume VS < 5"
        )
    # The free text after MS (radar sites) could contain anything, so search before it.
    fields = header.split("MS", 1)[0]
    grid = _GRID.search(fields)
    if grid is None or (int(grid[1]), int(grid[2])) != (GRID_SIZE, GRID_SIZE):
        raise RadolanError(f"expected a {GRID_SIZE}x{GRID_SIZE} grid in header {fields!r}")
    precision = _PRECISION.search(fields)
    if precision is None:
        raise RadolanError(f"no precision (PR) in header {fields!r}")
    data_start = header_end + 1
    if int(match["bytes"]) != len(raw) or len(raw) - data_start != 2 * GRID_SIZE * GRID_SIZE:
        raise RadolanError(f"file has {len(raw)} bytes, header says {match['bytes']}")
    words = array("H")
    words.frombytes(raw[data_start:])
    if sys.byteorder == "big":
        words.byteswap()
    return RadolanGrid(product_time, 10.0 ** -int(precision[1]), words)


def load_cells(path: Path) -> dict[str, list[int]]:
    """The radar cells per area from the file scripts/build_catchment.py writes."""
    content = json.loads(path.read_text(encoding="utf-8"))
    grid = content["grid"]
    if (grid["product"], grid["rows"], grid["cols"]) != ("RW", GRID_SIZE, GRID_SIZE):
        raise ValueError(f"{path.name} is not for the {GRID_SIZE}x{GRID_SIZE} RW grid")
    cells: Mapping[str, Sequence[int]] = content["cells"]
    for area, indices in cells.items():
        if not indices or not all(0 <= index < GRID_SIZE * GRID_SIZE for index in indices):
            raise ValueError(f"{path.name}: area {area!r} has no cells or one outside the grid")
    return {area: list(indices) for area, indices in cells.items()}


def fetch_live(client: httpx.Client, product_time: datetime) -> RadolanGrid | None:
    """The newest RW product from the recent archive, None if not published (yet). One try only."""
    url = RECENT_URL.format(stamp=_stamp(product_time))
    raw = _get(
        client,
        url,
        time.sleep,
        attempts=1,
        timeout_seconds=LIVE_TIMEOUT_SECONDS,
        budget_seconds=LIVE_BUDGET_SECONDS,
    )
    return None if raw is None else parse_rw(gzip.decompress(raw), product_time)


def fetch_recent(
    client: httpx.Client,
    product_time: datetime,
    cache_dir: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> RadolanGrid | None:
    """The RW product from the recent archive (2025 on), cached; None if the archive lacks it."""
    path = cache_dir / "recent" / f"raa01-rw_10000-{_stamp(product_time)}-dwd---bin.gz"
    if not path.exists():
        raw = _get(client, RECENT_URL.format(stamp=_stamp(product_time)), sleep)
        if raw is None:
            return None
        _write_atomically(path, raw)
    return parse_rw(gzip.decompress(path.read_bytes()), product_time)


def historical_month(
    client: httpx.Client,
    month_start: datetime,
    cache_dir: Path,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[RadolanGrid]:
    """Every hourly RW product of a month before 2025, from DWD's monthly tar (cached)."""
    path = cache_dir / f"RW{month_start:%Y%m}.tar.gz"
    if not path.exists():
        url = HISTORICAL_URL.format(year=month_start.year, month=month_start.month)
        raw = _get(client, url, sleep)
        if raw is None:
            raise RadolanError(f"no monthly archive for {month_start:%Y-%m}")
        _write_atomically(path, raw)
    with tarfile.open(path) as archive:
        yield from read_tar(archive)


def read_tar(archive: tarfile.TarFile) -> Iterator[RadolanGrid]:
    """The hourly RW products in a tar. Recent years nest daily tars, older ones gzip each file."""
    for member in archive:
        name = PurePosixPath(member.name).name
        file = archive.extractfile(member) if member.isfile() else None
        if file is None:
            continue
        if name.endswith((".tar", ".tar.gz")):
            with tarfile.open(fileobj=file) as inner:
                yield from read_tar(inner)
            continue
        match = _FILE_NAME.fullmatch(name)
        if match is None:
            continue
        raw = file.read()
        yield parse_rw(gzip.decompress(raw) if match[2] else raw, _product_time(match[1]))


def _stamp(product_time: datetime) -> str:
    return f"{product_time:%y%m%d%H%M}"


def _product_time(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%y%m%d%H%M").replace(tzinfo=UTC)


def _write_atomically(path: Path, content: bytes) -> None:
    # A crash mid-write must not leave a truncated file that later runs take as cached.
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(content)
    partial.replace(path)


def _get(
    client: httpx.Client,
    url: str,
    sleep: Callable[[float], None],
    *,
    attempts: int = MAX_ATTEMPTS,
    timeout_seconds: float = TIMEOUT_SECONDS,
    budget_seconds: float | None = None,
) -> bytes | None:
    """The body, or None for 404. Retries network errors and 5xx with backoff, then raises.

    With a budget, a body still arriving after `budget_seconds` counts as a network error.
    """
    name = url.rsplit("/", 1)[1]
    for attempt in range(1, attempts + 1):
        try:
            status, body = _get_once(client, url, timeout_seconds, budget_seconds)
        except (httpx.TransportError, TimeoutError) as error:
            failure = f"network error ({type(error).__name__})"
        else:
            if status == 404:
                return None
            if status < 400:
                return body
            if status < 500:
                raise RadolanError(f"DWD answered HTTP {status} for {name}")
            failure = f"HTTP {status}"
        if attempt == attempts:
            raise RadolanError(f"{name} unreachable after {attempts} attempt(s): {failure}")
        delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        logger.warning(
            "radolan request failed, retrying",
            extra={"file": name, "attempt": attempt, "failure": failure, "retry_in_s": delay},
        )
        sleep(delay)
    raise AssertionError("unreachable")


def _get_once(
    client: httpx.Client, url: str, timeout_seconds: float, budget_seconds: float | None
) -> tuple[int, bytes]:
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    with client.stream("GET", url, timeout=timeout_seconds) as response:
        if response.status_code >= 400:
            return response.status_code, b""
        chunks = []
        for chunk in response.iter_bytes():
            chunks.append(chunk)
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"body took longer than {budget_seconds} s")
        return response.status_code, b"".join(chunks)

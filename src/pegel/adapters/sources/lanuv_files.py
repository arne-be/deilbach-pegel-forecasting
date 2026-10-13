"""Reads water level history from LANUV open data CSV files (one file per station and decade).

The files come from opengeodata.nrw.de (hydro/w, licence dl-de/zero-2-0), extracted from the
`Ruhreinzugsgebiet-NRW-W_{decade}_EPSG25832_CSV.zip` archives.
"""

from bisect import bisect_left
from collections.abc import Iterator
from datetime import datetime
from itertools import pairwise
from pathlib import Path

from pegel.adapters.sources.lanuv import parse_lanuv_value
from pegel.config import Station
from pegel.core.observations import Observation

# The header also fixes the unit: levels in centimetres, as parse_lanuv_value expects.
LEVEL_HEADER = "station_name;station_no;dateTime;value[cm]"


def level_files(directory: Path, station: Station) -> list[Path]:
    """The station's level files, oldest decade first. Discharge files are left out."""
    files = sorted(directory.glob(f"{station.source_label}_*_Wasserstand_cm.csv"))
    if not files:
        raise FileNotFoundError(f"no LANUV level files for {station.source_label} in {directory}")
    return files


def read_level_file(path: Path, station: Station) -> Iterator[Observation]:
    """The readings of one file, skipping gaps. Fails on a wrong header, station or row."""
    with path.open(encoding="utf-8-sig") as lines:
        header = next(lines, "").strip()
        if header != LEVEL_HEADER:
            raise ValueError(f"{path}: unexpected header {header!r}, expected {LEVEL_HEADER!r}")
        for line_number, line in enumerate(lines, start=2):
            try:
                observation = _parse_row(line, station)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            if observation is not None:
                yield observation


def read_levels(directory: Path, station: Station) -> list[Observation]:
    """All readings of a station from its files, oldest first, each time at most once."""
    observations = sorted(
        (
            observation
            for path in level_files(directory, station)
            for observation in read_level_file(path, station)
        ),
        key=lambda observation: observation.observed_at,
    )
    for previous, current in pairwise(observations):
        if previous.observed_at == current.observed_at:
            raise ValueError(f"{station.id}: two readings at {current.observed_at.isoformat()}")
    return observations


class LevelFiles:
    """A FetchLevels source over the files. Loads a station's files once, keeps one in memory."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._loaded: tuple[str, list[Observation]] | None = None

    def __call__(self, station: Station, start: datetime, end: datetime) -> list[Observation]:
        if self._loaded is None or self._loaded[0] != station.id:
            self._loaded = (station.id, read_levels(self.directory, station))
        observations = self._loaded[1]

        def position(moment: datetime) -> int:
            return bisect_left(observations, moment, key=lambda reading: reading.observed_at)

        return observations[position(start) : position(end)]


def _parse_row(line: str, station: Station) -> Observation | None:
    fields = line.rstrip("\r\n").split(";")
    if len(fields) != 4:
        raise ValueError(f"expected 4 fields, got {len(fields)}")
    _, station_no, timestamp_text, value = fields
    if station_no != station.source_label:
        raise ValueError(f"station_no {station_no!r} is not {station.source_label!r}")
    return parse_lanuv_value(station.id, timestamp_text, value)

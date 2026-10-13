"""Loads and validates config/pegel.json, the one place for thresholds, horizons and stations."""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pegel.json"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Station(_Frozen):
    id: str
    name: str
    source: Literal["influx", "lanuv"]
    # The station's name or number at its source, e.g. the LANUV station_no.
    source_label: str
    # How long after its time a reading is reliably at the source (measured, see the docs).
    available_after_minutes: int = Field(ge=0)


class ForecastSettings(_Frozen):
    station_id: str
    # The model the page shows. Only models the hourly job can build are allowed.
    model: Literal["persistence"]
    horizon_hours: int = Field(gt=0)
    summary_horizons_hours: tuple[int, ...]
    # The hourly run is scheduled at this minute; it is also the issue time of its forecast.
    issue_minute: int = Field(ge=0, le=59)
    # Each hourly run refetches this many hours, so readings that arrive late are picked up.
    ingest_lookback_hours: int = Field(gt=0)
    # The same for the upstream stations. Longer, so missed runs heal on their own; LANUV only
    # serves the last seven days.
    upstream_ingest_lookback_hours: int = Field(gt=0, le=168)


class Category(_Frozen):
    """A flood category. It applies when the level is strictly above `above_cm`."""

    number: int
    name: str
    above_cm: float | None


class Freshness(_Frozen):
    observation_max_age_minutes: int = Field(gt=0)
    forecast_max_age_minutes: int = Field(gt=0)


class ApiSettings(_Frozen):
    # The first day with data. Earlier requests are rejected instead of querying for nothing.
    history_first_day: date
    # Whole days, counting the first and the last day of a history request.
    history_default_days: int = Field(gt=0)
    history_max_days: int = Field(gt=0)


class RadarRainSettings(_Frozen):
    source: str
    # Radar cells per series, written by scripts/build_catchment.py next to this config.
    cells_file: str
    # Each hourly run refetches this many hours, so a late or missed radar file is picked up.
    ingest_lookback_hours: int = Field(gt=0)


class RainForecastSettings(_Frozen):
    source: str
    # Rows loaded from the forecast archive for training get their own source.
    archive_source: str
    # Weather model grid points to fetch, written by scripts/build_catchment.py.
    points_file: str
    horizon_hours: int = Field(gt=0)
    # The "storm nearby" series is this percentile over the forecast ring.
    ring_percentile: int = Field(gt=0, lt=100)
    # How long after run_at a run is reliably served (docs/catchment.md); for live and archive.
    available_after_minutes: int = Field(ge=0)


class RainSettings(_Frozen):
    radar: RadarRainSettings
    forecast: RainForecastSettings


class PegelConfig(_Frozen):
    stations: tuple[Station, ...]
    forecast: ForecastSettings
    categories: tuple[Category, ...]
    freshness: Freshness
    api: ApiSettings
    rain: RainSettings

    @model_validator(mode="after")
    def _check_consistency(self) -> "PegelConfig":
        station_ids = {station.id for station in self.stations}
        if self.forecast.station_id not in station_ids:
            raise ValueError(f"forecast station {self.forecast.station_id!r} is not in stations")
        horizon = self.forecast.horizon_hours
        if any(hours > horizon for hours in self.forecast.summary_horizons_hours):
            raise ValueError("summary horizons must not exceed the forecast horizon")
        if not self.categories or self.categories[0].above_cm is not None:
            raise ValueError("the first category must have no lower bound (above_cm: null)")
        bounds = [category.above_cm for category in self.categories[1:]]
        set_bounds = [bound for bound in bounds if bound is not None]
        if len(set_bounds) != len(bounds) or set_bounds != sorted(set_bounds):
            raise ValueError("category bounds must be set and ascending after the first one")
        if self.api.history_default_days > self.api.history_max_days:
            raise ValueError("the default history range must not exceed the maximum")
        return self

    def station(self, station_id: str) -> Station:
        for station in self.stations:
            if station.id == station_id:
                return station
        raise KeyError(f"unknown station {station_id!r}")


def config_file(name: str) -> Path:
    """A data file that lives next to config/pegel.json, e.g. the radar cells."""
    return DEFAULT_CONFIG_PATH.parent / name


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> PegelConfig:
    return PegelConfig.model_validate_json(path.read_text(encoding="utf-8"))

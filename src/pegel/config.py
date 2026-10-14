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
    # Added at ingest to move the source's zero to ours; changing it needs a data migration.
    level_offset_cm: float = 0.0


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


class CleaningSettings(_Frozen):
    """The live Kalman outlier filter for the forecast station's level (core/cleaning.py)."""

    # A reading is an outlier if it is further than this many standard deviations from the
    # predicted level, and at least min_deviation_cm.
    gate_sigmas: float = Field(gt=0)
    min_deviation_cm: float = Field(gt=0)
    measurement_noise_cm: float = Field(gt=0)
    # How fast the trend may change, in (cm/h)^2 per hour.
    trend_noise: float = Field(gt=0)
    # The allowed change grows with the time since the last accepted reading only up to
    # this, so a sensor stuck at an error value never becomes plausible.
    cap_hours: float = Field(gt=0)
    # Without an accepted reading for this long, the filter starts over from the next one.
    restart_after_hours: float = Field(gt=0)
    # A reading back within recent_tolerance_cm of a level accepted in the last recent_hours
    # is accepted, so the true level after a spike that slipped through isn't rejected.
    recent_hours: float = Field(gt=0)
    recent_tolerance_cm: float = Field(gt=0)
    # Each run replays the filter from this many hours before its window, so it needs no
    # stored state.
    warm_up_hours: int = Field(gt=0)


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
    # How long after its product time a file is reliably in DWD's live folder (docs/catchment.md).
    available_after_minutes: int = Field(ge=0)


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


class EvaluationSettings(_Frozen):
    """The frozen setup for scoring forecast models (docs/decisions/0008)."""

    # Issue times from the start of the first day to the end of the last day, both inclusive.
    window_first_day: date
    window_last_day: date
    leads_hours: int = Field(gt=0)
    # High water: the level is above this at the issue time or at the target.
    high_water_cm: float = Field(gt=0)
    # A flood event is a peak above this.
    flood_cm: float = Field(gt=0)
    # A target is the reading closest to its time, at most this far off; otherwise missing.
    target_tolerance_minutes: int = Field(ge=0)
    # Training issue times stop this long before the test starts, so no target reaches into it.
    embargo_hours: int = Field(ge=0)


class PegelConfig(_Frozen):
    stations: tuple[Station, ...]
    forecast: ForecastSettings
    categories: tuple[Category, ...]
    cleaning: CleaningSettings
    freshness: Freshness
    api: ApiSettings
    evaluation: EvaluationSettings
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
        evaluation = self.evaluation
        if evaluation.window_first_day > evaluation.window_last_day:
            raise ValueError("the evaluation window must not end before it starts")
        if evaluation.leads_hours > horizon:
            raise ValueError("evaluation leads must not exceed the forecast horizon")
        if evaluation.high_water_cm >= evaluation.flood_cm:
            raise ValueError("the high water level must be below the flood level")
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

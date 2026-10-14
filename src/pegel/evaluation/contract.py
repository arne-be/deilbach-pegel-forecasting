"""What every part of the model evaluation agrees on: folds, file schemas and the model interface.

The dataset has one row per issue time (hh:30 UTC) and a column `issued_at` (tz-aware UTC). It
holds history windows, not features. Every input is as known at the issue time; a missing
value is NaN and is never filled in the dataset.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import numpy as np
import numpy.typing as npt
import pandas as pd
from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from pegel.config import EvaluationSettings

ISSUED_AT = "issued_at"
# The newest cleaned Kupferdreh reading known at the issue time, and its valid time.
KD_LAST_CM = "kd_last_cm"
KD_LAST_AT = "kd_last_at"
# Median of the cleaned hourly levels of the 30 days before the issue time.
KD_BASE_30D_CM = "kd_base_30d_cm"

# Column prefix per gauge for the hourly level windows.
GAUGE_PREFIXES = {"kupferdreh": "kd", "langenberg": "lb", "nierenhof": "nh"}
LEVEL_LAG_HOURS = 24
RADAR_LAG_HOURS = 7 * 24


def lag_columns(prefix: str, hours: int) -> list[str]:
    """`<prefix>_lag_0` … `<prefix>_lag_<hours-1>`: the value k hours before the issue time."""
    return [f"{prefix}_lag_{k}" for k in range(hours)]


def level_lag_columns(station_id: str) -> list[str]:
    return lag_columns(GAUGE_PREFIXES[station_id], LEVEL_LAG_HOURS)


def radar_lag_columns(area: str) -> list[str]:
    """Hourly radar rain of one area of the cells file: zone mean, or max for `catchment`."""
    return lag_columns(f"radar_{area}", RADAR_LAG_HOURS)


def lead_columns(prefix: str, leads: int) -> list[str]:
    """`<prefix>_1` … `<prefix>_<leads>`, one per hour ahead of the issue time."""
    return [f"{prefix}_{k}" for k in range(1, leads + 1)]


# ICON-D2 rain for each hour ahead: catchment mean, ring p90, and the lead of the run it came from.
ICON_MEAN = "icon_mean"
ICON_P90 = "icon_p90"
ICON_LEAD = "icon_lead"
# Cleaned Kupferdreh level for each lead; NaN when no reading is close enough.
TARGET = "target"


def dataset_columns(radar_areas: Sequence[str], leads: int) -> list[str]:
    """Every column of the dataset, in order. `radar_areas` are the areas of the cells file."""
    columns = [ISSUED_AT, KD_LAST_CM, KD_LAST_AT, KD_BASE_30D_CM]
    for station_id in GAUGE_PREFIXES:
        columns += level_lag_columns(station_id)
    for area in radar_areas:
        columns += radar_lag_columns(area)
    for prefix in (ICON_MEAN, ICON_P90, ICON_LEAD, TARGET):
        columns += lead_columns(prefix, leads)
    return columns


# predictions.parquet: one row per issue time, lead and model.
PREDICTION_COLUMNS = ("issued_at", "lead", "model", "fold", "prediction", "target")
# scores.csv: one row per model, fold, subset and lead.
SCORE_COLUMNS = ("model", "fold", "subset", "lead", "n", "mae", "rmse", "bias", "skill")


@dataclass(frozen=True)
class Fold:
    """A test period of whole days, `test_start` to `test_end`, both inclusive."""

    name: str
    test_start: date
    test_end: date


# Fixed in code, not config, so changing them is a reviewed code change (docs/decisions/0008).
FOLDS = (
    Fold("F1", date(2024, 10, 1), date(2024, 12, 31)),
    Fold("F2", date(2025, 1, 1), date(2025, 3, 31)),
    Fold("F3", date(2025, 4, 1), date(2025, 9, 30)),
    Fold("F4", date(2025, 10, 1), date(2026, 4, 12)),
)


def _midnight_utc(day: date) -> pd.Timestamp:
    return pd.Timestamp(day, tz="UTC")


def holdout_rows(dataset: pd.DataFrame, fold: Fold) -> pd.DataFrame:
    """The rows issued in the fold's test period."""
    issued_at = dataset[ISSUED_AT]
    start = _midnight_utc(fold.test_start)
    end = _midnight_utc(fold.test_end + timedelta(days=1))
    return dataset[(issued_at >= start) & (issued_at < end)]


def train_rows(dataset: pd.DataFrame, fold: Fold, settings: EvaluationSettings) -> pd.DataFrame:
    """The rows from the window start up to the embargo before the fold's test period.

    Expanding window: training always starts on the window's first day. The embargo is the
    longest lead, so no training target reaches into the test period.
    """
    issued_at = dataset[ISSUED_AT]
    start = _midnight_utc(settings.window_first_day)
    end = _midnight_utc(fold.test_start) - pd.Timedelta(hours=settings.leads_hours)
    return dataset[(issued_at >= start) & (issued_at < end)]


class Model(Protocol):
    name: str

    def fit(self, train: pd.DataFrame) -> None: ...

    def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        """Shape (len(rows), leads): column k-1 is the level forecast for lead k."""
        ...


class Manifest(BaseModel):
    """Written next to the dataset; the checksum ties every result to the file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_first_day: date
    window_last_day: date
    # The full config/pegel.json the dataset was built with.
    config: dict[str, object]
    git_commit: str
    row_count: int
    sha256: str
    created_at: AwareDatetime
    # A label such as "prod", never a connection string: the manifest may be shared.
    database: str

    @field_validator("database")
    @classmethod
    def _no_url(cls, value: str) -> str:
        if "://" in value or "@" in value:
            raise ValueError("database must be a label, not a connection string")
        return value

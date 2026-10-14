"""The rows of the evaluation dataset: every input as known at each issue time. Pure, no I/O.

Rules (docs/decisions/0008), with t the issue time:

- A value counts only if its available_at <= t. Targets ignore this: they are the truth.
- Hourly windows (`<gauge>_lag_k`, `radar_<area>_lag_k`): lag k is the newest known value with
  t - (k+1) h < valid_at <= t - k h, else NaN. The windows don't overlap, so a gap stays a gap
  and no value fills two lags.
- `kd_last_cm`, `kd_last_at`: the newest known cleaned value, of any age; `kd_last_at` says how
  old it is.
- `kd_base_30d_cm`: the median of the cleaned hourly windows lag 0 to 719 (30 days).
- ICON-D2 column k is the hourly sum with valid_at = floor(t) + (k-1) h, from the newest run
  with available_at <= t; `icon_lead_k` = valid_at - run_at in hours. Archive and live rows
  are passed together, so whichever run is newest wins.
- `target_k`: the cleaned reading closest to floor(t) + k h + 22 min, at most the
  tolerance off (inclusive), else NaN.

All times are UTC, so daylight saving time plays no part.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.core.series import InputForecastValue, SeriesValue
from pegel.evaluation import contract

HOUR = pd.Timedelta(hours=1)
# Targets sit 8 minutes before the hh:30 issue slot, so a reading there is in the hourly run.
TARGET_MINUTE = pd.Timedelta(minutes=22)
BASE_HOURS = 30 * 24
TIME_UNIT = "datetime64[us, UTC]"

Matrix = npt.NDArray[np.float64]


def issue_times(first_day: date, last_day: date, issue_minute: int) -> pd.DatetimeIndex:
    """Every hh:issue_minute UTC from the first day to the last day, both inclusive."""
    first = pd.Timestamp(first_day, tz="UTC") + pd.Timedelta(minutes=issue_minute)
    last = pd.Timestamp(last_day, tz="UTC") + pd.Timedelta(hours=23, minutes=issue_minute)
    return pd.date_range(first, last, freq="h").as_unit("us")


def observed_frame(values: Sequence[SeriesValue]) -> pd.DataFrame:
    """Columns valid_at, value, available_at."""
    return pd.DataFrame(
        {
            "valid_at": _times([value.valid_at for value in values]),
            "value": np.array([value.value for value in values], dtype=float),
            "available_at": _times([value.available_at for value in values]),
        }
    )


def forecast_frame(values: Sequence[InputForecastValue]) -> pd.DataFrame:
    """Columns run_at, valid_at, value, available_at."""
    return pd.DataFrame(
        {
            "run_at": _times([value.run_at for value in values]),
            "valid_at": _times([value.valid_at for value in values]),
            "value": np.array([value.value for value in values], dtype=float),
            "available_at": _times([value.available_at for value in values]),
        }
    )


def build_rows(
    issued_at: pd.DatetimeIndex,
    station_id: str,
    cleaned: pd.DataFrame,
    upstream: Mapping[str, pd.DataFrame],
    radar: Mapping[str, pd.DataFrame],
    icon_mean: pd.DataFrame,
    icon_p90: pd.DataFrame,
    leads: int,
    target_tolerance: pd.Timedelta,
) -> pd.DataFrame:
    """One row per issue time, with exactly `contract.dataset_columns(list(radar), leads)`.

    `cleaned` is the forecast station's (`station_id`) cleaned level, `upstream` the other
    gauges of `contract.GAUGE_PREFIXES` by station id, `radar` the radar series by area.
    """
    issued_at = _checked_issue_times(issued_at)
    columns: dict[str, object] = {contract.ISSUED_AT: issued_at}
    last = newest_known(cleaned, issued_at)
    columns[contract.KD_LAST_CM] = last["value"].to_numpy()
    columns[contract.KD_LAST_AT] = last["valid_at"].to_numpy()
    station_hours = hourly_windows(cleaned, issued_at, BASE_HOURS)
    # DataFrame.median skips NaN and gives NaN for an empty window, without a warning.
    columns[contract.KD_BASE_30D_CM] = pd.DataFrame(station_hours).median(axis=1).to_numpy()
    windows = {station_id: station_hours[:, : contract.LEVEL_LAG_HOURS]}
    for gauge, frame in upstream.items():
        windows[gauge] = hourly_windows(frame, issued_at, contract.LEVEL_LAG_HOURS)
    for gauge in contract.GAUGE_PREFIXES:
        columns.update(zip(contract.level_lag_columns(gauge), windows[gauge].T, strict=True))
    for area, frame in radar.items():
        lags = hourly_windows(frame, issued_at, contract.RADAR_LAG_HOURS)
        columns.update(zip(contract.radar_lag_columns(area), lags.T, strict=True))
    mean, lead_hours = icon_by_lead(icon_mean, issued_at, leads)
    p90, _ = icon_by_lead(icon_p90, issued_at, leads)
    targets = targets_by_lead(cleaned, issued_at, leads, target_tolerance)
    for prefix, matrix in (
        (contract.ICON_MEAN, mean),
        (contract.ICON_P90, p90),
        (contract.ICON_LEAD, lead_hours),
        (contract.TARGET, targets),
    ):
        columns.update(zip(contract.lead_columns(prefix, leads), matrix.T, strict=True))
    return pd.DataFrame(columns)[contract.dataset_columns(list(radar), leads)]


def newest_known(frame: pd.DataFrame, issued_at: pd.DatetimeIndex) -> pd.DataFrame:
    """Per issue time the newest value known then: columns valid_at and value, NaN/NaT if none."""
    ordered = frame.sort_values(["available_at", "valid_at"])
    # Only a value newer than every value known before it can ever be the newest known one.
    records = ordered[ordered["valid_at"] >= ordered["valid_at"].cummax()]
    issues = pd.DataFrame({"issued_at": issued_at})
    merged = pd.merge_asof(
        issues, records, left_on="issued_at", right_on="available_at", direction="backward"
    )
    return merged[["valid_at", "value"]]


def hourly_windows(frame: pd.DataFrame, issued_at: pd.DatetimeIndex, hours: int) -> Matrix:
    """Shape (issue times, hours): column k is lag k as defined in the module docstring."""
    offset = issued_at[0] - issued_at[0].floor("h")
    window_end = (frame["valid_at"] - offset).dt.ceil("h") + offset
    # Whole hours from the window's end until the value is known: it can fill lag k if <= k.
    delay = np.maximum(np.ceil((frame["available_at"] - window_end) / HOUR), 0)
    candidates = pd.DataFrame(
        {"window_end": window_end, "delay": delay, "valid_at": frame["valid_at"]}
    ).assign(value=frame["value"])
    candidates = candidates[candidates["delay"] < hours].sort_values("valid_at")
    # The newest value per window and delay is enough; it cuts minute data to about one per hour.
    candidates = candidates.groupby(["window_end", "delay"], as_index=False).last()
    candidates = candidates.sort_values("valid_at")
    delays = set(candidates["delay"])
    result = np.full((len(issued_at), hours), np.nan)
    newest = pd.Series(dtype=float)
    for lag in range(hours):
        # The known set only grows when some value's delay is reached.
        if lag == 0 or lag in delays:
            known = candidates[candidates["delay"] <= lag]
            newest = known.groupby("window_end")["value"].last()
        result[:, lag] = newest.reindex(issued_at - lag * HOUR).to_numpy()
    return result


def icon_by_lead(
    forecasts: pd.DataFrame, issued_at: pd.DatetimeIndex, leads: int
) -> tuple[Matrix, Matrix]:
    """Shape (issue times, leads) each: the value of the newest known run and its lead in hours."""
    offset = issued_at[0] - issued_at[0].floor("h")
    ordered = forecasts.sort_values("run_at", kind="stable")
    values = np.full((len(issued_at), leads), np.nan)
    lead_hours = np.full((len(issued_at), leads), np.nan)
    for column in range(1, leads + 1):
        # The issue time whose column `column` holds this valid hour.
        candidates = ordered.assign(issue=ordered["valid_at"] - (column - 1) * HOUR + offset)
        known = candidates[candidates["available_at"] <= candidates["issue"]]
        newest = known.groupby("issue").last().reindex(issued_at)
        values[:, column - 1] = newest["value"].to_numpy()
        lead = (newest["valid_at"] - newest["run_at"]).dt.total_seconds() / 3600
        lead_hours[:, column - 1] = lead.to_numpy()
    return values, lead_hours


def targets_by_lead(
    frame: pd.DataFrame, issued_at: pd.DatetimeIndex, leads: int, tolerance: pd.Timedelta
) -> Matrix:
    """Shape (issue times, leads): the reading closest to floor(t) + k h + 22 min, or NaN."""
    readings = frame[["valid_at", "value"]].sort_values("valid_at")
    result = np.full((len(issued_at), leads), np.nan)
    for lead in range(1, leads + 1):
        wanted = pd.DataFrame({"at": issued_at.floor("h") + lead * HOUR + TARGET_MINUTE})
        merged = pd.merge_asof(
            wanted,
            readings,
            left_on="at",
            right_on="valid_at",
            direction="nearest",
            tolerance=tolerance,
        )
        result[:, lead - 1] = merged["value"].to_numpy()
    return result


def _checked_issue_times(issued_at: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """The lag windows assume issue times at one minute of the hour, ascending, in UTC."""
    issued_at = pd.DatetimeIndex(issued_at).as_unit("us")
    if len(issued_at) == 0 or str(issued_at.tz) != "UTC":
        raise ValueError("issue times must be a non-empty UTC index")
    if not issued_at.is_monotonic_increasing or not issued_at.is_unique:
        raise ValueError("issue times must be ascending and unique")
    if len(set(issued_at - issued_at.floor("h"))) != 1 or (issued_at.second != 0).any():
        raise ValueError("issue times must all be at the same minute of the hour")
    return issued_at


def _times(moments: Sequence[datetime]) -> pd.Series:
    return pd.Series(pd.to_datetime(list(moments), utc=True), dtype=TIME_UNIT)

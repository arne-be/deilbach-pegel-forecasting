"""Model features from the history windows of one dataset row per issue time.

Shared by training and the live job, so the two can't drift apart (docs/decisions/0008).
Gaps stay NaN: LightGBM handles them, ridge fills them itself. Target columns are never read.

The error of the lead-1 forecast issued one hour earlier is not built here: it depends on
the model being evaluated, so the model code adds it.
"""

import math
import re

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.evaluation import contract

Array = npt.NDArray[np.float64]
UPSTREAM_LAG_HOURS = 7
UPSTREAM_CHANGE_HOURS = (1, 3)
RADAR_SUM_HOURS = (1, 3, 6, 12, 24, 72, 7 * 24)
STEP_RAIN_HOURS = 6
ICON_PREFIXES = (contract.ICON_MEAN, contract.ICON_P90, contract.ICON_LEAD)
LEAD = "lead"

_RADAR_AREA = re.compile(r"^radar_(.+)_lag_0$")


def features(dataset: pd.DataFrame, *, with_icon: bool = True) -> pd.DataFrame:
    """One row per issue time, on the dataset's index."""
    columns: dict[str, pd.Series] = {}
    kupferdreh = [contract.KD_LAST_CM, *contract.level_lag_columns("kupferdreh")]
    for name in [*kupferdreh, contract.KD_BASE_30D_CM]:
        columns[name] = dataset[name]
    for station_id in ("langenberg", "nierenhof"):
        prefix = contract.GAUGE_PREFIXES[station_id]
        for name in contract.lag_columns(prefix, UPSTREAM_LAG_HOURS):
            columns[name] = dataset[name]
        for hours in UPSTREAM_CHANGE_HOURS:
            change = dataset[f"{prefix}_lag_0"] - dataset[f"{prefix}_lag_{hours}"]
            columns[f"{prefix}_change_{hours}h"] = change
    for area in _radar_areas(dataset):
        for hours in RADAR_SUM_HOURS:
            window = dataset[contract.lag_columns(f"radar_{area}", hours)]
            # A sum with a missing hour would look like less rain, so it stays NaN.
            columns[f"radar_{area}_sum_{hours}h"] = window.sum(axis=1, skipna=False)
    if with_icon:
        for prefix in ICON_PREFIXES:
            for name in contract.lead_columns(prefix, _leads(dataset)):
                columns[name] = dataset[name]
    issued_at = dataset[contract.ISSUED_AT]
    year_fraction = (issued_at.dt.dayofyear - 1 + issued_at.dt.hour / 24) / 365.25
    columns["year_sin"] = np.sin(2 * math.pi * year_fraction)
    columns["year_cos"] = np.cos(2 * math.pi * year_fraction)
    return pd.DataFrame(columns, index=dataset.index)


def step_features(dataset: pd.DataFrame, *, with_icon: bool = True) -> pd.DataFrame:
    """One row per issue time and lead, issue time first, for the pooled hourly-step model.

    Index (dataset position, lead), unnamed so `groupby("lead")` finds the column, and
    `.to_numpy().reshape(n, leads)` maps back. Instead of all ICON-D2 hours, each row gets
    those of the 6 hours up to its step: `step_<prefix>_<j>` is the value at lead k-j, NaN
    for hours before the issue time, which radar covers.
    """
    leads = _leads(dataset)
    base = features(dataset, with_icon=False)
    lead_numbers = np.arange(1, leads + 1)
    long = base.iloc[np.repeat(np.arange(len(base)), leads)]
    long.index = pd.MultiIndex.from_product([base.index, lead_numbers])
    long[LEAD] = np.tile(lead_numbers, len(base))
    if not with_icon:
        return long
    for prefix in ICON_PREFIXES:
        values = dataset[contract.lead_columns(prefix, leads)].to_numpy(dtype=float)
        # Column 0 is NaN and stands for every hour before the issue time.
        padded = np.hstack([np.full((len(values), 1), np.nan), values])
        for hours_before in range(STEP_RAIN_HOURS):
            positions = np.maximum(lead_numbers - hours_before, 0)
            long[f"step_{prefix}_{hours_before}"] = padded[:, positions].ravel()
    return long


# Curated inputs of the v2 change models (docs/models/rain-change-v2.md). Each returns one value
# per row, or per row and lead, and NaN where it can't be computed.


def last_level_age_hours(dataset: pd.DataFrame) -> Array:
    """How old the newest known Kupferdreh reading is at the issue time."""
    age = dataset[contract.ISSUED_AT] - dataset[contract.KD_LAST_AT]
    return age.dt.total_seconds().to_numpy(dtype=np.float64) / 3600


def kupferdreh_change(dataset: pd.DataFrame, hours: int) -> Array:
    """The last level minus the hourly lag `hours` older than the lag the last level falls in.

    Counted from the newest reading, not from lag 0: lag 0 was never known at hh:30 before
    2024-11-20 and known at 98-99 % of issue times since. Lag k covers ages in [k h, (k+1) h),
    so a last level 40 minutes old pairs with lag `hours` and one 70 minutes old with lag
    `hours + 1`.
    """
    lag = np.floor(last_level_age_hours(dataset)) + hours
    lags = dataset[contract.level_lag_columns("kupferdreh")].to_numpy(dtype=np.float64)
    inside = lag < contract.LEVEL_LAG_HOURS
    earlier: Array = np.full(len(dataset), np.nan)
    positions = np.flatnonzero(inside)
    earlier[positions] = lags[positions, lag[inside].astype(int)]
    return dataset[contract.KD_LAST_CM].to_numpy(dtype=np.float64) - earlier


def recent_rise(dataset: pd.DataFrame, time_constant_hours: float) -> Array:
    """The rise of the last day, faded by its age: (peak - trough) · exp(-t / tau).

    Peak and trough are the highest and lowest of the last level and the 24 hourly lags, t the
    hours since the peak. A rise still going on counts in full; a rise long past fades the way
    the fast part of a recession does. NaN when no level of the day is known. Lag k is
    counted as k + 1 hours old, though it is about k h old, so t is about an hour too long;
    the fitted coefficients absorb that, and changing it needs a refit.
    """
    last = dataset[[contract.KD_LAST_CM]].to_numpy(dtype=np.float64)
    lags = dataset[contract.level_lag_columns("kupferdreh")].to_numpy(dtype=np.float64)
    window = np.hstack([last, lags])
    known = np.isfinite(window)
    highs = np.where(known, window, -np.inf)
    lows = np.where(known, window, np.inf)
    rise = highs.max(axis=1) - lows.min(axis=1)
    # Column 0 is the last level, column k+1 lag k: the column index is about the age in hours.
    hours_since_peak = highs.argmax(axis=1).astype(np.float64)
    faded = rise * np.exp(-hours_since_peak / time_constant_hours)
    return np.where(known.any(axis=1), faded, np.nan)


def icon_cumulative(dataset: pd.DataFrame, leads: int) -> Array:
    """Shape (rows, leads): ICON-D2 catchment mean summed over hours 1..k for lead k."""
    hourly = dataset[contract.lead_columns(contract.ICON_MEAN, leads)].to_numpy(dtype=np.float64)
    return np.cumsum(hourly, axis=1)


def summer_hour_terms(dataset: pd.DataFrame) -> Array:
    """Shape (rows, 4): sine and cosine of the issue hour and of twice it; 0 from October to March.

    The level dips by 6 to 8 cm in the early afternoon on summer days, under 1 cm in winter.
    With a coefficient per lead, the terms carry a daily cycle of up to two harmonics.
    """
    issued_at = dataset[contract.ISSUED_AT]
    summer = issued_at.dt.month.between(4, 9).to_numpy()
    angle = 2 * math.pi * (issued_at.dt.hour + issued_at.dt.minute / 60).to_numpy() / 24
    terms = [np.sin(angle), np.cos(angle), np.sin(2 * angle), np.cos(2 * angle)]
    result: Array = np.column_stack(terms) * summer[:, np.newaxis]
    return result


def _radar_areas(dataset: pd.DataFrame) -> list[str]:
    return [m.group(1) for c in dataset.columns if (m := _RADAR_AREA.match(c))]


def _leads(dataset: pd.DataFrame) -> int:
    # Counted from the ICON-D2 columns, not the targets, so features never touch a target.
    return sum(1 for c in dataset.columns if c.removeprefix(f"{contract.ICON_MEAN}_").isdigit())

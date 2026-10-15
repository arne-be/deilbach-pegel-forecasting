"""Model inputs from the history windows of one dataset row per issue time.

Shared by training and the live job, so the two can't drift apart (docs/decisions/0008).
Each function returns one value per row, or per row and lead, and NaN where it can't be
computed. Target columns are never read.
"""

import math

import numpy as np
import numpy.typing as npt
import pandas as pd

from pegel.evaluation import contract

Array = npt.NDArray[np.float64]


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

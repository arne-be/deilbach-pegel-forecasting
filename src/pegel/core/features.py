"""Model features from the history windows of one dataset row per issue time.

Shared by training and the live job, so the two can't drift apart (docs/decisions/0008).
Gaps stay NaN: LightGBM handles them, ridge fills them itself. Target columns are never read.

The error of the lead-1 forecast issued one hour earlier is not built here: it depends on
the model being evaluated, so the model code adds it.
"""

import math
import re

import numpy as np
import pandas as pd

from pegel.evaluation import contract

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


def _radar_areas(dataset: pd.DataFrame) -> list[str]:
    return [m.group(1) for c in dataset.columns if (m := _RADAR_AREA.match(c))]


def _leads(dataset: pd.DataFrame) -> int:
    # Counted from the ICON-D2 columns, not the targets, so features never touch a target.
    return sum(1 for c in dataset.columns if c.removeprefix(f"{contract.ICON_MEAN}_").isdigit())

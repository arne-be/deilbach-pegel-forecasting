"""Flood events, observed and forecast levels on the target-time grid, and the lag check.

Times are target times: an issue time plus the lead in whole hours, so every forecast and the
observed level share one hourly grid on hh:30. The observed level is the cleaned target series
rebuilt from the dataset.
"""

from typing import Any

import numpy as np
import pandas as pd

from pegel.evaluation import contract
from pegel.evaluation.metrics import high_water, with_truth

MAX_SHIFT_HOURS = 24
# Flood events (docs/evaluation.md#flood-events): a rise of RISE_CM within RISE_HOURS to above
# high water starts one; back within BACK_CM of the pre-event level, or below high water and
# falling less than FLAT_CM over FLAT_HOURS, ends it.
RISE_CM = 15
RISE_HOURS = 24
BACK_CM = 5
FLAT_CM = 2
FLAT_HOURS = 24

_HOUR = pd.Timedelta(hours=1)
FLOOD_EVENT_COLUMNS = ["start", "end", "pre_event_cm", "peak_cm", "peak_at"]


def _target_time(rows: pd.DataFrame) -> pd.Series:
    return rows[contract.ISSUED_AT] + rows["lead"] * _HOUR


def _hourly(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    grid = pd.date_range(series.index.min(), series.index.max(), freq="h")
    return series.reindex(grid)


def observed_levels(dataset: pd.DataFrame, leads: int) -> pd.Series:
    """The cleaned level at each target time, on a full hourly grid (NaN where missing)."""
    targets = dataset.melt(
        id_vars=[contract.ISSUED_AT],
        value_vars=contract.lead_columns(contract.TARGET, leads),
        var_name="lead",
        value_name="level",
    )
    targets["lead"] = targets["lead"].str.rsplit("_", n=1).str[1].astype(int)
    targets["at"] = _target_time(targets)
    # Every lead pointing at the same time holds the same reading; take any known one.
    return _hourly(targets.dropna(subset=["level"]).groupby("at")["level"].first())


def forecast_levels(predictions: pd.DataFrame, model: str, lead: int) -> pd.Series:
    """One model's lead-k forecasts by target time, on a full hourly grid."""
    rows = predictions[(predictions["model"] == model) & (predictions["lead"] == lead)]
    return _hourly(pd.Series(rows["prediction"].to_numpy(), index=_target_time(rows)).sort_index())


def _flood_end(values: np.ndarray, rise_at: int, pre_event_cm: float, high_water_cm: float) -> int:
    """The first hour after the rise back near the pre-event level, or below high water and
    flat; the last hour if neither comes. NaN hours never match, so gaps are skipped."""
    for at in range(rise_at + 1, len(values)):
        if values[at] <= pre_event_cm + BACK_CM:
            return at
        if at < FLAT_HOURS:
            continue
        fall = values[at - FLAT_HOURS] - values[at]
        if values[at] < high_water_cm and 0 <= fall < FLAT_CM:
            return at
    return len(values) - 1


def flood_events(levels: pd.Series, high_water_cm: float) -> pd.DataFrame:
    """Flood events on an hourly level series on a full grid (NaN where missing).

    An hour above high water that is at least RISE_CM above the lowest level of the RISE_HOURS
    before it starts an event at that lowest hour (the pre-event level). The look-back never
    reaches into the previous event. See `_flood_end` for the end; a new rise before the end
    belongs to the same event.
    """
    values = levels.to_numpy(dtype=float)
    found: list[dict[str, Any]] = []
    earliest = 0
    at = RISE_HOURS
    while at < len(values):
        low = max(at - RISE_HOURS, earliest)
        before = values[low:at]
        if (
            not values[at] > high_water_cm
            or np.isnan(before).all()
            or values[at] - np.nanmin(before) < RISE_CM
        ):
            at += 1
            continue
        start = low + int(np.nanargmin(before))
        end = _flood_end(values, at, values[start], high_water_cm)
        event = levels.iloc[start : end + 1]
        found.append(
            {
                "start": levels.index[start],
                "end": levels.index[end],
                "pre_event_cm": values[start],
                "peak_cm": event.max(),
                "peak_at": event.idxmax(),
            }
        )
        earliest = at = end + 1
    return pd.DataFrame(found, columns=FLOOD_EVENT_COLUMNS)


def lag_check(
    predictions: pd.DataFrame, dataset: pd.DataFrame, leads: int, high_water_cm: float
) -> pd.DataFrame:
    """The shift s (0 to MAX_SHIFT_HOURS) that minimises MAE between the forecast for time t
    and the observed level at t - s, on high-water rows, per model and lead.

    A shift equal to the lead means the model is a delayed persistence.
    """
    rows = with_truth(predictions, dataset)
    rows = rows[high_water(rows, high_water_cm)]
    observed = observed_levels(dataset, leads)
    at = _target_time(rows)
    result: list[dict[str, object]] = []
    for (model, lead), group in rows.groupby(["model", "lead"]):
        group_at = at[group.index]
        prediction = group["prediction"].to_numpy()
        mae = pd.Series(
            [
                pd.Series(prediction - observed.reindex(group_at - shift * _HOUR).to_numpy())
                .abs()
                .mean()
                for shift in range(MAX_SHIFT_HOURS + 1)
            ]
        )
        if mae.isna().all():
            continue
        best = int(np.nanargmin(mae.to_numpy()))
        result.append(
            {"model": model, "lead": lead, "n": len(group), "shift_hours": best, "mae": mae[best]}
        )
    return pd.DataFrame(result, columns=["model", "lead", "n", "shift_hours", "mae"])

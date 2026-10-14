"""Flood events, alarms, warning lead times and the lag check (docs/decisions/0008).

Times are target times: an issue time plus the lead in whole hours, so every forecast and the
observed level share one hourly grid on hh:30. The observed level is the cleaned target series
rebuilt from the dataset.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from pegel.evaluation import contract
from pegel.evaluation.metrics import high_water, with_truth

# Exceedances whose peaks are less than this apart are one event.
MERGE_HOURS = 24
MAX_SHIFT_HOURS = 24

_HOUR = pd.Timedelta(hours=1)
EPISODE_COLUMNS = ["start", "end", "peak_at", "peak_cm"]


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


def episodes(levels: pd.Series, threshold_cm: float) -> pd.DataFrame:
    """Spells above the threshold, merged into one episode while a spell's peak is less than
    MERGE_HOURS after the highest peak of the episode so far."""
    above = levels > threshold_cm
    spell = (above != above.shift()).cumsum()[above]
    merged: list[dict[str, Any]] = []
    for _, spell_levels in levels[above].groupby(spell):
        peak_at = spell_levels.idxmax()
        candidate = {
            "start": spell_levels.index[0],
            "end": spell_levels.index[-1],
            "peak_at": peak_at,
            "peak_cm": spell_levels.max(),
        }
        if merged and peak_at - merged[-1]["peak_at"] < pd.Timedelta(hours=MERGE_HOURS):
            last = merged[-1]
            last["end"] = candidate["end"]
            if candidate["peak_cm"] > last["peak_cm"]:
                last["peak_at"], last["peak_cm"] = peak_at, candidate["peak_cm"]
            continue
        merged.append(candidate)
    return pd.DataFrame(merged, columns=EPISODE_COLUMNS)


def peak_errors(predictions: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Peak errors of the forecasts issued `lead` hours before each peak.

    The rule: for lead k, take the whole forecast issued k hours before the observed peak. Its
    highest value minus the observed peak is the height error; its value at the peak (lead k)
    minus the observed peak is `at_peak_error_cm`. The target time of the highest value minus
    the peak time is the timing error in hours (positive is late). A forecast whose highest
    value is not above its first value has no peak to time, so its timing error is NaN; that
    keeps persistence and other flat or falling forecasts out of the timing.
    """
    rows: list[dict[str, object]] = []
    known = predictions.dropna(subset=["prediction"]).sort_values("lead")
    peaks = zip(events["peak_at"], events["peak_cm"], strict=True)
    for event_number, (peak_at, peak_cm) in enumerate(peaks, start=1):
        for lead in range(1, int(predictions["lead"].max()) + 1):
            issued_at = pd.Timestamp(peak_at) - lead * _HOUR
            forecast = known[known[contract.ISSUED_AT] == issued_at]
            for model, trajectory in forecast.groupby("model"):
                best = trajectory.iloc[trajectory["prediction"].argmax()]
                at_peak = trajectory.loc[trajectory["lead"] == lead, "prediction"]
                has_peak = best["prediction"] > trajectory["prediction"].iloc[0]
                rows.append(
                    {
                        "event": event_number,
                        "peak_at": peak_at,
                        "model": model,
                        "lead": lead,
                        "height_error_cm": best["prediction"] - peak_cm,
                        "at_peak_error_cm": (
                            at_peak.iloc[0] - peak_cm if not at_peak.empty else np.nan
                        ),
                        "timing_error_hours": int(best["lead"]) - lead if has_peak else np.nan,
                    }
                )
    return pd.DataFrame(
        rows,
        columns=[
            "event",
            "peak_at",
            "model",
            "lead",
            "height_error_cm",
            "at_peak_error_cm",
            "timing_error_hours",
        ],
    )


def _overlap_count(episodes_a: pd.DataFrame, episodes_b: pd.DataFrame) -> int:
    """How many episodes of `episodes_a` overlap at least one of `episodes_b` in time."""
    return sum(
        bool(((episodes_b["start"] <= end) & (episodes_b["end"] >= start)).any())
        for start, end in zip(episodes_a["start"], episodes_a["end"], strict=True)
    )


def alarms(
    predictions: pd.DataFrame, observed: pd.Series, thresholds_cm: Sequence[float]
) -> pd.DataFrame:
    """Hits, misses and false alarms per model, lead and threshold, counted by episode.

    For lead k, the forecast episodes are the spells of the lead-k forecasts above the
    threshold, merged like events. An observed episode with an overlapping forecast episode is
    a hit, without one a miss; a forecast episode overlapping no observed one is a false alarm.
    Only observed times the lead's forecasts cover count.
    """
    rows: list[dict[str, object]] = []
    for model in sorted(predictions["model"].unique()):
        for lead in sorted(predictions["lead"].unique()):
            forecast = forecast_levels(predictions, model, lead)
            covered = observed[forecast.index.min() : forecast.index.max()]
            for threshold in thresholds_cm:
                seen = episodes(covered, threshold)
                warned = episodes(forecast, threshold)
                hits = _overlap_count(seen, warned)
                false_alarms = len(warned) - _overlap_count(warned, seen)
                rows.append(
                    {
                        "model": model,
                        "lead": lead,
                        "threshold_cm": threshold,
                        "hits": hits,
                        "misses": len(seen) - hits,
                        "false_alarms": false_alarms,
                    }
                )
    return pd.DataFrame(rows)


def warning_lead_times(
    predictions: pd.DataFrame, observed: pd.Series, thresholds_cm: Sequence[float]
) -> pd.DataFrame:
    """For each observed crossing and model, the first forecast that showed it.

    A crossing is the start of an observed episode above the threshold. A forecast shows it
    when it was issued before the crossing and any of its values is above the threshold, so a
    forecast that has the rise a few hours early or late still counts as a warning.
    The first such forecast counts even if later forecasts drop the crossing again.
    `warning_hours` is NaN when no forecast showed the crossing. Crossings without any forecast
    issued in the hours before them are left out.
    """
    longest = pd.Timedelta(hours=int(predictions["lead"].max()))
    rows: list[dict[str, object]] = []
    for threshold in thresholds_cm:
        for crossing_at in episodes(observed, threshold)["start"]:
            issued_at = predictions[contract.ISSUED_AT]
            before = predictions[(issued_at < crossing_at) & (issued_at >= crossing_at - longest)]
            for model, forecasts in before.groupby("model"):
                showing = forecasts.loc[forecasts["prediction"] > threshold, contract.ISSUED_AT]
                first = showing.min() if not showing.empty else pd.NaT
                rows.append(
                    {
                        "model": model,
                        "threshold_cm": threshold,
                        "crossing_at": crossing_at,
                        "first_warning_at": first,
                        "warning_hours": (crossing_at - first) / _HOUR,
                    }
                )
    return pd.DataFrame(
        rows, columns=["model", "threshold_cm", "crossing_at", "first_warning_at", "warning_hours"]
    )


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

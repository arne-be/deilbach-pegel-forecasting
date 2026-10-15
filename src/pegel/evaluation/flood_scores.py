"""Flood forecasts scored per event and lead, and false alarms (docs/evaluation.md#flood-forecasts).

Events come from `events.flood_events` on the whole window, so the previous event of the first
test event and the events near a false alarm can lie in training. Only events peaking in a
test period are scored.
"""

from collections.abc import Collection
from datetime import timedelta

import numpy as np
import pandas as pd

from pegel.evaluation import contract
from pegel.evaluation.events import FLOOD_EVENT_COLUMNS, RISE_CM

# Hours before the observed peak at which each event is scored.
PEAK_LEADS = (24, 12, 6, 3, 1)
# Predicted: the forecast saw more than this share of the rise from the pre-event level.
PREDICTED_SIZE = 0.5
# A false alarm needs a last known level at most this old; otherwise the issue time is skipped.
STALE_HOURS = 3
HOURS_PER_MONTH = 24 * 365.25 / 12

_HOUR = pd.Timedelta(hours=1)
EVENT_COLUMNS = ["event", "fold", *FLOOD_EVENT_COLUMNS]
PEAK_COLUMNS = [
    "model",
    "event",
    "fold",
    "lead_hours",
    "issued_at",
    "forecast_peak_cm",
    "forecast_peak_at",
    "size",
    "timing_hours",
    "timing_at_least",
    "predicted",
]
FALSE_ALARM_COLUMNS = ["model", "count", "months", "per_month"]


def scored_events(floods: pd.DataFrame, folds: Collection[str]) -> pd.DataFrame:
    """The events peaking in the test period of one of `folds`, numbered from 1 by peak time."""
    spans = {
        fold.name: (
            pd.Timestamp(fold.test_start, tz="UTC"),
            pd.Timestamp(fold.test_end + timedelta(days=1), tz="UTC"),
        )
        for fold in contract.FOLDS
        if fold.name in folds
    }
    fold_of = [
        next((name for name, (start, end) in spans.items() if start <= peak_at < end), None)
        for peak_at in floods["peak_at"]
    ]
    scored = floods.assign(fold=pd.Series(fold_of, index=floods.index)).dropna(subset=["fold"])
    scored = scored.sort_values("peak_at").reset_index(drop=True)
    scored.insert(0, "event", scored.index + 1)
    return scored[EVENT_COLUMNS]


def _forecasts(predictions: pd.DataFrame, leads: int) -> pd.DataFrame:
    """One row per model and issue time, a column per lead 1 to `leads` (NaN where missing)."""
    keys = ["model", contract.ISSUED_AT, "lead"]
    wide = predictions.set_index(keys)["prediction"].unstack("lead")
    return wide.reindex(columns=range(1, leads + 1))


def _scored(
    values: np.ndarray, issued_at: pd.Timestamp, event: pd.Series, lead: int
) -> dict[str, object]:
    """Size, timing and predicted of one complete forecast. The first of tied hours counts."""
    peak_lead = int(np.argmax(values)) + 1
    size = (values[peak_lead - 1] - event["pre_event_cm"]) / (
        event["peak_cm"] - event["pre_event_cm"]
    )
    return {
        "forecast_peak_cm": values[peak_lead - 1],
        "forecast_peak_at": issued_at + peak_lead * _HOUR,
        "size": size,
        "timing_hours": peak_lead - lead,
        # The highest value at the last hour may only be the edge of a later peak.
        "timing_at_least": peak_lead == len(values) and lead < len(values),
        "predicted": size > PREDICTED_SIZE,
    }


def flood_peaks(
    predictions: pd.DataFrame, floods: pd.DataFrame, scored: pd.DataFrame, leads: int
) -> pd.DataFrame:
    """One row per model, scored event and lead in PEAK_LEADS, in PEAK_COLUMNS.

    `floods` are all events, `scored` the test events from `scored_events`. A forecast is
    missing (NaN values) when it has no row or a missing lead, or when its issue time is before
    the end of the previous event.
    """
    forecasts = _forecasts(predictions, leads)
    rows: list[dict[str, object]] = []
    for _, event in scored.iterrows():
        previous_end = floods.loc[floods["end"] < event["start"], "end"].max()
        for model in sorted(predictions["model"].unique()):
            for lead in PEAK_LEADS:
                issued_at = event["peak_at"] - lead * _HOUR
                row: dict[str, object] = {
                    "model": model,
                    "event": event["event"],
                    "fold": event["fold"],
                    "lead_hours": lead,
                    contract.ISSUED_AT: issued_at,
                }
                key = (model, issued_at)
                values = forecasts.loc[key].to_numpy(float) if key in forecasts.index else None
                after_previous = pd.isna(previous_end) or issued_at >= previous_end
                if values is not None and after_previous and not np.isnan(values).any():
                    row.update(_scored(values, issued_at, event, lead))
                rows.append(row)
    table = pd.DataFrame(rows).reindex(columns=PEAK_COLUMNS)
    for column in ("timing_at_least", "predicted"):
        table[column] = table[column].astype("boolean")
    return table


def false_alarms(
    predictions: pd.DataFrame,
    dataset: pd.DataFrame,
    floods: pd.DataFrame,
    high_water_cm: float,
    leads: int,
) -> pd.DataFrame:
    """False alarms per model, and per month of issue times scored, in FALSE_ALARM_COLUMNS.

    An alarm is a forecast whose peak is above high water and at least RISE_CM above the last
    known level, which must be at most STALE_HOURS old. It is false when no event in `floods`
    is running at its issue time or starts within `leads` hours after it. A run of hourly
    issue times with false alarms counts once; a skipped hour (stale level, no forecast) inside
    a run doesn't split it.
    """
    last = dataset.set_index(contract.ISSUED_AT)[[contract.KD_LAST_CM, contract.KD_LAST_AT]]
    starts = floods["start"].to_numpy("datetime64[ns]")
    ends = floods["end"].to_numpy("datetime64[ns]")
    rows: list[dict[str, object]] = []
    for model, own in predictions.groupby("model"):
        peaks = own.groupby(contract.ISSUED_AT)["prediction"].max()
        reading = last.reindex(peaks.index)
        fresh = peaks.index - reading[contract.KD_LAST_AT] <= pd.Timedelta(hours=STALE_HOURS)
        rise = peaks - reading[contract.KD_LAST_CM]
        alarm_at = peaks.index[fresh & (peaks > high_water_cm) & (rise >= RISE_CM)]
        at = alarm_at.to_numpy("datetime64[ns]")[:, None]
        horizon = np.timedelta64(leads, "h")
        near_event = ((starts[None, :] <= at + horizon) & (ends[None, :] >= at)).any(axis=1)
        # 1 for a false alarm, 0 for a checked hour without one, NaN for a skipped hour, which
        # carries the state before it.
        hourly = pd.date_range(peaks.index.min(), peaks.index.max(), freq=_HOUR)
        state = pd.Series(np.nan, index=hourly)
        state[peaks.index[fresh]] = 0.0
        state[alarm_at[~near_event]] = 1.0
        raised = state.ffill().fillna(0.0).astype(bool)
        count = int((raised & ~raised.shift(fill_value=False)).sum())
        months = own[contract.ISSUED_AT].nunique() / HOURS_PER_MONTH
        rows.append({"model": model, "count": count, "months": months, "per_month": count / months})
    return pd.DataFrame(rows, columns=FALSE_ALARM_COLUMNS)

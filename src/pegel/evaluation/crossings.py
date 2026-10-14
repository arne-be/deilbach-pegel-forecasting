"""Crossing warnings and false alarms per threshold (docs/decisions/0008).

A warning only helps if it comes before the level crosses a threshold. So each threshold is
its own warning, scored on first crossings, and only forecasts issued below the threshold
count. Times are target times on the hourly hh:30 grid, as in `events`.

The rules:

- An observed crossing is an hour above the threshold whose previous hour was not above it.
  It is a first crossing when no hour in the RE_CROSSING_HOURS before it was above the
  threshold. Re-crossings are left out of the warnings: during a flood a forecast that stays
  high shows them without foreseeing anything.
- A forecast crossing is an issue time whose last known level (`kd_last_cm`, what the model
  saw) is not above the threshold and whose forecast is above it at some lead. Its time is
  the target time of the first such lead.
- A first crossing is warned by every forecast crossing issued before it and at most
  MATCH_HOURS away from it. The warning time is the crossing time minus the earliest such
  issue time, even if later forecasts drop the crossing again.
- A forecast crossing with no observed crossing (first or re-crossing) within MATCH_HOURS is
  false. A run of hourly issue times with false forecast crossings is one false alarm, so a
  warning that stays up for many hours counts once.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from pegel.evaluation import contract

RE_CROSSING_HOURS = 24
MATCH_HOURS = 6
HOURS_PER_MONTH = 24 * 365.25 / 12

_HOUR = pd.Timedelta(hours=1)
CROSSING_COLUMNS = [
    "model",
    "threshold_cm",
    "crossing_at",
    "first_warning_at",
    "warning_hours",
    "hit_3h",
    "hit_6h",
]
FALSE_ALARM_COLUMNS = ["model", "threshold_cm", "count", "months", "per_month"]


def observed_crossings(observed: pd.Series, threshold_cm: float) -> pd.DataFrame:
    """Every upward crossing (`crossing_at`) and whether it is a re-crossing."""
    above = observed > threshold_cm
    starts = above & ~above.shift(fill_value=False)
    recent = above.shift(fill_value=False).astype(float).rolling(f"{RE_CROSSING_HOURS}h").max()
    return pd.DataFrame(
        {"crossing_at": observed.index[starts], "re_crossing": recent[starts].astype(bool).values}
    )


def forecast_crossings(
    predictions: pd.DataFrame, last_levels: pd.Series, threshold_cm: float
) -> pd.DataFrame:
    """Per model, the issue times whose forecast crosses the threshold from below, with the
    target time of the first lead above it (`crossing_at`)."""
    frames = []
    for model, rows in predictions.groupby("model"):
        wide = rows.pivot_table(
            index=contract.ISSUED_AT, columns="lead", values="prediction", aggfunc="first"
        )
        above = wide.gt(threshold_cm)
        level = last_levels.reindex(wide.index)
        crossing = above.any(axis=1) & ~(level > threshold_cm).to_numpy()
        if not crossing.any():
            continue
        first_lead = above[crossing].idxmax(axis=1).astype(int)
        crossing_at = first_lead.index + pd.to_timedelta(first_lead.to_numpy(), unit="h")
        frames.append(
            pd.DataFrame(
                {"model": model, contract.ISSUED_AT: first_lead.index, "crossing_at": crossing_at}
            )
        )
    if frames:
        return pd.concat(frames, ignore_index=True)
    no_times = pd.Series(dtype="datetime64[ns, UTC]")
    return pd.DataFrame(
        {"model": pd.Series(dtype=str), contract.ISSUED_AT: no_times, "crossing_at": no_times}
    )


def crossing_warnings(
    predictions: pd.DataFrame,
    observed: pd.Series,
    last_levels: pd.Series,
    thresholds_cm: Sequence[float],
) -> pd.DataFrame:
    """One row per model, threshold and first crossing: the first warning and its lead.

    A crossing counts for a model when the model has a forecast issued in the
    RE_CROSSING_HOURS before it. `warning_hours` is NaN when nothing warned.
    """
    window = pd.Timedelta(hours=RE_CROSSING_HOURS)
    match = pd.Timedelta(hours=MATCH_HOURS)
    issued = predictions[[contract.ISSUED_AT, "model"]].drop_duplicates()
    rows: list[dict[str, object]] = []
    for threshold in thresholds_cm:
        seen = observed_crossings(observed, threshold)
        warned = forecast_crossings(predictions, last_levels, threshold)
        for crossing_at in seen.loc[~seen["re_crossing"], "crossing_at"]:
            at = issued[contract.ISSUED_AT]
            covering = issued[(at >= crossing_at - window) & (at < crossing_at)]
            for model in sorted(covering["model"].unique()):
                own = warned[warned["model"] == model]
                early = own[contract.ISSUED_AT] < crossing_at
                near = (own["crossing_at"] - crossing_at).abs() <= match
                first = own.loc[early & near, contract.ISSUED_AT].min()
                hours = (crossing_at - first) / _HOUR if pd.notna(first) else np.nan
                rows.append(
                    {
                        "model": model,
                        "threshold_cm": threshold,
                        "crossing_at": crossing_at,
                        "first_warning_at": first,
                        "warning_hours": hours,
                        "hit_3h": bool(hours >= 3),
                        "hit_6h": bool(hours >= 6),
                    }
                )
    return pd.DataFrame(rows, columns=CROSSING_COLUMNS)


def false_alarms(
    predictions: pd.DataFrame,
    observed: pd.Series,
    last_levels: pd.Series,
    thresholds_cm: Sequence[float],
) -> pd.DataFrame:
    """False alarms per model and threshold, and per month of issue times scored."""
    months = predictions.groupby("model")[contract.ISSUED_AT].nunique() / HOURS_PER_MONTH
    rows: list[dict[str, object]] = []
    for threshold in thresholds_cm:
        seen = observed_crossings(observed, threshold)["crossing_at"].to_numpy("datetime64[ns]")
        warned = forecast_crossings(predictions, last_levels, threshold)
        for model in sorted(months.index):
            own = warned[warned["model"] == model].sort_values(contract.ISSUED_AT)
            forecast_at = own["crossing_at"].to_numpy("datetime64[ns]")
            gaps = np.abs(forecast_at[:, None] - seen[None, :])
            matched = (gaps <= np.timedelta64(MATCH_HOURS, "h")).any(axis=1)
            false_at = own.loc[~matched, contract.ISSUED_AT]
            count = int((false_at.diff() != _HOUR).sum())
            rows.append(
                {
                    "model": model,
                    "threshold_cm": threshold,
                    "count": count,
                    "months": months[model],
                    "per_month": count / months[model],
                }
            )
    return pd.DataFrame(rows, columns=FALSE_ALARM_COLUMNS)

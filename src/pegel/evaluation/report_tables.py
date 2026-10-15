"""The tables and the summary of the run report, from the files `score` wrote.

No matplotlib here, so the tables stay usable and testable without the plots.
"""

from collections.abc import Sequence
from typing import Any

import pandas as pd

from pegel.evaluation import contract
from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL, SUBSET_HIGH_WATER

TABLE_LEADS = (1, 3, 6, 12, 24)
ALARM_LEADS = (1, 6, 12, 24)
PEAK_LEADS = (6, 12)
# A warning this many hours ahead leaves time to act.
WARNED_HOURS = 3
# A warning this many hours ahead is early enough to prepare.
EARLY_HOURS = 6
# A crossing with the level above the threshold this long before it continues a flood.


def model_order(models: Sequence[str]) -> list[str]:
    """Persistence first, the rest by name, so tables and colours stay in one order."""
    unique = set(models)
    return [PERSISTENCE] * (PERSISTENCE in unique) + sorted(unique - {PERSISTENCE})


def _by_model_and(table: pd.DataFrame, models: Sequence[str]) -> pd.DataFrame:
    """Rows indexed by (model, second key), sorted by model order, then the second key."""
    order = model_order(models)
    return table.reindex(sorted(table.index, key=lambda key: (order.index(key[0]), key[1])))


def lead_table(scores: pd.DataFrame, subset: str) -> pd.DataFrame:
    """MAE at a few leads, mean MAE and mean skill over all leads, per model, pooled over folds."""
    pooled = scores[(scores["fold"] == ALL_FOLDS) & (scores["subset"] == subset)]
    mae = pooled.pivot(index="model", columns="lead", values="mae")
    table = mae[list(TABLE_LEADS)].rename(columns=lambda lead: f"+{lead} h")
    last_lead = int(mae.columns.max())
    table[f"mean 1-{last_lead} h"] = mae.mean(axis=1)
    table["mean skill"] = pooled.groupby("model")["skill"].mean()
    return table.reindex(model_order(list(table.index)))


def alarm_table(alarms: pd.DataFrame) -> pd.DataFrame:
    """Hits / misses / false alarms per model and threshold at a few leads."""
    rows = alarms[alarms["lead"].isin(ALARM_LEADS)].copy()
    rows["text"] = (
        rows["hits"].astype(str)
        + " / "
        + rows["misses"].astype(str)
        + " / "
        + rows["false_alarms"].astype(str)
    )
    table = rows.pivot(index=["model", "threshold_cm"], columns="lead", values="text")
    table = table.rename(columns=lambda lead: f"+{lead} h")
    return _by_model_and(table, list(rows["model"]))


def observed_from_predictions(predictions: pd.DataFrame) -> pd.Series:
    """The observed cleaned level by target time, from the targets in the predictions."""
    known = predictions.dropna(subset=["target"])
    at = known[contract.ISSUED_AT] + known["lead"] * pd.Timedelta(hours=1)
    return known["target"].groupby(at).first().sort_index()


def crossing_table(crossings: pd.DataFrame) -> pd.DataFrame:
    """Per model and threshold: first crossings, how many were warned WARNED_HOURS and
    EARLY_HOURS ahead,
    and the median hours ahead of the warned ones."""
    grouped = crossings.groupby(["model", "threshold_cm"])["warning_hours"]
    table = pd.DataFrame(
        {
            "crossings": grouped.size(),
            f"warned >= {WARNED_HOURS} h": grouped.agg(
                lambda hours: int((hours >= WARNED_HOURS).sum())
            ),
            f"warned >= {EARLY_HOURS} h": grouped.agg(
                lambda hours: int((hours >= EARLY_HOURS).sum())
            ),
            "median hours ahead": grouped.median(),
        }
    )
    return _by_model_and(table, list(crossings["model"]))


def false_alarm_table(false_alarms: pd.DataFrame) -> pd.DataFrame:
    """False alarms per model and threshold: count and per month of issue times."""
    table = false_alarms.set_index(["model", "threshold_cm"])[["count", "per_month"]]
    return _by_model_and(table, list(false_alarms["model"]))


def peak_table(peaks: pd.DataFrame) -> pd.DataFrame:
    """Mean peak errors over the flood events per model, for the forecasts issued 6 and 12
    hours before each peak."""
    rows = peaks[peaks["lead"].isin(PEAK_LEADS)].assign(
        abs_height=lambda frame: frame["height_error_cm"].abs()
    )
    grouped = rows.groupby(["model", "lead"])
    table = pd.DataFrame(
        {
            "events": grouped.size(),
            "mean abs height error (cm)": grouped["abs_height"].mean(),
            "mean at-peak error (cm)": grouped["at_peak_error_cm"].mean(),
            "mean timing error (h)": grouped["timing_error_hours"].mean(),
        }
    )
    return _by_model_and(table, list(rows["model"]))


def lag_table(lag: pd.DataFrame) -> pd.DataFrame:
    """The lag check's best shift on high water at +6 h and +12 h; equal to the lead means a
    delayed persistence."""
    rows = lag[lag["lead"].isin(PEAK_LEADS)]
    table = rows.pivot(index="model", columns="lead", values="shift_hours")
    table = table.rename(columns=lambda lead: f"shift at +{lead} h")
    return table.reindex(model_order(list(table.index)))


def _headline_numbers(
    scores: pd.DataFrame, crossings: pd.DataFrame, false_alarms: pd.DataFrame, flood_cm: float
) -> pd.DataFrame:
    """Per model: mean MAE over all leads on `all` and high water, MAE and skill at high water
    at the last lead, first crossings of `flood_cm` warned WARNED_HOURS ahead and in all,
    and false alarms per month at `flood_cm`."""
    pooled = scores[scores["fold"] == ALL_FOLDS]
    mean_mae = pooled.pivot_table(index="model", columns="subset", values="mae", aggfunc="mean")
    high = pooled[pooled["subset"] == SUBSET_HIGH_WATER]
    last = high[high["lead"] == high["lead"].max()].set_index("model")
    numbers = pd.DataFrame(
        {
            "mae_all": mean_mae.get(SUBSET_ALL),
            "mae_high": mean_mae.get(SUBSET_HIGH_WATER),
            "mae_high_last": last["mae"],
            "skill_high_last": last["skill"],
        },
        index=model_order(list(pooled["model"])),
    )
    if not crossings.empty:
        hours = crossings[crossings["threshold_cm"] == flood_cm].groupby("model")["warning_hours"]
        numbers["warned"] = hours.agg(lambda values: int((values >= WARNED_HOURS).sum()))
        numbers["crossings"] = hours.size()
    if not false_alarms.empty:
        at_flood = false_alarms[false_alarms["threshold_cm"] == flood_cm]
        numbers["false_per_month"] = at_flood.set_index("model")["per_month"]
    return numbers


def _number(value: Any, digits: int) -> str:
    return "-" if pd.isna(value) else f"{value:.{digits}f}"


def headline_table(
    scores: pd.DataFrame, crossings: pd.DataFrame, false_alarms: pd.DataFrame, flood_cm: float
) -> pd.DataFrame:
    """One row per model with the numbers to compare first, already formatted."""
    numbers = _headline_numbers(scores, crossings, false_alarms, flood_cm)
    last_lead = int(scores["lead"].max())
    flood = f"{flood_cm:g} cm"
    columns: dict[str, list[str]] = {
        "mean MAE all (cm)": [_number(v, 1) for v in numbers["mae_all"]],
        "mean MAE high water (cm)": [_number(v, 1) for v in numbers["mae_high"]],
        f"MAE +{last_lead} h high water (cm)": [_number(v, 1) for v in numbers["mae_high_last"]],
        f"skill +{last_lead} h high water": [_number(v, 2) for v in numbers["skill_high_last"]],
    }
    if "warned" in numbers:
        columns[f"{flood} crossings warned >= {WARNED_HOURS} h"] = [
            "-" if pd.isna(total) else f"{warned:.0f} of {total:.0f}"
            for warned, total in zip(numbers["warned"], numbers["crossings"], strict=True)
        ]
    if "false_per_month" in numbers:
        columns[f"false alarms per month at {flood}"] = [
            _number(v, 2) for v in numbers["false_per_month"]
        ]
    return pd.DataFrame(columns, index=pd.Index(numbers.index, name="model"))


def summary(
    scores: pd.DataFrame, crossings: pd.DataFrame, false_alarms: pd.DataFrame, flood_cm: float
) -> list[str]:
    """Two to four plain sentences with the facts a reader looks for first."""
    numbers = _headline_numbers(scores, crossings, false_alarms, flood_cm)
    last_lead = int(scores["lead"].max())
    if len(numbers) == 1:
        model = numbers.index[0]
        lines = [
            f"Mean MAE of {model} over leads 1-{last_lead} h: {numbers['mae_all'].iloc[0]:.1f} cm"
            f" over all issue times, {numbers['mae_high'].iloc[0]:.1f} cm at high water."
        ]
    else:
        parts = []
        for column, where in (("mae_all", "over all issue times"), ("mae_high", "at high water")):
            values = numbers[column]
            # Every model that prints the same as the best one, so a tie isn't hidden.
            best = values[values.round(1) == round(values.min(), 1)].sort_values().index
            names = " and ".join([", ".join(best[:-1]), best[-1]] if len(best) > 1 else best)
            baseline = values.get(PERSISTENCE)
            versus = "" if pd.isna(baseline) else f"; persistence {baseline:.1f} cm"
            parts.append(f"{names} {where} ({values.min():.1f} cm{versus})")
        lines = [f"Lowest mean MAE over leads 1-{last_lead} h: {parts[0]}, {parts[1]}."]
    scored = numbers.dropna(subset=["crossings"]) if "warned" in numbers else numbers.iloc[:0]
    if not scored.empty:
        warned, total = scored["warned"], scored["crossings"]
        # Only the best model and persistence; the table has every model.
        named = dict.fromkeys([str(warned.idxmax()), PERSISTENCE])
        counts = ", ".join(
            f"{model} {warned[model]:.0f} of {total[model]:.0f}"
            for model in named
            if model in warned.index
        )
        lines.append(
            f"First crossings of {flood_cm:g} cm warned at least {WARNED_HOURS} h ahead: {counts}."
        )
    if "false_per_month" in numbers:
        rates = numbers["false_per_month"].dropna()
        span = f"{rates.min():.2f}" + (
            f" to {rates.max():.2f}" if rates.max() > rates.min() else ""
        )
        lines.append(f"False alarms at {flood_cm:g} cm: {span} per month.")
    return lines


def _cell(value: Any) -> str:
    if isinstance(value, float):
        return "-" if pd.isna(value) else f"{value:.2f}"
    return str(value)


def markdown_table(table: pd.DataFrame) -> str:
    """A GitHub Markdown table; the index levels become the first columns."""
    frame = table.reset_index()
    if "threshold_cm" in frame:
        frame["threshold_cm"] = [f"{threshold:g}" for threshold in frame["threshold_cm"]]
    header = "| " + " | ".join(str(column) for column in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    body = [
        "| " + " | ".join(_cell(value) for value in row) + " |" for row in frame.itertuples(False)
    ]
    return "\n".join([header, rule, *body])

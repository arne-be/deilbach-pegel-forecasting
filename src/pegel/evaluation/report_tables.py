"""The tables and the summary of the run report, from the files `score` wrote.

No matplotlib here, so the tables stay usable and testable without the plots.
"""

from collections.abc import Sequence
from typing import Any

import pandas as pd

from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL, SUBSET_HIGH_WATER

TABLE_LEADS = (1, 3, 6, 12, 24)
LAG_LEADS = (6, 12)


def model_order(models: Sequence[str]) -> list[str]:
    """Persistence first, the rest by name, so tables and colours stay in one order."""
    unique = set(models)
    return [PERSISTENCE] * (PERSISTENCE in unique) + sorted(unique - {PERSISTENCE})


def lead_table(scores: pd.DataFrame, subset: str) -> pd.DataFrame:
    """MAE at a few leads, mean MAE and mean skill over all leads, per model, pooled over folds."""
    pooled = scores[(scores["fold"] == ALL_FOLDS) & (scores["subset"] == subset)]
    mae = pooled.pivot(index="model", columns="lead", values="mae")
    table = mae[list(TABLE_LEADS)].rename(columns=lambda lead: f"+{lead} h")
    last_lead = int(mae.columns.max())
    table[f"mean 1-{last_lead} h"] = mae.mean(axis=1)
    table["mean skill"] = pooled.groupby("model")["skill"].mean()
    return table.reindex(model_order(list(table.index)))


def lag_table(lag: pd.DataFrame) -> pd.DataFrame:
    """The lag check's best shift on high water at +6 h and +12 h; equal to the lead means a
    delayed persistence."""
    rows = lag[lag["lead"].isin(LAG_LEADS)]
    table = rows.pivot(index="model", columns="lead", values="shift_hours")
    table = table.rename(columns=lambda lead: f"shift at +{lead} h")
    return table.reindex(model_order(list(table.index)))


def _headline_numbers(scores: pd.DataFrame) -> pd.DataFrame:
    """Per model: mean MAE over all leads on `all` and high water, MAE and skill at high water
    at the last lead."""
    pooled = scores[scores["fold"] == ALL_FOLDS]
    mean_mae = pooled.pivot_table(index="model", columns="subset", values="mae", aggfunc="mean")
    high = pooled[pooled["subset"] == SUBSET_HIGH_WATER]
    last = high[high["lead"] == high["lead"].max()].set_index("model")
    return pd.DataFrame(
        {
            "mae_all": mean_mae.get(SUBSET_ALL),
            "mae_high": mean_mae.get(SUBSET_HIGH_WATER),
            "mae_high_last": last["mae"],
            "skill_high_last": last["skill"],
        },
        index=model_order(list(pooled["model"])),
    )


def _number(value: Any, digits: int) -> str:
    return "-" if pd.isna(value) else f"{value:.{digits}f}"


def headline_table(scores: pd.DataFrame) -> pd.DataFrame:
    """One row per model with the numbers to compare first, already formatted."""
    numbers = _headline_numbers(scores)
    last_lead = int(scores["lead"].max())
    columns: dict[str, list[str]] = {
        "mean MAE all (cm)": [_number(v, 1) for v in numbers["mae_all"]],
        "mean MAE high water (cm)": [_number(v, 1) for v in numbers["mae_high"]],
        f"MAE +{last_lead} h high water (cm)": [_number(v, 1) for v in numbers["mae_high_last"]],
        f"skill +{last_lead} h high water": [_number(v, 2) for v in numbers["skill_high_last"]],
    }
    return pd.DataFrame(columns, index=pd.Index(numbers.index, name="model"))


def summary(scores: pd.DataFrame) -> list[str]:
    """One plain sentence with the facts a reader looks for first."""
    numbers = _headline_numbers(scores)
    last_lead = int(scores["lead"].max())
    if len(numbers) == 1:
        model = numbers.index[0]
        return [
            f"Mean MAE of {model} over leads 1-{last_lead} h: {numbers['mae_all'].iloc[0]:.1f} cm"
            f" over all issue times, {numbers['mae_high'].iloc[0]:.1f} cm at high water."
        ]
    parts = []
    for column, where in (("mae_all", "over all issue times"), ("mae_high", "at high water")):
        values = numbers[column]
        # Every model that prints the same as the best one, so a tie isn't hidden.
        best = values[values.round(1) == round(values.min(), 1)].sort_values().index
        names = " and ".join([", ".join(best[:-1]), best[-1]] if len(best) > 1 else best)
        baseline = values.get(PERSISTENCE)
        versus = "" if pd.isna(baseline) else f"; persistence {baseline:.1f} cm"
        parts.append(f"{names} {where} ({values.min():.1f} cm{versus})")
    return [f"Lowest mean MAE over leads 1-{last_lead} h: {parts[0]}, {parts[1]}."]


def _cell(value: Any) -> str:
    if isinstance(value, float):
        return "-" if pd.isna(value) else f"{value:.2f}"
    return str(value)


def markdown_table(table: pd.DataFrame) -> str:
    """A GitHub Markdown table; the index levels become the first columns."""
    frame = table.reset_index()
    header = "| " + " | ".join(str(column) for column in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    body = [
        "| " + " | ".join(_cell(value) for value in row) + " |" for row in frame.itertuples(False)
    ]
    return "\n".join([header, rule, *body])


def _timing(hours: Any, at_least: bool = False) -> str:
    """Signed hours with a real minus sign; `≥` when the forecast may peak later still."""
    if pd.isna(hours):
        return "—"
    hours = round(hours)
    sign = "+" if hours > 0 else "\N{MINUS SIGN}" if hours < 0 else "±"
    text = f"{sign}{abs(hours)} h"
    return f"≥ {text}" if at_least else text


def _percent(share: Any) -> str:
    return "—" if pd.isna(share) else f"{share * 100:.0f} %"


def _lead_column(lead: int) -> str:
    return f"{lead} h before"


def _summary_cell(rows: pd.DataFrame) -> str:
    """`9 of 13 · 78 % · -1 h`: predicted of events with a forecast, median size of those,
    median timing of the predicted ones."""
    scored = rows.dropna(subset=["size"])
    if scored.empty:
        return "—"
    predicted = scored[scored["predicted"].astype(bool)]
    # shortcut: an "at least" timing counts with its lower bound in the median.
    timing = _timing(predicted["timing_hours"].median())
    return f"{len(predicted)} of {len(scored)} · {_percent(scored['size'].median())} · {timing}"


def flood_summary_table(peaks: pd.DataFrame, false_alarms: pd.DataFrame) -> pd.DataFrame:
    """One row per model, persistence first: a summary cell per lead and false alarms."""
    models = model_order(list(peaks["model"]))
    leads = sorted(peaks["lead_hours"].unique(), reverse=True)
    columns = {
        _lead_column(lead): [
            _summary_cell(peaks[(peaks["model"] == model) & (peaks["lead_hours"] == lead)])
            for model in models
        ]
        for lead in leads
    }
    per_month = (
        false_alarms.set_index("model")["per_month"] if not false_alarms.empty else pd.Series()
    )
    columns["false alarms / month"] = [_number(per_month.get(model), 2) for model in models]
    return pd.DataFrame(columns, index=pd.Index(models, name="model"))


def _grid_cell(row: pd.Series) -> str:
    if pd.isna(row["size"]):
        return "—"
    mark = "✓" if bool(row["predicted"]) else "✗"
    timing = _timing(row["timing_hours"], bool(row["timing_at_least"]))
    return f"{mark} {_percent(row['size'])} {timing}"


def flood_grid_table(peaks: pd.DataFrame, events: pd.DataFrame, model: str) -> pd.DataFrame:
    """One row per event for one model: peak date and height, a `✓ 82 % -2 h` cell per lead."""
    own = peaks[peaks["model"] == model]
    cells = own.assign(cell=own.apply(_grid_cell, axis=1)).pivot(
        index="event", columns="lead_hours", values="cell"
    )
    cells = cells[sorted(cells.columns, reverse=True)].rename(columns=_lead_column)
    info = events.set_index("event")
    table = pd.DataFrame(
        {
            "peak (UTC)": pd.to_datetime(info["peak_at"]).dt.strftime("%Y-%m-%d"),
            "peak cm": info["peak_cm"].map(lambda cm: f"{cm:.0f}"),
        }
    )
    return table.join(cells, how="inner")


def _predicted_counts(peaks: pd.DataFrame, lead: int) -> pd.Series:
    """Per model: (predicted, events with a forecast) at one lead."""
    rows = peaks[(peaks["lead_hours"] == lead)].dropna(subset=["size"])
    grouped = rows.groupby("model")["predicted"]
    return pd.Series(
        {model: (int(values.astype(bool).sum()), len(values)) for model, values in grouped}
    )


def flood_summary(peaks: pd.DataFrame, leads: Sequence[int] = (6, 24)) -> list[str]:
    """One line: events predicted at `leads` by the best model and by persistence."""
    counts = {lead: _predicted_counts(peaks, lead) for lead in leads}
    models = list(counts[leads[0]].index)
    if not models:
        return []
    rank = {model: tuple(counts[lead].get(model, (0, 0))[0] for lead in leads) for model in models}
    best_rank = max(rank.values())
    best = [model for model in model_order(models) if rank[model] == best_rank]

    def at_leads(model: str) -> str:
        parts = []
        for lead in leads:
            predicted, total = counts[lead].get(model, (0, 0))
            parts.append(f"{predicted} of {total} at {lead} h")
        return ", ".join(parts)

    line = f"Events predicted: {' and '.join(best)} {at_leads(best[0])}"
    if PERSISTENCE in models and PERSISTENCE not in best:
        line += f"; persistence {at_leads(PERSISTENCE)}"
    return [line + "."]

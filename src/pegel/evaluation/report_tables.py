"""The tables and the summary of the run report, from the files `score` wrote.

No matplotlib here, so the tables stay usable and testable without the plots.
"""

from collections.abc import Sequence
from typing import Any

import pandas as pd

from pegel.evaluation import contract
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


def observed_from_predictions(predictions: pd.DataFrame) -> pd.Series:
    """The observed cleaned level by target time, from the targets in the predictions."""
    known = predictions.dropna(subset=["target"])
    at = known[contract.ISSUED_AT] + known["lead"] * pd.Timedelta(hours=1)
    return known["target"].groupby(at).first().sort_index()


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

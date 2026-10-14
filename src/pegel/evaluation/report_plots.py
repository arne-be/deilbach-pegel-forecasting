"""The plots of the run report: MAE and skill per lead, MAE per fold, and one plot per flood.

Analysis only: matplotlib is in the `analysis` group, not in the Lambda image.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from pegel.evaluation import contract
from pegel.evaluation.events import forecast_levels
from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL
from pegel.evaluation.report import model_order

PERSISTENCE_COLOUR = "#808080"
# tab10 without its grey, which is reserved for persistence.
MODEL_COLOURS = [c for i, c in enumerate(plt.get_cmap("tab10").colors) if i != 7]  # type: ignore[attr-defined]
EVENT_LEADS = {6: "-", 12: "--"}
EVENT_MARGIN = pd.Timedelta(hours=24)
DPI = 100


def colours(models: list[str]) -> dict[str, str | tuple[float, float, float]]:
    others = [model for model in model_order(models) if model != PERSISTENCE]
    palette: dict[str, str | tuple[float, float, float]] = {PERSISTENCE: PERSISTENCE_COLOUR}
    palette.update({model: MODEL_COLOURS[i % len(MODEL_COLOURS)] for i, model in enumerate(others)})
    return palette


def _save(figure: Figure, path: Path) -> Path:
    figure.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(figure)
    return path


def _lead_axes(axes: Axes, ylabel: str, title: str) -> None:
    axes.set_xlabel("hours ahead")
    axes.set_ylabel(ylabel)
    axes.set_title(title)
    axes.set_xlim(left=0)
    axes.grid(alpha=0.3)


def _by_lead(scores: pd.DataFrame, fold: str, subset: str) -> pd.DataFrame:
    rows = scores[(scores["fold"] == fold) & (scores["subset"] == subset)]
    return rows.pivot(index="lead", columns="model", values=["mae", "skill"])


def mae_plot(scores: pd.DataFrame, bootstrap: pd.DataFrame, path: Path) -> Path:
    """MAE per lead for each subset, pooled over folds, with the bootstrap band on `all`."""
    subsets = list(scores["subset"].unique())
    palette = colours(list(scores["model"]))
    figure, axes = plt.subplots(1, len(subsets), figsize=(5 * len(subsets), 4), squeeze=False)
    for ax, subset in zip(axes[0], subsets, strict=True):
        mae = _by_lead(scores, ALL_FOLDS, subset)["mae"]
        for model in model_order(list(mae.columns)):
            ax.plot(mae.index, mae[model], color=palette[model], label=model)
            band = bootstrap[bootstrap["model"] == model] if not bootstrap.empty else bootstrap
            if subset == SUBSET_ALL and not band.empty:
                # The interval of the gain over persistence, placed around the model's MAE.
                band = band.set_index("lead").reindex(mae.index)
                base = mae[model] - band["mae_difference"]
                ax.fill_between(
                    mae.index,
                    base + band["low"],
                    base + band["high"],
                    color=palette[model],
                    alpha=0.2,
                )
        _lead_axes(ax, "MAE (cm)", subset)
        ax.set_ylim(bottom=0)
    axes[0][0].legend()
    return _save(figure, path)


def skill_plot(scores: pd.DataFrame, path: Path) -> Path:
    """Skill per lead against persistence, one panel per subset."""
    subsets = list(scores["subset"].unique())
    palette = colours(list(scores["model"]))
    figure, axes = plt.subplots(1, len(subsets), figsize=(5 * len(subsets), 4), squeeze=False)
    for ax, subset in zip(axes[0], subsets, strict=True):
        skill = _by_lead(scores, ALL_FOLDS, subset)["skill"]
        for model in model_order(list(skill.columns)):
            ax.plot(skill.index, skill[model], color=palette[model], label=model)
        _lead_axes(ax, "skill vs persistence (1 - MAE / MAE persistence)", subset)
    axes[0][0].legend()
    return _save(figure, path)


def fold_plot(scores: pd.DataFrame, path: Path) -> Path:
    """MAE per lead per fold, a row per subset, a column per fold."""
    subsets = list(scores["subset"].unique())
    folds = sorted(set(scores["fold"]) - {ALL_FOLDS})
    palette = colours(list(scores["model"]))
    figure, axes = plt.subplots(
        len(subsets),
        len(folds),
        figsize=(3.2 * len(folds), 2.8 * len(subsets)),
        squeeze=False,
        sharex=True,
        sharey="row",
    )
    for row, subset in enumerate(subsets):
        for column, fold in enumerate(folds):
            ax = axes[row][column]
            # A fold without high water has no rows for that subset.
            if ((scores["fold"] == fold) & (scores["subset"] == subset)).any():
                mae = _by_lead(scores, fold, subset)["mae"]
                for model in model_order(list(mae.columns)):
                    ax.plot(mae.index, mae[model], color=palette[model], label=model)
            _lead_axes(ax, f"MAE (cm), {subset}" if column == 0 else "", fold if row == 0 else "")
            if row < len(subsets) - 1:
                ax.set_xlabel("")
    # After plotting: on shared axes an earlier set_ylim would freeze the top too.
    for ax in axes.flat:
        ax.set_ylim(bottom=0)
    axes[0][0].legend(fontsize="small")
    return _save(figure, path)


def observed_from_predictions(predictions: pd.DataFrame) -> pd.Series:
    """The observed cleaned level by target time, from the targets in the predictions."""
    known = predictions.dropna(subset=["target"])
    at = known[contract.ISSUED_AT] + known["lead"] * pd.Timedelta(hours=1)
    return known["target"].groupby(at).first().sort_index()


def event_plot(
    predictions: pd.DataFrame,
    observed: pd.Series,
    event: pd.Series,
    thresholds: list[float],
    path: Path,
) -> Path:
    """Observed level around one flood and each model's lead-6 and lead-12 forecasts."""
    start = pd.Timestamp(event["start"]) - EVENT_MARGIN
    end = pd.Timestamp(event["end"]) + EVENT_MARGIN
    palette = colours(list(predictions["model"]))
    figure, ax = plt.subplots(figsize=(9, 4))
    ax.plot(observed[start:end], color="black", linewidth=2, label="observed")
    for model in model_order(list(predictions["model"])):
        for lead, style in EVENT_LEADS.items():
            forecast = forecast_levels(predictions, model, lead)[start:end]
            ax.plot(forecast, color=palette[model], linestyle=style, label=f"{model} +{lead} h")
    for threshold in thresholds:
        ax.axhline(threshold, color="tab:red", linewidth=0.8, linestyle=":")
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("level (cm)")
    ax.set_title(f"Flood peaking {pd.Timestamp(event['peak_at']):%Y-%m-%d %H:%M} UTC")
    ax.grid(alpha=0.3)
    ax.legend(fontsize="small")
    figure.autofmt_xdate()
    return _save(figure, path)


def write_plots(
    predictions: pd.DataFrame, tables: dict[str, pd.DataFrame], plot_dir: Path
) -> list[Path]:
    """Every plot the tables allow; a missing or empty table only skips its plots."""
    plot_dir.mkdir(parents=True, exist_ok=True)
    scores, events, alarms = tables["scores"], tables["events"], tables["alarms"]
    plots: list[Path] = []
    if not scores.empty:
        plots.append(mae_plot(scores, tables["bootstrap"], plot_dir / "mae.png"))
        plots.append(skill_plot(scores, plot_dir / "skill.png"))
        plots.append(fold_plot(scores, plot_dir / "mae-folds.png"))
    if events.empty:
        return plots
    thresholds = sorted(alarms["threshold_cm"].unique()) if not alarms.empty else []
    observed = observed_from_predictions(predictions)
    for number, event in enumerate(events.to_dict("records"), start=1):
        name = f"event-{number}-{pd.Timestamp(event['peak_at']):%Y-%m-%d}.png"
        plots.append(
            event_plot(predictions, observed, pd.Series(event), thresholds, plot_dir / name)
        )
    return plots

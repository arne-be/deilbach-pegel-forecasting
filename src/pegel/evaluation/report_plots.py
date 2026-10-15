"""The plots of the run report: MAE and skill per lead, MAE per fold, and one plot per flood.

Analysis only: matplotlib is in the `analysis` group, not in the Lambda image.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from pegel.evaluation.events import forecast_levels
from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL
from pegel.evaluation.report_tables import model_order, observed_from_predictions

PERSISTENCE_COLOUR = "#808080"
# tab20 without the greys reserved for persistence: 9 dark and 9 light shades.
_TAB20 = [c for i, c in enumerate(plt.get_cmap("tab20").colors) if i not in (14, 15)]  # type: ignore[attr-defined]
MODEL_COLOURS = _TAB20[0::2] + _TAB20[1::2]
EVENT_LEADS = {6: "-", 12: "--"}
EVENT_MARGIN = pd.Timedelta(hours=24)
DPI = 100


Palette = dict[str, str | tuple[float, float, float]]


def colours(models: list[str], registered: list[str]) -> Palette:
    """A colour per model by its place in the registry, so a model keeps its colour across
    runs; models not in the registry come after the registered ones. Beyond 9 models the
    oldest get the light shades, so the newest models are never the faintest lines."""
    unregistered = sorted(set(models) - set(registered))
    others = [model for model in [*registered, *unregistered] if model != PERSISTENCE]
    dark, light = MODEL_COLOURS[:9], MODEL_COLOURS[9:]
    order = light[: max(0, len(others) - len(dark))] + dark + light
    palette: Palette = {PERSISTENCE: PERSISTENCE_COLOUR}
    palette.update({model: order[i % len(order)] for i, model in enumerate(others)})
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


def mae_plot(scores: pd.DataFrame, bootstrap: pd.DataFrame, palette: Palette, path: Path) -> Path:
    """MAE per lead for each subset, pooled over folds, with the bootstrap band on `all`."""
    subsets = list(scores["subset"].unique())
    figure, axes = plt.subplots(1, len(subsets), figsize=(5 * len(subsets), 4), squeeze=False)
    for ax, subset in zip(axes[0], subsets, strict=True):
        mae = _by_lead(scores, ALL_FOLDS, subset)["mae"]
        for model in model_order(list(mae.columns)):
            ax.plot(mae.index, mae[model], color=palette[model], label=model)
            band = bootstrap[bootstrap["model"] == model] if not bootstrap.empty else bootstrap
            if subset == SUBSET_ALL and not band.empty:
                # A band clear of the grey line means a gain significant at 90 %.
                band = band.set_index("lead").reindex(mae.index)
                ax.fill_between(
                    mae.index,
                    mae[PERSISTENCE] + band["low"],
                    mae[PERSISTENCE] + band["high"],
                    color=palette[model],
                    alpha=0.2,
                )
        _lead_axes(ax, "MAE (cm)", subset)
        ax.set_ylim(bottom=0)
    _legend_below(figure, axes[0][0])
    return _save(figure, path)


def skill_plot(scores: pd.DataFrame, palette: Palette, path: Path) -> Path:
    """Skill per lead against persistence, one panel per subset."""
    subsets = list(scores["subset"].unique())
    figure, axes = plt.subplots(1, len(subsets), figsize=(5 * len(subsets), 4), squeeze=False)
    for ax, subset in zip(axes[0], subsets, strict=True):
        skill = _by_lead(scores, ALL_FOLDS, subset)["skill"]
        for model in model_order(list(skill.columns)):
            ax.plot(skill.index, skill[model], color=palette[model], label=model)
        _lead_axes(ax, "skill" if ax is axes[0][0] else "", subset)
    _legend_below(figure, axes[0][0])
    return _save(figure, path)


def _legend_below(figure: Figure, axes: Axes) -> None:
    handles = axes.get_legend_handles_labels()
    figure.legend(*handles, loc="upper center", ncols=4, bbox_to_anchor=(0.5, 0), fontsize="small")


def fold_plot(scores: pd.DataFrame, palette: Palette, path: Path) -> Path:
    """MAE per lead per fold, a row per subset, a column per fold."""
    subsets = list(scores["subset"].unique())
    folds = sorted(set(scores["fold"]) - {ALL_FOLDS})
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
    _legend_below(figure, axes[0][0])
    return _save(figure, path)


def event_plot(
    predictions: pd.DataFrame,
    observed: pd.Series,
    event: pd.Series,
    palette: Palette,
    path: Path,
) -> Path:
    """Observed level around one flood and each model's lead-6 and lead-12 forecasts."""
    start = pd.Timestamp(event["start"]) - EVENT_MARGIN
    end = pd.Timestamp(event["end"]) + EVENT_MARGIN
    figure, ax = plt.subplots(figsize=(9, 4))
    ax.plot(observed[start:end], color="black", linewidth=2, label="observed")
    for model in model_order(list(predictions["model"])):
        for lead, style in EVENT_LEADS.items():
            forecast = forecast_levels(predictions, model, lead)[start:end]
            ax.plot(forecast, color=palette[model], linestyle=style, label=f"{model} +{lead} h")
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("level (cm)")
    ax.set_title(f"Flood peaking {pd.Timestamp(event['peak_at']):%Y-%m-%d %H:%M} UTC")
    ax.grid(alpha=0.3)
    ax.legend(fontsize="small")
    figure.autofmt_xdate()
    return _save(figure, path)


def write_plots(
    predictions: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    registered: list[str],
    plot_dir: Path,
) -> list[Path]:
    """Every plot the tables allow; a missing or empty table only skips its plots."""
    plot_dir.mkdir(parents=True, exist_ok=True)
    scores, events = tables["scores"], tables["events"]
    palette = colours(list(predictions["model"]), registered)
    plots: list[Path] = []
    if not scores.empty:
        plots.append(mae_plot(scores, tables["bootstrap"], palette, plot_dir / "mae.png"))
        # Skill is 0 by definition for persistence, so a run of it alone has nothing to show.
        if set(scores["model"]) != {PERSISTENCE}:
            plots.append(skill_plot(scores, palette, plot_dir / "skill.png"))
    if not scores.empty:
        plots.append(fold_plot(scores, palette, plot_dir / "mae-folds.png"))
    if events.empty:
        return plots
    observed = observed_from_predictions(predictions)
    for number, event in enumerate(events.to_dict("records"), start=1):
        name = f"event-{number}-{pd.Timestamp(event['peak_at']):%Y-%m-%d}.png"
        plots.append(event_plot(predictions, observed, pd.Series(event), palette, plot_dir / name))
    return plots

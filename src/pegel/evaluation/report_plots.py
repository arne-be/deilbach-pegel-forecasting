"""The plots of the run report: MAE and skill per lead, MAE per fold, and a peak track per flood.

Analysis only: matplotlib is in the `analysis` group, not in the Lambda image.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from pegel.evaluation import contract
from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL
from pegel.evaluation.report_tables import model_order

PERSISTENCE_COLOUR = "#808080"
# tab20 without the greys reserved for persistence: 9 dark and 9 light shades.
_TAB20 = [c for i, c in enumerate(plt.get_cmap("tab20").colors) if i not in (14, 15)]  # type: ignore[attr-defined]
MODEL_COLOURS = _TAB20[0::2] + _TAB20[1::2]
# The peak track shows the issue times from this many hours before the observed peak to it.
TRACK_HOURS = 24
_HOUR = pd.Timedelta(hours=1)
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


def forecast_peaks(predictions: pd.DataFrame, peak_at: pd.Timestamp) -> pd.DataFrame:
    """Per model and issue time from TRACK_HOURS before `peak_at` to it: the forecast's highest
    value and its time, both relative to the observed peak (hours, first of tied hours)."""
    issued = predictions[contract.ISSUED_AT]
    window = predictions[(issued >= peak_at - TRACK_HOURS * _HOUR) & (issued <= peak_at)]
    # Only complete forecasts, as in flood_scores: a missing hour could hide the peak.
    complete = window.groupby(["model", contract.ISSUED_AT])["prediction"].transform(
        lambda values: values.notna().all()
    )
    window = window[complete.astype(bool)]
    highest = window.loc[window.groupby(["model", contract.ISSUED_AT])["prediction"].idxmax()]
    issued_at = highest[contract.ISSUED_AT]
    return pd.DataFrame(
        {
            "model": highest["model"],
            "issued_hours": (issued_at - peak_at) / _HOUR,
            "peak_cm": highest["prediction"],
            "timing_hours": (issued_at - peak_at) / _HOUR + highest["lead"],
        }
    )


def peak_track_plot(
    predictions: pd.DataFrame,
    event: pd.Series,
    high_water_cm: float,
    palette: Palette,
    path: Path,
) -> Path:
    """Each model's forecast peak height (top) and time (bottom) against its issue time, over
    the TRACK_HOURS before the observed peak: when a model saw the flood and if it held on."""
    peak_at = pd.Timestamp(event["peak_at"])
    tracks = forecast_peaks(predictions, peak_at)
    figure, (height, timing) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    references = (
        (event["peak_cm"], "black", "-", "observed peak"),
        (event["pre_event_cm"], "black", ":", "pre-event level"),
        (high_water_cm, "#b22222", "--", f"{high_water_cm:.0f} cm"),
    )
    for level, colour, style, label in references:
        height.axhline(level, color=colour, linestyle=style, linewidth=1.2)
        height.annotate(
            label, (0, level), xytext=(4, 2), textcoords="offset points", fontsize="small"
        )
    timing.axhline(0, color="black", linewidth=1.2)
    for model in model_order(list(tracks["model"])):
        track = tracks[tracks["model"] == model]
        for ax, column in ((height, "peak_cm"), (timing, "timing_hours")):
            ax.plot(track["issued_hours"], track[column], color=palette[model], label=model)
    height.set_ylabel("forecast peak (cm)")
    height.set_title(
        f"Event {event['event']}: peak {event['peak_cm']:.0f} cm at {peak_at:%Y-%m-%d %H:%M} UTC"
    )
    timing.set_ylabel("forecast peak time (h after observed peak)")
    timing.set_xlabel("issue time (h relative to the observed peak)")
    timing.set_xlim(-TRACK_HOURS, 0)
    for ax in (height, timing):
        ax.grid(alpha=0.3)
    _legend_below(figure, timing)
    return _save(figure, path)


def write_plots(
    predictions: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    registered: list[str],
    high_water_cm: float,
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
    for event in events.to_dict("records"):
        name = f"peak-track-{event['event']}-{pd.Timestamp(event['peak_at']):%Y-%m-%d}.png"
        plots.append(
            peak_track_plot(predictions, pd.Series(event), high_water_cm, palette, plot_dir / name)
        )
    return plots

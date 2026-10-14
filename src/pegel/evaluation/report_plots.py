"""The plots of the run report: MAE and skill per lead, warnings and false alarms, MAE per
fold, and one plot per flood.

Analysis only: matplotlib is in the `analysis` group, not in the Lambda image.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from pegel.evaluation.events import forecast_levels
from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL
from pegel.evaluation.report_tables import (
    EARLY_HOURS,
    WARNED_HOURS,
    first_crossings,
    model_order,
    observed_from_predictions,
)

PERSISTENCE_COLOUR = "#808080"
# tab10 without its grey, which is reserved for persistence.
MODEL_COLOURS = [c for i, c in enumerate(plt.get_cmap("tab10").colors) if i != 7]  # type: ignore[attr-defined]
EVENT_LEADS = {6: "-", 12: "--"}
EVENT_MARGIN = pd.Timedelta(hours=24)
WARNING_COLUMNS = 4
DPI = 100


Palette = dict[str, str | tuple[float, float, float]]


def colours(models: list[str], registered: list[str]) -> Palette:
    """A colour per model by its place in the registry, so a model keeps its colour across
    runs; models not in the registry come after the registered ones."""
    unregistered = sorted(set(models) - set(registered))
    others = [model for model in [*registered, *unregistered] if model != PERSISTENCE]
    palette: Palette = {PERSISTENCE: PERSISTENCE_COLOUR}
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
    axes[0][0].legend()
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
    axes[0][0].legend()
    return _save(figure, path)


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
    axes[0][0].legend(fontsize="small")
    return _save(figure, path)


def event_plot(
    predictions: pd.DataFrame,
    observed: pd.Series,
    event: pd.Series,
    thresholds: list[float],
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
    for threshold in thresholds:
        ax.axhline(threshold, color="tab:red", linewidth=0.8, linestyle=":")
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("level (cm)")
    ax.set_title(f"Flood peaking {pd.Timestamp(event['peak_at']):%Y-%m-%d %H:%M} UTC")
    ax.grid(alpha=0.3)
    ax.legend(fontsize="small")
    figure.autofmt_xdate()
    return _save(figure, path)


def _model_rows(ax: Axes, models: list[str], labels: bool) -> None:
    """Models as rows from the top, with a faint line per row to follow."""
    ax.set_yticks(range(len(models)), models if labels else [])
    ax.set_ylim(len(models) - 0.5, -0.5)
    ax.grid(axis="y", alpha=0.3)


def _panel_places(panels: pd.DataFrame) -> tuple[list[tuple[int, int]], int]:
    """Grid places for the panels, each threshold starting a new row, and the row count."""
    places: list[tuple[int, int]] = []
    rows = 0
    for _, group in panels.groupby("threshold_cm"):
        places += [(rows + i // WARNING_COLUMNS, i % WARNING_COLUMNS) for i in range(len(group))]
        rows += -(-len(group) // WARNING_COLUMNS)
    return places, rows


def warning_plot(crossings: pd.DataFrame, palette: Palette, path: Path, note: str = "") -> Path:
    """A small panel per first crossing, grouped by threshold: a dot per model at its first
    warning, in hours before the crossing. No dot is a miss."""
    crossings = crossings.assign(crossing_at=pd.to_datetime(crossings["crossing_at"], utc=True))
    panels = (
        crossings[["threshold_cm", "crossing_at"]]
        .drop_duplicates()
        .sort_values(["threshold_cm", "crossing_at"])
    )
    places, rows = _panel_places(panels)
    models = model_order(list(crossings["model"]))
    longest = crossings["warning_hours"].max()
    earliest = max(24.0, 0.0 if pd.isna(longest) else float(longest)) + 1
    figure, axes = plt.subplots(
        rows,
        WARNING_COLUMNS,
        figsize=(3.2 * WARNING_COLUMNS, rows * (1.0 + 0.25 * len(models))),
        squeeze=False,
    )
    for ax in axes.flat:
        ax.set_visible(False)
    for (threshold, at), (row, column) in zip(panels.itertuples(index=False), places, strict=True):
        ax = axes[row][column]
        ax.set_visible(True)
        ax.axvspan(-WARNED_HOURS, 0.5, color="tab:red", alpha=0.12, linewidth=0)
        ax.axvspan(-earliest, -EARLY_HOURS, color="tab:green", alpha=0.10, linewidth=0)
        same = (crossings["threshold_cm"] == threshold) & (crossings["crossing_at"] == at)
        hours = crossings[same].set_index("model")["warning_hours"]
        for y, model in enumerate(models):
            if pd.notna(hours.get(model)):
                ax.plot(-hours[model], y, "o", color=palette[model], markersize=7)
        _model_rows(ax, models, labels=column == 0)
        ax.set_xlim(-earliest, 0.5)
        ax.set_title(f"{threshold:g} cm, {at:%Y-%m-%d %H:%M} UTC", fontsize="small")
        ax.tick_params(labelsize="small")
        ax.set_xlabel("hours before the crossing", fontsize="small")
    zones = [
        Patch(color="tab:red", alpha=0.25, label=f"< {WARNED_HOURS} h: too late to act"),
        Patch(color="tab:green", alpha=0.2, label=f">= {EARLY_HOURS} h ahead"),
    ]
    title = "First warning before each first crossing (no dot: missed)"
    figure.suptitle(f"{title}\n{note}" if note else title)
    figure.tight_layout()
    figure.legend(handles=zones, loc="upper center", ncols=2, bbox_to_anchor=(0.5, 0.0))
    return _save(figure, path)


def false_alarm_plot(false_alarms: pd.DataFrame, palette: Palette, path: Path) -> Path | None:
    """False alarms per month per model, a panel per threshold that has any; None if none."""
    counted = false_alarms.groupby("threshold_cm")["count"].sum()
    thresholds = list(counted[counted > 0].index)
    if not thresholds:
        return None
    models = model_order(list(false_alarms["model"]))
    figure, axes = plt.subplots(
        1,
        len(thresholds),
        figsize=(3.2 * len(thresholds) + 1, 1.2 + 0.3 * len(models)),
        squeeze=False,
        sharex=True,
    )
    for column, (ax, threshold) in enumerate(zip(axes[0], thresholds, strict=True)):
        rows = false_alarms[false_alarms["threshold_cm"] == threshold].set_index("model")
        rates, counts = rows["per_month"].reindex(models), rows["count"].reindex(models)
        ax.barh(range(len(models)), rates.fillna(0), color=[palette[model] for model in models])
        for y, (rate, count) in enumerate(zip(rates, counts, strict=True)):
            if pd.notna(count):
                ax.text(rate, y, f" {count:.0f}", va="center", fontsize="small")
        _model_rows(ax, models, labels=column == 0)
        ax.grid(axis="x", alpha=0.3)
        ax.set_title(f"{threshold:g} cm", fontsize="small")
        ax.set_xlabel("false alarms per month", fontsize="small")
    # Room for the count right of the longest bar.
    axes[0][0].set_xlim(right=1.15 * float(false_alarms["per_month"].max()))
    figure.suptitle("False alarms per month (count at the bar end)")
    figure.tight_layout()
    return _save(figure, path)


def write_plots(
    predictions: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
    registered: list[str],
    plot_dir: Path,
) -> list[Path]:
    """Every plot the tables allow; a missing or empty table only skips its plots."""
    plot_dir.mkdir(parents=True, exist_ok=True)
    scores, events, alarms = tables["scores"], tables["events"], tables["alarms"]
    palette = colours(list(predictions["model"]), registered)
    plots: list[Path] = []
    if not scores.empty:
        plots.append(mae_plot(scores, tables["bootstrap"], palette, plot_dir / "mae.png"))
        # Skill is 0 by definition for persistence, so a run of it alone has nothing to show.
        if set(scores["model"]) != {PERSISTENCE}:
            plots.append(skill_plot(scores, palette, plot_dir / "skill.png"))
    crossings = first_crossings(tables)
    if not crossings.empty:
        note = "" if not tables["crossings"].empty else "old rule: warnings.csv, no crossings.csv"
        plots.append(warning_plot(crossings, palette, plot_dir / "warnings.png", note))
    if not tables["false_alarms"].empty:
        path = false_alarm_plot(tables["false_alarms"], palette, plot_dir / "false_alarms.png")
        plots += [path] if path else []
    if not scores.empty:
        plots.append(fold_plot(scores, palette, plot_dir / "mae-folds.png"))
    if events.empty:
        return plots
    thresholds = sorted(alarms["threshold_cm"].unique()) if not alarms.empty else []
    observed = observed_from_predictions(predictions)
    for number, event in enumerate(events.to_dict("records"), start=1):
        name = f"event-{number}-{pd.Timestamp(event['peak_at']):%Y-%m-%d}.png"
        plots.append(
            event_plot(
                predictions, observed, pd.Series(event), thresholds, palette, plot_dir / name
            )
        )
    return plots

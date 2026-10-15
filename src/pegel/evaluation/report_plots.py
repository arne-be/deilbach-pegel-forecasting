"""The plots of the run report, each answering one question with the answer in its title.

1. `error.png`: how fast does the forecast get worse with the hours ahead?
2. `floods-seen.png`: does it see the floods coming, and how early?
3. `flood-size.png`: how much of each flood's rise did it see, half a day ahead?

They show persistence and the best few models by the selection rule; the tables show all.
Analysis only: matplotlib is in the `analysis` group, not in the Lambda image.
"""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE, SUBSET_ALL, SUBSET_HIGH_WATER
from pegel.evaluation.report_tables import plotted_models

PERSISTENCE_COLOUR = "#808080"
# The first three slots of the dataviz reference palette: they stay apart for colour-blind
# readers in every pair. A colour goes by rank in the run, so it can differ between runs.
MODEL_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a")
MARKERS = ("o", "s", "^", "D")
# The flood-size plot shows the forecasts issued about this many hours before the peak.
SIZE_LEAD = 12
DPI = 100

Palette = dict[str, str]


def colours(models: list[str]) -> Palette:
    """Persistence grey, the others a colour each in the order given (best first)."""
    others = [model for model in models if model != PERSISTENCE]
    return {PERSISTENCE: PERSISTENCE_COLOUR, **dict(zip(others, MODEL_COLOURS, strict=False))}


def _save(figure: Figure, path: Path) -> Path:
    figure.savefig(path, dpi=DPI, facecolor="white")
    plt.close(figure)
    return path


def _figure(title: str, rows: int = 1, columns: int = 1, **options: Any) -> tuple[Figure, Any]:
    """A figure with the takeaway as its title; constrained layout keeps the title, the
    legend and the axes apart."""
    figure, axes = plt.subplots(rows, columns, layout="constrained", **options)
    figure.suptitle(title)
    return figure, axes


def _legend_below(figure: Figure) -> None:
    handles, labels = figure.axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="outside lower center", ncols=4, frameon=False)


def _style(model: str, models: list[str], palette: Palette) -> dict[str, object]:
    return {
        "color": palette[model],
        "marker": MARKERS[models.index(model) % len(MARKERS)],
        "label": model,
        # The baseline thinner and behind, so the models read as the subject.
        "linewidth": 1.5 if model == PERSISTENCE else 2.2,
        "zorder": 2 if model == PERSISTENCE else 3,
    }


def error_title(pooled: pd.DataFrame, models: list[str]) -> str:
    """`24 h ahead, m is off by 2.9 cm on average (persistence 4.0 cm), at high water ...`."""
    last = int(pooled["lead"].max())
    at_last = (
        pooled[pooled["lead"] == last]
        .pivot(index="model", columns="subset", values="mae")
        .to_dict("index")
    )
    best = models[1] if len(models) > 1 else PERSISTENCE
    every, high = at_last[best][SUBSET_ALL], at_last[best][SUBSET_HIGH_WATER]
    title = f"{last} h ahead, {best} is off by {every:.1f} cm on average"
    if best == PERSISTENCE:
        return f"{title}, at high water by {high:.1f} cm"
    base = at_last[PERSISTENCE]
    return (
        f"{title} (persistence {base[SUBSET_ALL]:.1f} cm),\n"
        f"at high water by {high:.1f} cm (persistence {base[SUBSET_HIGH_WATER]:.1f} cm)"
    )


def error_plot(scores: pd.DataFrame, models: list[str], high_water_cm: float, path: Path) -> Path:
    """Average error per hour ahead, all times and high water side by side on one scale."""
    pooled = scores[(scores["fold"] == ALL_FOLDS) & scores["model"].isin(models)]
    palette = colours(models)
    figure, axes = _figure(error_title(pooled, models), 1, 2, figsize=(10, 4.8), sharey=True)
    panels = (
        (SUBSET_ALL, "All times"),
        (SUBSET_HIGH_WATER, f"High water (above {high_water_cm:.0f} cm)"),
    )
    for ax, (subset, name) in zip(axes, panels, strict=True):
        for model in models:
            line = pooled[(pooled["model"] == model) & (pooled["subset"] == subset)]
            line = line.sort_values("lead")
            ax.plot(line["lead"], line["mae"], markevery=[-1], **_style(model, models, palette))
        ax.set_title(name, fontsize="medium", loc="left")
        ax.set_xlabel("hours ahead")
        ax.set_xlim(0, pooled["lead"].max() + 1)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("average error (cm)")
    axes[0].set_ylim(bottom=0)
    _legend_below(figure)
    return _save(figure, path)


def _seen(peaks: pd.DataFrame) -> pd.DataFrame:
    """Per model and lead: floods seen coming and floods with a forecast."""
    scored = peaks.dropna(subset=["size"])
    grouped = scored.assign(seen=scored["predicted"].astype(bool)).groupby(["model", "lead_hours"])
    return grouped.agg(seen=("seen", "sum"), total=("seen", "size"))


def seen_title(seen: pd.DataFrame, models: list[str]) -> str:
    """`m sees 9 of 13 floods coming 24 h ahead; persistence 5`, for the model that sees most
    at the earliest lead."""
    earliest = seen.index.get_level_values("lead_hours").max()
    at_earliest = seen[seen.index.get_level_values("lead_hours") == earliest]
    first = at_earliest.droplevel("lead_hours").reindex(models).dropna().to_dict("index")
    # max keeps the first of tied models, so the better one by the selection rule.
    best = max(first, key=lambda model: first[model]["seen"])
    title = (
        f"{best} sees {first[best]['seen']:.0f} of {first[best]['total']:.0f} floods coming"
        f" {earliest} h ahead"
    )
    if best == PERSISTENCE or PERSISTENCE not in first:
        return title
    return f"{title}; persistence {first[PERSISTENCE]['seen']:.0f}"


def seen_plot(peaks: pd.DataFrame, models: list[str], path: Path) -> Path:
    """Floods seen coming per lead before the peak, the leads evenly spaced, early on the left."""
    seen = _seen(peaks)
    models = [model for model in models if model in seen.index.get_level_values("model")]
    leads = sorted(seen.index.get_level_values("lead_hours").unique(), reverse=True)
    palette = colours(models)
    figure, ax = _figure(seen_title(seen, models), figsize=(8, 4.8))
    for model in models:
        counts = seen.loc[model].reindex(leads)["seen"]
        ax.plot(range(len(leads)), counts.values, markersize=7, **_style(model, models, palette))
    floods = int(seen["total"].max())
    ax.axhline(floods, color="black", linewidth=0.8, linestyle=":")
    ax.annotate(f"all {floods}", (0, floods), xytext=(2, 3), textcoords="offset points")
    ax.set_xticks(range(len(leads)), [f"{lead} h" for lead in leads])
    ax.set_xlabel("hours before the peak the forecast was made")
    ax.set_ylabel("floods seen coming")
    ax.set_ylim(0, floods + 1)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.grid(alpha=0.3)
    _legend_below(figure)
    return _save(figure, path)


def size_lead(peaks: pd.DataFrame) -> int:
    """SIZE_LEAD, or the scored lead nearest to it."""
    return int(min(peaks["lead_hours"].unique(), key=lambda lead: abs(lead - SIZE_LEAD)))


def size_title(sizes: pd.DataFrame, models: list[str], lead: int) -> str:
    """`12 h before the peak, m saw a median 70 % of the rise; persistence 47 %`."""
    median = sizes.median() * 100
    best = models[1] if len(models) > 1 else PERSISTENCE
    title = f"{lead} h before the peak, {best} saw a median {median[best]:.0f} % of the rise"
    if best == PERSISTENCE:
        return title
    return f"{title}; persistence {median[PERSISTENCE]:.0f} %"


def size_plot(peaks: pd.DataFrame, events: pd.DataFrame, models: list[str], path: Path) -> Path:
    """Per flood, the share of the rise each model's forecast saw at one lead, with the
    50 % bar for "seen coming" and the 100 % line for the right height."""
    lead = size_lead(peaks)
    rows = peaks[peaks["lead_hours"] == lead]
    sizes = rows.pivot(index="event", columns="model", values="size")
    models = [model for model in models if model in sizes.columns]
    events = events.set_index("event").sort_values("peak_at")
    palette = colours(models)
    title = size_title(sizes[models], models, lead)
    figure, ax = _figure(title, figsize=(9, 0.4 * len(events) + 2))
    for row, event in enumerate(events.index):
        for i, model in enumerate(models):
            # A small vertical offset per model, so equal values don't hide each other.
            offset = (i - (len(models) - 1) / 2) * 0.15
            style = _style(model, models, palette)
            style.update(linestyle="none", markersize=7, label=model if row == 0 else None)
            ax.plot(
                sizes.get(model, pd.Series()).get(event, float("nan")) * 100, row + offset, **style
            )
    labels = [
        f"{pd.Timestamp(at):%d %b %Y} · {cm:.0f} cm"
        for at, cm in zip(events["peak_at"], events["peak_cm"], strict=True)
    ]
    ax.set_yticks(range(len(events)), labels)
    ax.set_ylim(len(events) - 0.5, -0.5)
    for share, text in ((50, "half the rise:\nseen coming"), (100, "full rise:\nright height")):
        ax.axvline(share, color="black", linewidth=0.8, linestyle=":" if share == 50 else "-")
        transform = ax.get_xaxis_transform()
        ax.text(share, 1.01, text, transform=transform, ha="center", va="bottom", fontsize="small")
    ax.set_xlabel("share of the rise the forecast saw (%)")
    left = min(0, sizes.min().min() * 100 - 5)
    ax.axvspan(left, 50, color="#f0efec", zorder=0)  # missed: less than half the rise
    ax.set_xlim(left=left)
    ax.grid(axis="x", alpha=0.3)
    _legend_below(figure)
    return _save(figure, path)


def write_plots(
    tables: dict[str, pd.DataFrame], high_water_cm: float, plot_dir: Path
) -> list[Path]:
    """Every plot the tables allow; a missing or empty table only skips its plots."""
    plot_dir.mkdir(parents=True, exist_ok=True)
    scores = tables["scores"]
    if scores.empty:
        return []
    models = plotted_models(scores)
    plots = [error_plot(scores, models, high_water_cm, plot_dir / "error.png")]
    peaks, events = tables["peaks"], tables["events"]
    if peaks.empty or events.empty:
        return plots
    plots.append(seen_plot(peaks, models, plot_dir / "floods-seen.png"))
    plots.append(size_plot(peaks, events, models, plot_dir / "flood-size.png"))
    return plots

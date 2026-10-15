"""Figures and tables for docs/evaluation.md: the fold split and every flood event.

Reads the frozen dataset only, with the same folds, embargo and event rule as the scorer.

    uv run --group analysis python analysis/model-evaluation/methodology_plots.py \
        ~/data/deilbach-pegel/eval/2026-10-14/eval.parquet docs/images/evaluation-methodology
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from pegel.config import load_config
from pegel.evaluation import contract, events
from pegel.evaluation.report_tables import markdown_table

TRAIN, TEST = "#2b6cb0", "#c26a12"
LEVEL, UPSTREAM, RAIN = "#18222d", ("#2f855a", "#805ad5"), "#4a90c2"
HOUR = pd.Timedelta(hours=1)


def split_plot(observed: pd.Series, floods: pd.DataFrame, settings, path: Path) -> None:
    """The cleaned level over the window, with each fold's training, embargo and test span."""
    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(11, 5.5), sharex=True, height_ratios=[3, 2], layout="constrained"
    )
    top.plot(observed.index, observed.to_numpy(), color=LEVEL, linewidth=0.6)
    for fold in contract.FOLDS:
        top.axvspan(
            pd.Timestamp(fold.test_start), pd.Timestamp(fold.test_end), color=TEST, alpha=0.08
        )
    for cm, label in ((settings.high_water_cm, "high water"), (settings.flood_cm, "flood")):
        top.axhline(
            cm, color="#b42343", linewidth=0.8, linestyle="--" if cm == settings.flood_cm else ":"
        )
        top.text(
            1.0,
            cm,
            f" {label} {cm:.0f} cm",
            transform=top.get_yaxis_transform(),
            fontsize=8,
            color="#b42343",
            va="center",
        )
    previous_peak = None
    for number, flood in enumerate(floods.itertuples(), start=1):
        # Shift a label sideways when its peak is close to the previous one.
        close = previous_peak is not None and flood.peak_at - previous_peak < pd.Timedelta(days=5)
        top.annotate(
            str(number),
            (flood.peak_at, flood.peak_cm),
            xytext=(7 if close else 0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=8,
            weight="bold",
        )
        previous_peak = flood.peak_at
    top.set_ylabel("Kupferdreh, cleaned (cm)")
    top.set_title("Cleaned level, test periods shaded, flood events numbered")

    first = pd.Timestamp(settings.window_first_day)
    for row, fold in enumerate(contract.FOLDS):
        test_start = pd.Timestamp(fold.test_start)
        embargo_start = test_start - settings.leads_hours * HOUR
        y = len(contract.FOLDS) - 1 - row
        bottom.barh(y, embargo_start - first, left=first, color=TRAIN, height=0.6)
        bottom.barh(
            y,
            pd.Timestamp(fold.test_end) + pd.Timedelta(days=1) - test_start,
            left=test_start,
            color=TEST,
            height=0.6,
        )
    bottom.set_yticks(range(len(contract.FOLDS)), [fold.name for fold in reversed(contract.FOLDS)])
    bottom.set_title("Folds: training (blue) and test (orange), 24 h dropped between")
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    figure.savefig(path, dpi=120)
    plt.close(figure)


def event_plot(
    number: int, flood, dataset: pd.DataFrame, observed: pd.Series, settings, path: Path
) -> None:
    """One flood: Kupferdreh, the upstream gauges and radar rain in the wettest catchment cell."""
    start, end = flood.start - pd.Timedelta(hours=36), flood.end + pd.Timedelta(hours=48)
    rows = dataset.set_index(contract.ISSUED_AT).loc[start:end]
    figure, (top, bottom) = plt.subplots(
        2, 1, figsize=(9, 5), sharex=True, height_ratios=[3, 1], layout="constrained"
    )
    kupferdreh = observed[start:end]
    top.plot(
        kupferdreh.index,
        kupferdreh.to_numpy(),
        color=LEVEL,
        linewidth=1.6,
        label="Kupferdreh (cleaned)",
    )
    for colour, (prefix, name) in zip(
        UPSTREAM, (("lb", "Langenberg"), ("nh", "Nierenhof")), strict=True
    ):
        top.plot(
            rows.index,
            rows[f"{prefix}_lag_0"],
            color=colour,
            linewidth=1,
            label=f"{name} (upstream)",
        )
    top.axhline(
        settings.high_water_cm,
        color="#b42343",
        linewidth=0.8,
        linestyle=":",
        label="high water 75 cm",
    )
    top.axhline(
        settings.flood_cm, color="#b42343", linewidth=0.8, linestyle="--", label="flood 95 cm"
    )
    top.axvspan(flood.start - HOUR / 2, flood.end + HOUR / 2, color=TEST, alpha=0.12)
    top.set_ylabel("level (cm)")
    top.set_title(
        f"Event {number}: peak {flood.peak_cm:.1f} cm at {flood.peak_at:%d %b %Y %H:%M} UTC"
    )
    top.legend(fontsize=8, loc="upper right")
    bottom.bar(rows.index, rows["radar_catchment_lag_0"], width=1 / 24, color=RAIN)
    bottom.set_ylabel("radar, wettest\ncell (mm/h)")
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    figure.savefig(path, dpi=120)
    plt.close(figure)


def fold_table(dataset: pd.DataFrame, floods: pd.DataFrame, settings) -> pd.DataFrame:
    rows = []
    for fold in contract.FOLDS:
        test = contract.holdout_rows(dataset, fold)
        in_test = floods["peak_at"].between(
            test[contract.ISSUED_AT].min(),
            test[contract.ISSUED_AT].max() + settings.leads_hours * HOUR,
        )
        rows.append(
            {
                "fold": fold.name,
                "test period": f"{fold.test_start} to {fold.test_end}",
                "training issue times": len(contract.train_rows(dataset, fold, settings)),
                "test issue times": len(test),
                "test issue times above 75 cm": int(
                    (test[contract.KD_LAST_CM] > settings.high_water_cm).sum()
                ),
                "flood events": int(in_test.sum()),
            }
        )
    return pd.DataFrame(rows)


def event_table(floods: pd.DataFrame, dataset: pd.DataFrame) -> pd.DataFrame:
    radar = dataset.set_index(contract.ISSUED_AT)["radar_catchment_lag_0"]
    fold_of = {
        fold.name: (
            pd.Timestamp(fold.test_start, tz="UTC"),
            pd.Timestamp(fold.test_end, tz="UTC") + pd.Timedelta(days=1),
        )
        for fold in contract.FOLDS
    }
    rows = []
    for number, flood in enumerate(floods.itertuples(), start=1):
        rows.append(
            {
                "event": number,
                "fold": next(name for name, (a, b) in fold_of.items() if a <= flood.peak_at < b),
                "above 95 cm from (UTC)": f"{flood.start:%Y-%m-%d %H:%M}",
                "to (UTC)": f"{flood.end:%Y-%m-%d %H:%M}",
                "peak (cm)": round(flood.peak_cm, 1),
                "peak at (UTC)": f"{flood.peak_at:%Y-%m-%d %H:%M}",
                "radar, wettest cell, 48 h to peak (mm)": round(
                    radar[flood.peak_at - pd.Timedelta(hours=47) : flood.peak_at].sum(), 1
                ),
            }
        )
    return pd.DataFrame(rows)


def main(dataset_path: Path, out_dir: Path) -> None:
    settings = load_config().evaluation
    dataset = pd.read_parquet(dataset_path)
    observed = events.observed_levels(dataset, settings.leads_hours)
    # The scored events: only those in the test periods, as in score.py.
    test_start = pd.Timestamp(contract.FOLDS[0].test_start, tz="UTC")
    floods = events.episodes(observed[test_start:], settings.flood_cm)
    all_floods = events.episodes(observed, settings.flood_cm)
    out_dir.mkdir(parents=True, exist_ok=True)
    split_plot(observed, floods, settings, out_dir / "split.png")
    for number, flood in enumerate(floods.itertuples(), start=1):
        event_plot(
            number,
            flood,
            dataset,
            observed,
            settings,
            out_dir / f"event-{number}-{flood.peak_at:%Y-%m-%d}.png",
        )
    print(markdown_table(fold_table(dataset, floods, settings).set_index("fold")))
    print()
    print(markdown_table(event_table(floods, dataset).set_index("event")))
    print()
    print("floods in training only:")
    print(markdown_table(all_floods[all_floods["peak_at"] < test_start].set_index("peak_at")))


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]))

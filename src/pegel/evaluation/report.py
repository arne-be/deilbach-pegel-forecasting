"""Plots and one experiment-log section for a scored run (docs/decisions/0008).

    uv run --group analysis python -m pegel.evaluation.report <run dir> [--notes "..."]

Reads the files `predict` and `score` wrote into the run folder, writes the plots to
`analysis/model-evaluation/plots/<run>/` and appends a section to
`analysis/model-evaluation/experiments.md`. Analysis only: needs matplotlib.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from pegel.evaluation import report_tables

REPORT_DIR = Path("analysis/model-evaluation")
CSV_TABLES = (
    "scores",
    "events",
    "peaks",
    "false_alarms",
    "lag",
    "bands",
)
EMPTY = pd.DataFrame()
# One sentence under each plot on how to read it, by file stem.
CAPTIONS = {
    "error": "Each line is a model's average error, from 1 to 24 hours ahead; lower is better."
    " Left all times, right only when the water is high.",
    "floods-seen": "How many of the floods each model saw coming (its forecast showed more than"
    " half the rise), by how long before the peak the forecast was made; higher is better.",
    "flood-size": "One row per flood. A dot is how much of the rise a model's forecast saw:"
    " right of the dotted line counts as seen coming, on the solid line is the right height.",
}
OVERVIEW_PLOTS = ("error",)


def read_csv(path: Path) -> pd.DataFrame:
    """The table, or an empty frame when the file is missing or has no rows."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def details(summary: str, body: Sequence[str]) -> list[str]:
    """A block GitHub shows folded; the blank lines let the Markdown inside it render."""
    inner = "\n".join(body).strip("\n")
    return ["", "<details>", f"<summary>{summary}</summary>", "", inner, "", "</details>"]


def _images(plots: Sequence[Path], stems: Sequence[str]) -> list[str]:
    """The plots with these stems, each with its caption below it."""
    lines: list[str] = []
    for plot in plots:
        if plot.stem in stems:
            lines += ["", f"![{plot.stem}]({plot.as_posix()})", "", CAPTIONS[plot.stem]]
    return lines


def _table_details(summary: str, text: str, table: pd.DataFrame) -> list[str]:
    return details(summary, [text, "", report_tables.markdown_table(table)])


def _flood_lines(tables: dict[str, pd.DataFrame], plots: Sequence[Path], replay: bool) -> list[str]:
    """Summary table, the flood plots, replay pointer, then the per-model grids folded."""
    peaks, events = tables.get("peaks", EMPTY), tables.get("events", EMPTY)
    if peaks.empty or events.empty:
        return []
    false_alarms = tables.get("false_alarms", EMPTY)
    lines = [
        "",
        "### Flood forecasts",
        "",
        "Per lead before the peak: events predicted (forecast saw more than half the rise) of"
        " events with a forecast, median size, median timing of the predicted ones.",
        "",
        report_tables.markdown_table(report_tables.flood_summary_table(peaks, false_alarms)),
    ]
    lines += _images(plots, [stem for stem in CAPTIONS if stem not in OVERVIEW_PLOTS])
    if replay:
        lines += ["", "Forecast replay: `replay.html` in the run folder."]
    for model in report_tables.model_order(list(peaks["model"])):
        grid = report_tables.flood_grid_table(peaks, events, model)
        lines += _table_details(f"Flood events: {model}", "✓ predicted, ✗ not, — missing.", grid)
    return lines


def section(
    run_name: str,
    run_info: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    plots: Sequence[Path],
    notes: str = "",
    replay: bool = False,
) -> str:
    """The Markdown section for one run. `plots` are paths relative to the log file.

    Summary, notes and one headline table first, then the plots; the detail tables folded.
    """
    scores = tables.get("scores", EMPTY)
    lines = [f"## {run_name}", ""]
    if not scores.empty:
        lines += [*report_tables.summary(scores), ""]
    peaks = tables.get("peaks", EMPTY)
    if not peaks.empty:
        lines += [*report_tables.flood_summary(peaks), ""]
    lines.append(f"**Notes:** {notes}")
    if not scores.empty:
        headline = report_tables.headline_table(scores)
        lines += ["", report_tables.markdown_table(headline)]
    if plots:
        lines += [
            "",
            "The plots show persistence (grey) and up to"
            f" {report_tables.PLOTTED_MODELS} models that beat it by the selection rule;"
            " the tables show all models.",
        ]
    lines += _images(plots, OVERVIEW_PLOTS)
    if not scores.empty:
        body: list[str] = []
        for subset in scores["subset"].unique():
            table = report_tables.lead_table(scores, subset)
            body += [f"Subset `{subset}`:", "", report_tables.markdown_table(table), ""]
        lines += details("MAE in cm per lead and subset, pooled over folds", body)
    lag = tables.get("lag", EMPTY)
    if not lag.empty:
        lines += _table_details(
            "Lag check",
            "Shift in hours that best matches the forecast to the observed level on high water.",
            report_tables.lag_table(lag),
        )
    band_scores = tables.get("bands", EMPTY)
    if not band_scores.empty:
        lines += _table_details(
            "Uncertainty bands",
            "Share of observed levels inside each band / its mean width in cm, per situation,"
            " pooled over leads and the folds after the first (each calibrated on the folds"
            " before it). A good band holds its nominal share in every situation.",
            report_tables.band_table(band_scores),
        )
    state = "dirty" if run_info["dirty"] else "clean"
    models = ", ".join(report_tables.model_order(run_info["models"]))
    lines += details(
        "Run: commit and dataset",
        [
            f"- Run: {run_info['created_at'][:10]}, commit `{run_info['git_commit'][:12]}`"
            f" ({state})",
            f"- Dataset sha256: `{run_info['dataset_sha256']}`",
            f"- Models: {models}",
        ],
    )
    lines += _flood_lines(tables, plots, replay)
    return "\n".join(lines) + "\n"


def check_new_run(log: Path, run_name: str) -> None:
    """Append-only: a run that is already in the log is refused, not rewritten."""
    if f"\n## {run_name}\n" in log.read_text():
        raise ValueError(f"{log} already has a section for {run_name}")


def append_section(log: Path, run_name: str, text: str) -> None:
    check_new_run(log, run_name)
    log.write_text(log.read_text().rstrip("\n") + "\n\n" + text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pegel.evaluation.report")
    parser.add_argument("run", type=Path, help="run folder from predict and score")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--notes", default="", help="the Notes line of the section")
    arguments = parser.parse_args(argv)

    # Imported here so the table code stays usable without matplotlib.
    from pegel.evaluation import report_plots

    run: Path = arguments.run
    run_info = json.loads((run / "run.json").read_text())
    tables = {name: read_csv(run / f"{name}.csv") for name in CSV_TABLES}
    log = arguments.report_dir / "experiments.md"
    plot_dir = arguments.report_dir / "plots" / run.name
    check_new_run(log, run.name)
    high_water_cm = float(run_info["settings"]["high_water_cm"])
    plots = report_plots.write_plots(tables, high_water_cm, plot_dir)
    relative = [plot.relative_to(arguments.report_dir) for plot in plots]
    replay = (run / "replay.html").exists()
    text = section(run.name, run_info, tables, relative, arguments.notes, replay)
    append_section(log, run.name, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

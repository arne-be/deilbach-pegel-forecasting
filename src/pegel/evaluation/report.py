"""Plots and one experiment-log section for a scored run (docs/decisions/0008).

    uv run --group analysis python -m pegel.evaluation.report <run dir> [--notes "..."]

Reads the files `predict` and `score` wrote into the run folder, writes the plots to
`analysis/model-evaluation/plots/<run>/` and appends a section to
`analysis/model-evaluation/experiments.md`. Analysis only: needs pyarrow and matplotlib.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from pegel.config import EvaluationSettings
from pegel.evaluation import report_tables
from pegel.evaluation.registry import MODELS

REPORT_DIR = Path("analysis/model-evaluation")
CSV_TABLES = (
    "scores",
    "bootstrap",
    "events",
    "peaks",
    "false_alarms",
    "lag",
)
EMPTY = pd.DataFrame()


def read_csv(path: Path) -> pd.DataFrame:
    """The table, or an empty frame when the file is missing or has no rows."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def registered_models(settings: EvaluationSettings) -> list[str]:
    """Model names in registry order; the registry only grows, so the order is stable."""
    return [factory(settings).name for factory in MODELS]


def details(summary: str, body: Sequence[str]) -> list[str]:
    """A block GitHub shows folded; the blank lines let the Markdown inside it render."""
    inner = "\n".join(body).strip("\n")
    return ["", "<details>", f"<summary>{summary}</summary>", "", inner, "", "</details>"]


def _image(plot: Path) -> str:
    return f"![{plot.stem}]({plot.as_posix()})"


def _table_details(summary: str, text: str, table: pd.DataFrame) -> list[str]:
    return details(summary, [text, "", report_tables.markdown_table(table)])


def _plot_lines(plots: Sequence[Path]) -> list[str]:
    """The overview plots in the open, the event plots folded."""
    events = [plot for plot in plots if plot.stem.startswith("event-")]
    lines = []
    for plot in plots:
        if plot in events:
            continue
        lines += ["", _image(plot)]
    if events:
        summary = f"Flood events: observed level and forecasts ({len(events)} plots)"
        lines += details(summary, [line for plot in events for line in (_image(plot), "")])
    return lines


def section(
    run_name: str,
    run_info: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    plots: Sequence[Path],
    notes: str = "",
) -> str:
    """The Markdown section for one run. `plots` are paths relative to the log file.

    Summary, notes and one headline table first, then the plots; the detail tables folded.
    """
    scores = tables.get("scores", EMPTY)
    lines = [f"## {run_name}", ""]
    if not scores.empty:
        lines += [*report_tables.summary(scores), ""]
    lines.append(f"**Notes:** {notes}")
    if not scores.empty:
        headline = report_tables.headline_table(scores)
        lines += ["", report_tables.markdown_table(headline)]
    lines += _plot_lines(plots)
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
    predictions = pd.read_parquet(run / "predictions.parquet")
    registered = registered_models(EvaluationSettings.model_validate(run_info["settings"]))
    log = arguments.report_dir / "experiments.md"
    plot_dir = arguments.report_dir / "plots" / run.name
    check_new_run(log, run.name)
    plots = report_plots.write_plots(predictions, tables, registered, plot_dir)
    relative = [plot.relative_to(arguments.report_dir) for plot in plots]
    append_section(log, run.name, section(run.name, run_info, tables, relative, arguments.notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

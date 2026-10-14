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

from pegel.evaluation.metrics import ALL_FOLDS, PERSISTENCE

REPORT_DIR = Path("analysis/model-evaluation")
TABLE_LEADS = (1, 3, 6, 12, 24)
ALARM_LEADS = (1, 6, 12, 24)
CSV_TABLES = ("scores", "bootstrap", "events", "peaks", "alarms", "warnings", "lag")


def read_csv(path: Path) -> pd.DataFrame:
    """The table, or an empty frame when the file is missing or has no rows."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


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


def alarm_table(alarms: pd.DataFrame) -> pd.DataFrame:
    """Hits / misses / false alarms per model and threshold at a few leads."""
    rows = alarms[alarms["lead"].isin(ALARM_LEADS)].copy()
    rows["text"] = (
        rows["hits"].astype(str)
        + " / "
        + rows["misses"].astype(str)
        + " / "
        + rows["false_alarms"].astype(str)
    )
    table = rows.pivot(index=["model", "threshold_cm"], columns="lead", values="text")
    table = table.rename(columns=lambda lead: f"+{lead} h")
    order = model_order(list(rows["model"]))
    return table.reindex(sorted(table.index, key=lambda key: (order.index(key[0]), key[1])))


def warning_table(warnings: pd.DataFrame) -> pd.DataFrame:
    """Per model and threshold: observed crossings, how many any forecast showed, and how far
    ahead the first warning came (median and minimum over the warned crossings)."""
    grouped = warnings.groupby(["model", "threshold_cm"])
    table = pd.DataFrame(
        {
            "crossings": grouped.size(),
            "warned": grouped["warning_hours"].count(),
            "median hours ahead": grouped["warning_hours"].median(),
            "min hours ahead": grouped["warning_hours"].min(),
        }
    )
    order = model_order(list(warnings["model"]))
    return table.reindex(sorted(table.index, key=lambda key: (order.index(key[0]), key[1])))


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


def section(
    run_name: str,
    run_info: dict[str, Any],
    tables: dict[str, pd.DataFrame],
    plots: Sequence[Path],
    notes: str = "",
) -> str:
    """The Markdown section for one run. `plots` are paths relative to the log file."""
    commit = run_info["git_commit"]
    state = "dirty" if run_info["dirty"] else "clean"
    lines = [
        f"## {run_name}",
        "",
        f"- Run: {run_info['created_at'][:10]}, commit `{commit[:12]}` ({state})",
        f"- Dataset sha256: `{run_info['dataset_sha256']}`",
        f"- Models: {', '.join(model_order(run_info['models']))}",
        "",
        "### MAE in cm, pooled over folds",
    ]
    scores = tables["scores"]
    for subset in scores["subset"].unique() if not scores.empty else []:
        lines += ["", f"Subset `{subset}`:", "", markdown_table(lead_table(scores, subset))]
    alarms, warnings = tables["alarms"], tables["warnings"]
    if not alarms.empty:
        lines += [
            "",
            "### Alarms",
            "",
            "Flood episodes per threshold: hits / misses / false alarms of the lead-k forecasts.",
            "",
            markdown_table(alarm_table(alarms)),
        ]
    if not warnings.empty:
        lines += [
            "",
            "### Warnings",
            "",
            "Observed crossings and the first forecast that showed them.",
            "",
            markdown_table(warning_table(warnings)),
        ]
    lines += ["", "### Plots", ""]
    lines += [f"![{plot.stem}]({plot.as_posix()})" for plot in plots]
    lines += ["", f"**Notes:** {notes}", ""]
    return "\n".join(lines)


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

    # Imported here so the table code above stays usable without matplotlib.
    from pegel.evaluation import report_plots

    run: Path = arguments.run
    run_info = json.loads((run / "run.json").read_text())
    tables = {name: read_csv(run / f"{name}.csv") for name in CSV_TABLES}
    predictions = pd.read_parquet(run / "predictions.parquet")
    log = arguments.report_dir / "experiments.md"
    plot_dir = arguments.report_dir / "plots" / run.name
    check_new_run(log, run.name)
    plots = report_plots.write_plots(predictions, tables, plot_dir)
    relative = [plot.relative_to(arguments.report_dir) for plot in plots]
    append_section(log, run.name, section(run.name, run_info, tables, relative, arguments.notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

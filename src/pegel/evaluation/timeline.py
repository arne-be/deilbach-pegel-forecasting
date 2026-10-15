"""Builds the lead timeline page of a run: one self-contained HTML file (docs/evaluation.md).

    uv run --group analysis python -m pegel.evaluation.timeline <run dir> <eval.parquet>

Reads `<run dir>/predictions.parquet`, writes `<run dir>/timeline.html`. Two panels over the
whole test period: the observed level and every model's forecast made SHORT_LEAD_HOURS
(top) and LONG_LEAD_HOURS (bottom) earlier, plotted at the target time, with fold boundaries,
flood events and the high water line. Times are epoch milliseconds (UTC) in the data; the page
shows them in Europe/Berlin. Analysis only: reads Parquet (pyarrow, `analysis` group).
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from pegel.config import load_config
from pegel.evaluation import contract, events
from pegel.evaluation.metrics import PERSISTENCE
from pegel.evaluation.replay import milliseconds, replay_events, rounded

TEMPLATE = Path(__file__).with_name("timeline.html")
DATA_MARKER = "/*TIMELINE_DATA*/"
SHORT_LEAD_HOURS = 3
LONG_LEAD_HOURS = 24
LEADS = (SHORT_LEAD_HOURS, LONG_LEAD_HOURS)

_HOUR = pd.Timedelta(hours=1)


def time_grid(predictions: pd.DataFrame) -> pd.DatetimeIndex:
    """Hourly target times from the first short-lead to the last long-lead forecast."""
    issued = predictions[contract.ISSUED_AT]
    return pd.date_range(
        issued.min() + min(LEADS) * _HOUR, issued.max() + max(LEADS) * _HOUR, freq="h"
    )


def timeline_data(
    predictions: pd.DataFrame, dataset: pd.DataFrame, leads: int, high_water_cm: float
) -> dict[str, Any]:
    """Everything the page draws, as plain JSON-ready values, every series on one hourly grid."""
    names = set(predictions["model"])
    models = ([PERSISTENCE] if PERSISTENCE in names else []) + sorted(names - {PERSISTENCE})
    grid = time_grid(predictions)
    observed = events.observed_levels(dataset, leads)
    present = set(predictions["fold"])
    flood = replay_events(observed, high_water_cm)
    return {
        "start": milliseconds(grid[0]),
        "high_water_cm": high_water_cm,
        "leads": list(LEADS),
        "default_model": PERSISTENCE,
        "models": models,
        "observed": rounded(observed.reindex(grid).to_numpy(dtype=float)),
        "forecasts": {
            str(lead): {
                model: rounded(
                    events.forecast_levels(predictions, model, lead)
                    .reindex(grid)
                    .to_numpy(dtype=float)
                )
                for model in models
            }
            for lead in LEADS
        },
        "folds": [
            {"name": fold.name, "start": milliseconds(pd.Timestamp(fold.test_start, tz="UTC"))}
            for fold in contract.FOLDS
            if fold.name in present
        ],
        "events": [
            {
                "number": event["number"],
                "start": milliseconds(event["start"]),
                "end": milliseconds(event["end"]),
                "peak_at": milliseconds(event["peak_at"]),
                "peak_cm": round(float(event["peak_cm"]), 1),
            }
            for event in flood.to_dict("records")
        ],
    }


def render(data: dict[str, Any]) -> str:
    """The template with the data embedded; every `<` escaped so the JSON can't end the script."""
    payload = json.dumps(data, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    return TEMPLATE.read_text().replace(DATA_MARKER, payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pegel.evaluation.timeline")
    parser.add_argument("run", type=Path, help="run folder with predictions.parquet")
    parser.add_argument("dataset", type=Path, help="the eval.parquet the run was made from")
    arguments = parser.parse_args(argv)
    predictions_path = arguments.run / "predictions.parquet"
    for path in (predictions_path, arguments.dataset):
        if not path.is_file():
            parser.error(f"file not found: {path}")
    predictions = pd.read_parquet(predictions_path)
    if predictions.empty:
        parser.error(f"no predictions in {predictions_path}")
    missing = sorted(set(LEADS) - set(predictions["lead"]))
    if missing:
        parser.error(f"no predictions at lead {', '.join(map(str, missing))} h")
    settings = load_config().evaluation
    data = timeline_data(
        predictions,
        pd.read_parquet(arguments.dataset),
        settings.leads_hours,
        settings.high_water_cm,
    )
    out = arguments.run / "timeline.html"
    out.write_text(render(data))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Builds the forecast replay page of a run: one self-contained HTML file (docs/evaluation.md).

    uv run --group analysis python -m pegel.evaluation.replay <run dir> <eval.parquet>

Reads `<run dir>/predictions.parquet`, writes `<run dir>/replay.html`. The page steps through
the issue times of each test-fold flood event and draws every model's 24-hour forecast against
the observed level. Times are epoch milliseconds (UTC) in the data; the page shows them in
Europe/Berlin. Analysis only: reads Parquet (pyarrow, `analysis` group).
"""

import argparse
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pegel.config import load_config
from pegel.evaluation import contract, events
from pegel.evaluation.metrics import PERSISTENCE

TEMPLATE = Path(__file__).with_name("replay.html")
DATA_MARKER = "/*REPLAY_DATA*/"
# Issue times start this long before the peak, but never before the previous event's end.
BEFORE_PEAK_HOURS = 24
# Observed level shown before the first issue time, for context.
HISTORY_HOURS = 24
Y_PADDING_CM = 5

_HOUR = pd.Timedelta(hours=1)


def _in_test_fold(at: pd.Timestamp) -> bool:
    return any(
        pd.Timestamp(fold.test_start, tz="UTC")
        <= at
        < pd.Timestamp(fold.test_end, tz="UTC") + pd.Timedelta(days=1)
        for fold in contract.FOLDS
    )


def replay_events(observed: pd.Series, high_water_cm: float) -> pd.DataFrame:
    """Flood events whose peak is in a test fold, numbered 1.. by peak time, each with the end
    of the event before it (any event, also in training; NaT for the first)."""
    found = events.flood_events(observed, high_water_cm).sort_values("peak_at")
    found["previous_end"] = found["end"].shift()
    found = found[[_in_test_fold(at) for at in found["peak_at"]]].reset_index(drop=True)
    found.insert(0, "number", range(1, len(found) + 1))
    return found


def issue_times(peak_at: pd.Timestamp, end: pd.Timestamp, previous_end: object) -> pd.DatetimeIndex:
    """Hourly issue times from BEFORE_PEAK_HOURS before the peak to the event's end, none
    before the end of the previous event."""
    first = peak_at - BEFORE_PEAK_HOURS * _HOUR
    if isinstance(previous_end, pd.Timestamp):
        first = max(first, previous_end)
    return pd.date_range(first, end, freq="h")


def rounded(values: np.ndarray) -> list[float | None]:
    return [None if np.isnan(value) else round(float(value), 1) for value in values]


def forecast_arrays(
    predictions: pd.DataFrame, models: Sequence[str], issued: pd.DatetimeIndex, leads: int
) -> dict[str, list[list[float | None] | None]]:
    """Per model, one list of `leads` levels per issue time; None where the model has no
    forecast at that issue time."""
    rows = predictions[predictions[contract.ISSUED_AT].isin(issued)]
    wide = (
        rows.set_index(["model", contract.ISSUED_AT, "lead"])["prediction"]
        .unstack("lead")
        .reindex(columns=range(1, leads + 1))
    )
    result: dict[str, list[list[float | None] | None]] = {}
    for model in models:
        per_issue = wide.loc[model] if model in wide.index.get_level_values(0) else wide.iloc[:0]
        table = per_issue.reindex(issued).to_numpy(dtype=float)
        result[model] = [None if np.isnan(row).all() else rounded(row) for row in table]
    return result


def milliseconds(at: pd.Timestamp) -> int:
    return int(at.value // 1_000_000)


def _y_range(values: Iterable[float | None]) -> list[float]:
    """The fixed y axis of an event: every value it draws, padded."""
    known = [value for value in values if value is not None]
    return [float(np.floor(min(known) - Y_PADDING_CM)), float(np.ceil(max(known) + Y_PADDING_CM))]


def replay_data(
    predictions: pd.DataFrame, dataset: pd.DataFrame, leads: int, high_water_cm: float
) -> dict[str, Any]:
    """Everything the page draws, as plain JSON-ready values."""
    names = set(predictions["model"])
    models = ([PERSISTENCE] if PERSISTENCE in names else []) + sorted(names - {PERSISTENCE})
    observed = events.observed_levels(dataset, leads)
    replays = []
    for event in replay_events(observed, high_water_cm).to_dict("records"):
        issued = issue_times(event["peak_at"], event["end"], event["previous_end"])
        window = observed.reindex(
            pd.date_range(issued[0] - HISTORY_HOURS * _HOUR, issued[-1] + leads * _HOUR, freq="h")
        )
        forecasts = forecast_arrays(predictions, models, issued, leads)
        observed_values = rounded(window.to_numpy(dtype=float))
        replays.append(
            {
                "number": event["number"],
                "start": milliseconds(event["start"]),
                "end": milliseconds(event["end"]),
                "pre_event_cm": round(float(event["pre_event_cm"]), 1),
                "peak_cm": round(float(event["peak_cm"]), 1),
                "peak_at": milliseconds(event["peak_at"]),
                "first_issue": milliseconds(issued[0]),
                "issues": len(issued),
                "observed_from": milliseconds(window.index[0]),
                "observed": observed_values,
                "forecasts": forecasts,
                "y_range": _y_range([high_water_cm, *observed_values]),
                # Per model, so the page sizes the axis to the models shown, not to all of them.
                "model_ranges": {
                    model: _y_range(
                        value
                        for forecast in per_issue
                        if forecast is not None
                        for value in forecast
                    )
                    for model, per_issue in forecasts.items()
                    if any(forecast is not None for forecast in per_issue)
                },
            }
        )
    return {
        "leads": leads,
        "high_water_cm": high_water_cm,
        "default_model": PERSISTENCE,
        "models": models,
        "events": replays,
    }


def render(data: dict[str, Any]) -> str:
    """The template with the data embedded; every `<` escaped so the JSON can't end the script."""
    payload = json.dumps(data, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    return TEMPLATE.read_text().replace(DATA_MARKER, payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pegel.evaluation.replay")
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
    settings = load_config().evaluation
    data = replay_data(
        predictions,
        pd.read_parquet(arguments.dataset),
        settings.leads_hours,
        settings.high_water_cm,
    )
    if not data["events"]:
        parser.error("no flood event with its peak in a test fold")
    out = arguments.run / "replay.html"
    out.write_text(render(data))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.timeline import LEADS as TIMELINE_LEADS
from pegel.evaluation.timeline import LONG_LEAD_HOURS, SHORT_LEAD_HOURS, main, render, timeline_data

# Two days before the first test fold (F1 starts 2024-10-01), so the first event is in training.
START = pd.Timestamp("2024-09-29T00:30Z")
HOURS = 200
LEADS = load_config().evaluation.leads_hours


def _observed() -> pd.Series:
    """Three events on a 50 cm base: peaks at hours 32 (training), 52 and 122 (fold F1)."""
    levels = [50.0] * HOURS
    for at in (30, 50, 120):
        levels[at - 1] = 49
        levels[at : at + 6] = [70, 90, 100, 80, 60, 53]
    return pd.Series(levels, index=pd.date_range(START, periods=HOURS, freq="h"))


def _dataset(observed: pd.Series) -> pd.DataFrame:
    """The eval_factory schema with each lead's target the observed level `lead` hours later."""
    dataset = eval_dataset(first_issue=START.isoformat(), hours=len(observed))
    for lead in range(1, LEADS + 1):
        dataset[f"{contract.TARGET}_{lead}"] = observed.shift(-lead).to_numpy()
    return dataset


def _predictions(issued: pd.DatetimeIndex, models: list[str]) -> pd.DataFrame:
    """Each forecast is the issue hour (counted from START) plus the lead, to trace it back."""
    return pd.DataFrame(
        [
            {
                contract.ISSUED_AT: issued_at,
                "lead": lead,
                "model": model,
                "fold": "F1",
                "prediction": (issued_at - START) / pd.Timedelta(hours=1) + lead / 100,
                "target": np.nan,
            }
            for model in models
            for issued_at in issued
            for lead in range(1, LEADS + 1)
        ]
    )


def _test_hours() -> pd.DatetimeIndex:
    return pd.date_range("2024-10-01T00:30Z", START + pd.Timedelta(hours=HOURS - 1), freq="h")


def test_timeline_data_puts_each_forecast_at_its_target_time() -> None:
    issued = _test_hours()
    predictions = _predictions(issued, ["upstream", "persistence"])

    data = timeline_data(predictions, _dataset(_observed()), LEADS, high_water_cm=75)

    assert data["models"] == ["persistence", "upstream"]
    assert data["leads"] == list(TIMELINE_LEADS)
    assert data["shown_leads"] == [SHORT_LEAD_HOURS, LONG_LEAD_HOURS]
    assert set(data["forecasts"]) == {str(lead) for lead in TIMELINE_LEADS}
    first_target = issued[0] + pd.Timedelta(hours=SHORT_LEAD_HOURS)
    assert data["start"] == first_target.value // 1_000_000
    length = len(issued) - 1 + LONG_LEAD_HOURS - SHORT_LEAD_HOURS + 1
    short = data["forecasts"][str(SHORT_LEAD_HOURS)]["upstream"]
    long = data["forecasts"][str(LONG_LEAD_HOURS)]["upstream"]
    assert len(data["observed"]) == len(short) == len(long) == length
    # Grid index i is target time start + i h: issued at hour 48 + i (short) or 27 + i (long).
    assert short[0] == round(48 + SHORT_LEAD_HOURS / 100, 1)
    assert long[0] is None and long[21] == round(48 + LONG_LEAD_HOURS / 100, 1)
    assert short[-1] is None
    assert data["observed"][0] == _observed()[first_target]


def test_timeline_data_breaks_lines_at_gaps() -> None:
    issued = _test_hours()
    predictions = _predictions(issued, ["persistence"])
    predictions = predictions[predictions[contract.ISSUED_AT] != issued[5]]

    data = timeline_data(predictions, _dataset(_observed()), LEADS, high_water_cm=75)

    assert data["forecasts"][str(SHORT_LEAD_HOURS)]["persistence"][5] is None
    assert data["forecasts"][str(SHORT_LEAD_HOURS)]["persistence"][6] is not None


def test_timeline_data_marks_folds_and_test_events() -> None:
    predictions = _predictions(_test_hours(), ["persistence"])

    data = timeline_data(predictions, _dataset(_observed()), LEADS, high_water_cm=75)

    assert data["folds"] == [
        {"name": "F1", "start": pd.Timestamp("2024-10-01T00:00Z").value // 1_000_000}
    ]
    assert [event["number"] for event in data["events"]] == [1, 2]
    assert data["events"][0]["peak_at"] == (START + pd.Timedelta(hours=52)).value // 1_000_000
    assert data["events"][0]["peak_cm"] == 100


def _write_run(tmp_path: Path, predictions: pd.DataFrame) -> tuple[Path, Path]:
    dataset_path = tmp_path / "eval.parquet"
    _dataset(_observed()).to_parquet(dataset_path)
    run = tmp_path / "run"
    run.mkdir()
    predictions.to_parquet(run / "predictions.parquet")
    return run, dataset_path


def test_cli_writes_the_page_with_the_data_embedded(tmp_path: Path) -> None:
    run, dataset_path = _write_run(tmp_path, _predictions(_test_hours(), ["persistence"]))

    assert main([str(run), str(dataset_path)]) == 0

    page = (run / "timeline.html").read_text()
    embedded = re.search(r'<script id="timeline-data" type="application/json">(.*?)</script>', page)
    assert embedded is not None
    assert json.loads(embedded.group(1))["models"] == ["persistence"]


def test_cli_rejects_missing_files_empty_predictions_and_missing_leads(tmp_path: Path) -> None:
    predictions = _predictions(_test_hours(), ["persistence"])
    run, dataset_path = _write_run(tmp_path, predictions[predictions["lead"] != LONG_LEAD_HOURS])
    with pytest.raises(SystemExit):
        main([str(run), str(tmp_path / "missing.parquet")])
    with pytest.raises(SystemExit):
        main([str(run), str(dataset_path)])
    predictions.iloc[:0].to_parquet(run / "predictions.parquet")
    with pytest.raises(SystemExit):
        main([str(run), str(dataset_path)])
    assert not (run / "timeline.html").exists()


def test_render_escapes_model_names_that_would_end_the_script() -> None:
    name = "a</script><!--<script>b"

    page = render({"models": [name]})

    embedded = re.search(
        r'<script id="timeline-data" type="application/json">(.*?)</script>', page, re.S
    )
    assert embedded is not None
    assert json.loads(embedded.group(1)) == {"models": [name]}

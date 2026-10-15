import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.replay import (
    forecast_arrays,
    issue_times,
    main,
    render,
    replay_data,
    replay_events,
)

# Two days before the first test fold (F1 starts 2024-10-01), so the first event is in training.
START = pd.Timestamp("2024-09-29T00:30Z")
HOURS = 200


def _hour(hour: int) -> pd.Timestamp:
    return START + pd.Timedelta(hours=hour)


def _observed() -> pd.Series:
    """Three events on a 50 cm base: peaks at hours 32 (training), 52 and 122 (fold F1).

    Each rise starts from a 49 cm low the hour before and ends back at 53 cm."""
    levels = [50.0] * HOURS
    for at in (30, 50, 120):
        levels[at - 1] = 49
        levels[at : at + 6] = [70, 90, 100, 80, 60, 53]
    return pd.Series(levels, index=pd.date_range(START, periods=HOURS, freq="h"))


def _dataset(observed: pd.Series, leads: int) -> pd.DataFrame:
    """The eval_factory schema with each lead's target the observed level `lead` hours later."""
    dataset = eval_dataset(first_issue=START.isoformat(), hours=len(observed))
    for lead in range(1, leads + 1):
        dataset[f"{contract.TARGET}_{lead}"] = observed.shift(-lead).to_numpy()
    return dataset


def _predictions(issued: pd.Index, models: list[str], leads: int) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                contract.ISSUED_AT: issued_at,
                "lead": lead,
                "model": model,
                "fold": "F1",
                "prediction": 60.0 + lead,
                "target": np.nan,
            }
            for model in models
            for issued_at in issued
            for lead in range(1, leads + 1)
        ]
    )


def test_replay_events_keeps_test_fold_peaks_numbered_by_peak_time() -> None:
    found = replay_events(_observed(), 75)
    assert found["number"].tolist() == [1, 2]
    assert found["peak_at"].tolist() == [_hour(52), _hour(122)]
    # The previous end comes from the training event too.
    assert found["previous_end"].tolist() == [_hour(35), _hour(55)]


def test_issue_times_start_a_day_before_the_peak_and_run_to_the_end() -> None:
    issued = issue_times(_hour(122), _hour(125), _hour(55))
    assert issued[0] == _hour(98)
    assert issued[-1] == _hour(125)
    assert len(issued) == 28


def test_issue_times_never_start_before_the_previous_event_ends() -> None:
    assert issue_times(_hour(52), _hour(55), _hour(35))[0] == _hour(35)
    assert issue_times(_hour(52), _hour(55), pd.NaT)[0] == _hour(28)


def test_forecast_arrays_mark_missing_forecasts() -> None:
    issued = pd.date_range(_hour(0), periods=3, freq="h")
    predictions = _predictions(issued, ["persistence", "other"], leads=2)
    # `other` has no forecast at the second issue time and a gap at lead 2 of the third.
    other = predictions["model"] == "other"
    predictions = predictions[~(other & (predictions[contract.ISSUED_AT] == issued[1]))]
    gap = other & (predictions[contract.ISSUED_AT] == issued[2]) & (predictions["lead"] == 2)
    predictions.loc[gap, "prediction"] = np.nan

    arrays = forecast_arrays(predictions, ["persistence", "other", "absent"], issued, leads=2)

    assert arrays["persistence"] == [[61.0, 62.0]] * 3
    assert arrays["other"] == [[61.0, 62.0], None, [61.0, None]]
    assert arrays["absent"] == [None, None, None]


def test_replay_data_builds_one_replay_per_test_event() -> None:
    observed = _observed()
    predictions = _predictions(observed.index, ["upstream", "persistence"], leads=3)

    data = replay_data(predictions, _dataset(observed, 3), leads=3, high_water_cm=75)

    assert data["models"] == ["persistence", "upstream"]
    first, second = data["events"]
    assert first["first_issue"] == _hour(35).value // 1_000_000
    assert first["issues"] == 21
    assert len(first["forecasts"]["upstream"]) == 21
    assert first["peak_cm"] == 100
    assert first["pre_event_cm"] == 49
    assert first["y_range"][0] <= 49 and first["y_range"][1] >= 100
    assert set(first["model_ranges"]) == {"persistence", "upstream"}
    assert second["number"] == 2
    # History before the first issue time and the last forecast's leads after the end.
    assert len(second["observed"]) == 24 + second["issues"] + 3


def _write_run(tmp_path: Path, predictions: pd.DataFrame) -> tuple[Path, Path]:
    leads = load_config().evaluation.leads_hours
    dataset_path = tmp_path / "eval.parquet"
    _dataset(_observed(), leads).to_parquet(dataset_path)
    run = tmp_path / "run"
    run.mkdir()
    predictions.to_parquet(run / "predictions.parquet")
    return run, dataset_path


def test_cli_writes_the_page_with_the_data_embedded(tmp_path: Path) -> None:
    leads = load_config().evaluation.leads_hours
    run, dataset_path = _write_run(
        tmp_path, _predictions(_observed().index, ["persistence"], leads)
    )

    assert main([str(run), str(dataset_path)]) == 0

    page = (run / "replay.html").read_text()
    embedded = re.search(r'<script id="replay-data" type="application/json">(.*?)</script>', page)
    assert embedded is not None
    data = json.loads(embedded.group(1))
    assert [event["number"] for event in data["events"]] == [1, 2]


def test_cli_rejects_missing_files_and_empty_predictions(tmp_path: Path) -> None:
    run, dataset_path = _write_run(tmp_path, _predictions(pd.DatetimeIndex([]), [], 1))
    with pytest.raises(SystemExit):
        main([str(run), str(tmp_path / "missing.parquet")])
    with pytest.raises(SystemExit):
        main([str(run), str(dataset_path)])
    assert not (run / "replay.html").exists()


def test_render_escapes_model_names_that_would_end_the_script() -> None:
    name = "a</script><!--<script>b"

    page = render({"models": [name]})

    # Unescaped, the match would stop at the name's own </script> and fail to parse.
    embedded = re.search(
        r'<script id="replay-data" type="application/json">(.*?)</script>', page, re.S
    )
    assert embedded is not None
    assert json.loads(embedded.group(1)) == {"models": [name]}

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import ClassVar

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import EvaluationSettings, load_config
from pegel.evaluation import contract, harness, predict
from pegel.evaluation.models.persistence import Persistence

SETTINGS = load_config().evaluation
FIRST_FOLD = contract.FOLDS[0]


def _dataset() -> pd.DataFrame:
    """Five days before the first fold, through its first two days."""
    return eval_dataset(first_issue="2024-09-26T00:30Z", hours=7 * 24)


class _Spy:
    name = "spy"
    instances: ClassVar[list["_Spy"]] = []

    def __init__(self, settings: EvaluationSettings) -> None:
        self.leads = settings.leads_hours
        self.fits: list[pd.DataFrame] = []
        self.predict_columns: list[str] = []
        _Spy.instances.append(self)

    def fit(self, train: pd.DataFrame) -> None:
        self.fits.append(train)

    def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
        self.predict_columns += list(rows.columns)
        return np.zeros((len(rows), self.leads))


def test_persistence_repeats_the_last_level_for_every_lead() -> None:
    rows = _dataset()
    forecast = Persistence(SETTINGS).predict(rows)
    assert forecast.shape == (len(rows), SETTINGS.leads_hours)
    assert (forecast == rows[[contract.KD_LAST_CM]].to_numpy()).all()


def test_output_has_the_prediction_columns_and_targets() -> None:
    dataset = _dataset()
    predictions = harness.run(dataset, [Persistence], SETTINGS)
    assert tuple(predictions.columns) == contract.PREDICTION_COLUMNS
    assert str(predictions["issued_at"].dt.tz) == "UTC"
    assert predictions["lead"].dtype == np.int64
    assert predictions["model"].tolist() == ["persistence"] * len(predictions)
    assert predictions["prediction"].dtype == np.float64
    assert predictions["target"].dtype == np.float64
    assert set(predictions["fold"]) == {FIRST_FOLD.name}
    holdout = contract.holdout_rows(dataset, FIRST_FOLD)
    assert len(predictions) == len(holdout) * SETTINGS.leads_hours
    row = predictions.iloc[SETTINGS.leads_hours + 2]  # second issue time, lead 3
    assert row["lead"] == 3
    assert row["issued_at"] == holdout[contract.ISSUED_AT].iloc[1]
    assert row["target"] == holdout["target_3"].iloc[1]
    assert row["prediction"] == holdout[contract.KD_LAST_CM].iloc[1]


def test_training_rows_end_an_embargo_before_the_test_period() -> None:
    _Spy.instances = []
    harness.run(_dataset(), [_Spy], SETTINGS)
    (train,) = _Spy.instances[0].fits
    assert not train.empty
    embargo_start = pd.Timestamp(FIRST_FOLD.test_start, tz="UTC") - pd.Timedelta(
        hours=SETTINGS.leads_hours
    )
    assert train[contract.ISSUED_AT].max() < embargo_start


def test_predict_never_sees_a_target() -> None:
    dataset = _dataset()
    # Datasets built before the raw series was left out still carry raw target columns.
    dataset["target_raw_1"] = dataset["target_1"]
    _Spy.instances = []
    harness.run(dataset, [_Spy], SETTINGS)
    columns = _Spy.instances[0].predict_columns
    assert contract.KD_LAST_CM in columns
    assert not [column for column in columns if column.startswith(contract.TARGET)]


def test_each_fold_gets_a_fresh_model() -> None:
    # Two days in each of the first two folds.
    dataset = pd.concat(
        [
            eval_dataset(first_issue="2024-12-30T00:30Z", hours=4 * 24),
            eval_dataset(first_issue="2024-09-30T00:30Z", hours=2 * 24),
        ]
    )
    _Spy.instances = []
    predictions = harness.run(dataset, [_Spy], SETTINGS)
    assert set(predictions["fold"]) == {"F1", "F2"}
    assert [len(spy.fits) for spy in _Spy.instances] == [1, 1]


def test_a_prediction_of_the_wrong_shape_is_rejected() -> None:
    class _Short(_Spy):
        def predict(self, rows: pd.DataFrame) -> npt.NDArray[np.float64]:
            return np.zeros((len(rows), self.leads - 1))

    with pytest.raises(ValueError, match="shape"):
        harness.run(_dataset(), [_Short], SETTINGS)


def test_a_dataset_outside_every_fold_is_rejected() -> None:
    with pytest.raises(ValueError, match="no rows"):
        harness.run(eval_dataset(), [Persistence], SETTINGS)


def _write_dataset(folder: Path, row_count: int = 7 * 24) -> Path:
    dataset = folder / "eval.parquet"
    _dataset().to_parquet(dataset, index=False)
    manifest = contract.Manifest(
        window_first_day=date(2024, 9, 26),
        window_last_day=date(2024, 10, 2),
        config=load_config().model_dump(mode="json"),
        git_commit="abc",
        row_count=row_count,
        sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
        created_at=pd.Timestamp("2026-10-14T12:00Z").to_pydatetime(),
        database="test",
    )
    predict.manifest_path(dataset).write_text(manifest.model_dump_json())
    return dataset


def test_runner_writes_predictions_and_run_manifest(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    out = tmp_path / "run"
    assert predict.main([str(dataset), "--out", str(out), "--models", "persistence"]) == 0
    predictions = pd.read_parquet(out / "predictions.parquet")
    assert tuple(predictions.columns) == contract.PREDICTION_COLUMNS
    assert set(predictions["model"]) == {"persistence"}
    run = json.loads((out / "run.json").read_text())
    assert run["dataset_sha256"] == hashlib.sha256(dataset.read_bytes()).hexdigest()
    assert run["models"] == ["persistence"]
    assert len(run["git_commit"]) == 40
    assert isinstance(run["dirty"], bool)
    assert run["settings"]["leads_hours"] == SETTINGS.leads_hours


def test_runner_uses_the_settings_frozen_in_the_manifest(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    manifest = json.loads(predict.manifest_path(dataset).read_text())
    manifest["config"]["evaluation"]["leads_hours"] = SETTINGS.leads_hours - 1
    predict.manifest_path(dataset).write_text(json.dumps(manifest))
    predict.main([str(dataset), "--out", str(tmp_path / "run")])
    predictions = pd.read_parquet(tmp_path / "run" / "predictions.parquet")
    assert predictions["lead"].max() == SETTINGS.leads_hours - 1


def test_runner_rejects_a_row_count_mismatch(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path, row_count=7 * 24 + 1)
    with pytest.raises(ValueError, match="rows"):
        predict.main([str(dataset), "--out", str(tmp_path / "run")])


def test_runner_rejects_a_modified_dataset(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    with dataset.open("ab") as file:
        file.write(b"\0")
    with pytest.raises(ValueError, match="sha256"):
        predict.main([str(dataset), "--out", str(tmp_path / "run")])
    assert not (tmp_path / "run").exists()


def test_runner_rejects_an_unknown_model(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path)
    with pytest.raises(ValueError, match="unknown models"):
        predict.main([str(dataset), "--out", str(tmp_path / "run"), "--models", "nope"])

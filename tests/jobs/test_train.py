import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.core.bands import BandTable
from pegel.evaluation.models.curated import CuratedChange
from pegel.jobs import train

CONFIG = load_config()
CREATED_AT = datetime(2026, 10, 15, 9, 41, 30, tzinfo=UTC)


def test_saved_model_loads_back_and_predicts_the_same(tmp_path: Path) -> None:
    # Ten days before the first fold and twelve in it, so the bands have out-of-sample errors.
    rows = eval_dataset(first_issue="2024-09-21T00:30Z", hours=22 * 24)
    model = train.trainable_model("ridge:change:v2", CONFIG.evaluation)
    model.fit(rows)
    band_table = train.out_of_sample_bands(model.name, rows, CONFIG)
    document = train.model_document(
        model,
        band_table,
        rows,
        CONFIG,
        date(2024, 9, 21),
        date(2024, 10, 12),
        "abc",
        "role/host",
        CREATED_AT,
    )
    path = tmp_path / train.file_name(model.name, CREATED_AT)
    train.write_new(path, document)

    saved = json.loads(path.read_text())
    loaded = CuratedChange.from_dict(saved["model"], CONFIG.evaluation)
    np.testing.assert_array_equal(loaded.predict(rows), model.predict(rows))
    assert BandTable.from_dict(saved["bands"]).leads == CONFIG.evaluation.leads_hours
    trained = saved["trained"]
    assert path.name == "ridge-change-v2-20261015T0941Z.json"
    assert trained["row_count"] == 22 * 24
    assert trained["window_last_day"] == "2024-10-12"
    assert len(trained["in_sample_mae_cm_per_lead"]) == CONFIG.evaluation.leads_hours
    assert trained["config"]["evaluation"]["leads_hours"] == CONFIG.evaluation.leads_hours


def test_refuses_a_model_that_cannot_be_saved() -> None:
    with pytest.raises(SystemExit, match="only curated change models"):
        train.trainable_model("persistence", CONFIG.evaluation)


def test_never_overwrites_a_saved_file(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    path.write_text("old")
    with pytest.raises(SystemExit, match="never overwritten"):
        train.write_new(path, {"new": 1})
    assert path.read_text() == "old"

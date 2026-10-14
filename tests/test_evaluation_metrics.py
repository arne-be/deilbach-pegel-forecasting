import math

import numpy as np
import pandas as pd
import pytest

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.metrics import (
    PERSISTENCE,
    SUBSET_ALL,
    SUBSET_HIGH_WATER,
    bootstrap_skill,
    scores,
)

SETTINGS = load_config().evaluation.model_copy(update={"leads_hours": 1, "high_water_cm": 75})
ISSUED = pd.date_range("2024-10-01T00:30Z", periods=3, freq="h")


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            contract.ISSUED_AT: ISSUED,
            contract.KD_LAST_CM: [50.0, 80.0, 50.0],
            "target_1": [52.0, 70.0, np.nan],
        }
    )


def _predictions() -> pd.DataFrame:
    target = [52.0, 70.0, np.nan]
    frames = [
        pd.DataFrame({"model": name, "prediction": values, "target": target})
        for name, values in ((PERSISTENCE, [50.0, 80.0, 50.0]), ("m", [53.0, 74.0, 40.0]))
    ]
    predictions = pd.concat(frames, ignore_index=True)
    predictions[contract.ISSUED_AT] = list(ISSUED) * 2
    predictions["lead"] = 1
    predictions["fold"] = "F1"
    return predictions[list(contract.PREDICTION_COLUMNS)]


def _score(subset: str, fold: str = "F1", model: str = "m") -> pd.Series:
    table = scores(_predictions(), _dataset(), SETTINGS)
    selected = table[(table["model"] == model) & (table["fold"] == fold)]
    return selected[selected["subset"] == subset].iloc[0]


def test_scores_have_the_contract_columns() -> None:
    table = scores(_predictions(), _dataset(), SETTINGS)
    assert tuple(table.columns) == contract.SCORE_COLUMNS


def test_all_rows_leave_out_missing_targets() -> None:
    row = _score(SUBSET_ALL)
    # Errors +1 and +4; persistence errors -2 and +10.
    assert row["n"] == 2
    assert row["mae"] == pytest.approx(2.5)
    assert row["rmse"] == pytest.approx(math.sqrt(8.5))
    assert row["bias"] == pytest.approx(2.5)
    assert row["skill"] == pytest.approx(1 - 2.5 / 6)


def test_pooled_fold_equals_the_single_fold() -> None:
    assert _score(SUBSET_ALL, fold="all")["mae"] == _score(SUBSET_ALL)["mae"]


def test_high_water_takes_rows_above_the_threshold_at_issue_or_target() -> None:
    row = _score(SUBSET_HIGH_WATER)
    assert row["n"] == 1
    assert row["mae"] == pytest.approx(4)
    assert row["skill"] == pytest.approx(0.6)


def test_persistence_has_skill_zero() -> None:
    assert _score(SUBSET_ALL, model=PERSISTENCE)["skill"] == 0


def test_scores_need_persistence() -> None:
    predictions = _predictions()
    with pytest.raises(ValueError, match="persistence"):
        scores(predictions[predictions["model"] != PERSISTENCE], _dataset(), SETTINGS)


def _bootstrap_predictions() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    issued = pd.date_range("2024-10-01T00:30Z", periods=10 * 24, freq="h")
    target = rng.uniform(40, 60, len(issued))
    persistence = target + rng.uniform(0, 5, len(issued))
    models = {
        PERSISTENCE: persistence,
        "copy": persistence,
        "plus_one": persistence + 1,
        "noisy": target + rng.normal(0, 4, len(issued)),
    }
    return pd.concat(
        pd.DataFrame(
            {
                contract.ISSUED_AT: issued,
                "lead": 1,
                "model": name,
                "fold": "F1",
                "prediction": values,
                "target": target,
            }
        )
        for name, values in models.items()
    )


def _bootstrap_row(table: pd.DataFrame, model: str) -> pd.Series:
    return table[table["model"] == model].iloc[0]


def test_bootstrap_of_a_copy_of_persistence_is_zero() -> None:
    row = _bootstrap_row(bootstrap_skill(_bootstrap_predictions()), "copy")
    assert (row["mae_difference"], row["low"], row["high"]) == (0, 0, 0)


def test_bootstrap_of_a_constant_offset_is_exact() -> None:
    # Every persistence forecast is above its target, so one more cm is one more cm of error.
    row = _bootstrap_row(bootstrap_skill(_bootstrap_predictions()), "plus_one")
    assert row[["mae_difference", "low", "high"]].tolist() == pytest.approx([1, 1, 1])


def test_bootstrap_is_seeded() -> None:
    predictions = _bootstrap_predictions()
    first = bootstrap_skill(predictions, resamples=200, seed=3)
    pd.testing.assert_frame_equal(first, bootstrap_skill(predictions, resamples=200, seed=3))
    noisy = _bootstrap_row(first, "noisy")
    assert noisy["low"] < noisy["mae_difference"] < noisy["high"]
    other = _bootstrap_row(bootstrap_skill(predictions, resamples=200, seed=4), "noisy")
    assert other["low"] != noisy["low"]


def test_a_missing_prediction_is_left_out_for_the_model_and_persistence() -> None:
    issued = pd.date_range("2024-10-01T00:30Z", periods=2, freq="h")
    dataset = pd.DataFrame(
        {
            contract.ISSUED_AT: issued,
            contract.KD_LAST_CM: [50.0, 50.0],
            "target_1": [50.0, 50.0],
        }
    )
    predictions = pd.DataFrame(
        {
            contract.ISSUED_AT: list(issued) * 2,
            "lead": 1,
            "model": [PERSISTENCE, PERSISTENCE, "m", "m"],
            "fold": "F1",
            "prediction": [54.0, 52.0, np.nan, 51.0],
            "target": 50.0,
        }
    )
    table = scores(predictions, dataset, SETTINGS)
    selected = (table["model"] == "m") & (table["fold"] == "F1") & (table["subset"] == SUBSET_ALL)
    row = table[selected].iloc[0]
    assert row["n"] == 1
    assert row["skill"] == pytest.approx(1 - 1 / 2)
    assert _bootstrap_row(bootstrap_skill(predictions), "m")["mae_difference"] == -1

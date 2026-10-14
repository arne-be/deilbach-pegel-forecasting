import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.evaluation import contract
from pegel.evaluation.targets import TargetKind, from_target, to_target

KINDS: list[TargetKind] = ["level", "change", "step"]


def _levels(dataset: pd.DataFrame) -> np.ndarray:
    return dataset[contract.lead_columns(contract.TARGET, 24)].to_numpy(dtype=float)


@pytest.mark.parametrize("kind", KINDS)
def test_round_trip_gives_back_the_levels(kind: TargetKind) -> None:
    dataset = eval_dataset()
    target = to_target(dataset, kind)
    assert target.shape == (len(dataset), 24)
    np.testing.assert_allclose(from_target(target, dataset, kind), _levels(dataset))


def test_forms_match_a_hand_computation() -> None:
    dataset = eval_dataset(hours=1)
    row = dataset.iloc[0]
    change = to_target(dataset, "change")[0]
    step = to_target(dataset, "step")[0]
    assert change[4] == pytest.approx(row["target_5"] - row["kd_last_cm"])
    assert step[0] == pytest.approx(row["target_1"] - row["kd_last_cm"])
    assert step[4] == pytest.approx(row["target_5"] - row["target_4"])


def test_a_missing_level_makes_the_steps_around_it_nan() -> None:
    dataset = eval_dataset(hours=1)
    dataset.loc[0, "target_5"] = np.nan
    step = to_target(dataset, "step")[0]
    assert np.isnan(step[[4, 5]]).all()
    assert not np.isnan(np.delete(step, [4, 5])).any()
    restored = from_target(to_target(dataset, "step"), dataset, "step")[0]
    np.testing.assert_allclose(restored[:4], _levels(dataset)[0, :4])
    assert np.isnan(restored[4:]).all()

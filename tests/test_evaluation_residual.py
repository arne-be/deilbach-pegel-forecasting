import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract, harness
from pegel.evaluation.models.residual import ResidualTrees, ridge_v2
from pegel.evaluation.predict import selected_models

SETTINGS = load_config().evaluation
NAMES = ["lgbm_residual:v1", "lgbm_residual:v1:linear"]


def _dataset() -> pd.DataFrame:
    """A month before the first fold, through its first two days."""
    return eval_dataset(first_issue="2024-09-01T00:30Z", hours=32 * 24)


def test_both_variants_run_end_to_end_and_are_seeded() -> None:
    dataset = _dataset()
    factories = selected_models(NAMES, SETTINGS)
    first = harness.run(dataset, factories, SETTINGS)
    second = harness.run(dataset, factories, SETTINGS)
    assert sorted(first["model"].unique()) == NAMES
    assert np.isfinite(first["prediction"]).all()
    pd.testing.assert_frame_equal(first, second)


@pytest.mark.parametrize("linear_tree", [False, True])
def test_with_the_trees_at_zero_it_is_ridge_change_v2(
    linear_tree: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = _dataset()
    train = contract.train_rows(dataset, contract.FOLDS[0], SETTINGS)
    rows = contract.holdout_rows(dataset, contract.FOLDS[0])
    model = ResidualTrees(SETTINGS, name="test", linear_tree=linear_tree)
    model.fit(train)
    ridge = ridge_v2(SETTINGS)
    ridge.fit(train)
    assert not np.allclose(model.predict(rows), ridge.predict(rows))
    monkeypatch.setattr(
        model, "correction", lambda rows: np.zeros((len(rows), SETTINGS.leads_hours))
    )
    np.testing.assert_allclose(model.predict(rows), ridge.predict(rows))


def test_out_of_fold_residuals_ignore_the_order_of_the_rows() -> None:
    train = contract.train_rows(_dataset(), contract.FOLDS[0], SETTINGS)
    model = ResidualTrees(SETTINGS, name="test")
    shuffled = train.sample(frac=1, random_state=0)
    np.testing.assert_allclose(
        model.out_of_fold_residuals(shuffled),
        pd.DataFrame(model.out_of_fold_residuals(train), index=train.index).loc[shuffled.index],
    )

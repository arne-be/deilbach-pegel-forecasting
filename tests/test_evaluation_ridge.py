import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.core.features import ICON_PREFIXES, features
from pegel.evaluation import contract
from pegel.evaluation.models.ridge import Imputer, Ridge
from pegel.evaluation.registry import MODELS
from pegel.evaluation.targets import TargetKind

SETTINGS = load_config().evaluation
LEADS = SETTINGS.leads_hours
TARGETS = contract.lead_columns(contract.TARGET, LEADS)


def _linear_dataset(hours: int = 800) -> pd.DataFrame:
    """Targets that are an exact linear function of two inputs, with a few missing."""
    dataset = eval_dataset(hours=hours)
    for lead, column in enumerate(TARGETS, start=1):
        dataset[column] = 10 + 2 * dataset["kd_lag_3"] + 0.1 * lead * dataset["lb_lag_0"]
    dataset.loc[::7, TARGETS[5]] = np.nan
    return dataset


def _without_targets(dataset: pd.DataFrame) -> pd.DataFrame:
    return dataset.loc[:, ~dataset.columns.str.startswith(f"{contract.TARGET}_")]


def test_recovers_a_linear_relation() -> None:
    dataset = _linear_dataset()
    train, test = dataset.iloc[:600], dataset.iloc[600:]
    model = Ridge(SETTINGS, kind="level")
    model.fit(train)
    predictions = model.predict(_without_targets(test))
    assert predictions.shape == (len(test), LEADS)
    expected = test[TARGETS].to_numpy()
    assert np.nanmax(np.abs(predictions - expected)) < 1.0


def test_change_variant_adds_the_last_level_back() -> None:
    dataset = eval_dataset(hours=200)
    for column in TARGETS:
        dataset[column] = dataset[contract.KD_LAST_CM] + 3.0
    model = Ridge(SETTINGS, kind="change")
    model.fit(dataset.iloc[:150])
    test = dataset.iloc[150:]
    predictions = model.predict(_without_targets(test))
    expected = np.repeat(test[[contract.KD_LAST_CM]].to_numpy() + 3.0, LEADS, axis=1)
    np.testing.assert_allclose(predictions, expected, atol=1e-9)


def test_fill_uses_only_training_statistics() -> None:
    dataset = _linear_dataset()
    model = Ridge(SETTINGS, kind="level")
    model.fit(dataset.iloc[:300])
    test = _without_targets(dataset.iloc[300:310]).copy()
    test.loc[test.index[0], "lb_lag_0"] = np.nan
    before = model.predict(test)[0]
    # Extreme values in the other test rows would move any statistic taken from the test rows.
    test.loc[test.index[1:], "lb_lag_0"] = 1e6
    np.testing.assert_array_equal(model.predict(test)[0], before)


def test_imputer_fills_newer_level_then_training_median_and_flags_groups() -> None:
    frame = features(eval_dataset(hours=20))
    train, test = frame.iloc[:10].copy(), frame.iloc[10:].copy()
    train.loc[train.index[1], "kd_lag_5"] = np.nan
    imputer = Imputer()
    imputer.fit(train)
    first, second = test.index[:2]
    test.loc[first, ["kd_lag_0", "kd_lag_1", "lb_lag_0"]] = np.nan
    test.loc[second, "radar_catchment_sum_1h"] = np.nan
    filled = imputer.transform(test)
    assert filled.loc[first, "kd_lag_1"] == test.loc[first, contract.KD_LAST_CM]
    # lb_lag_0 has no newer level, so it takes the training median.
    assert filled.loc[first, "lb_lag_0"] == train["lb_lag_0"].median()
    assert filled.loc[second, "radar_catchment_sum_1h"] == train["radar_catchment_sum_1h"].median()
    # Only kd had gaps in training, so only kd gets a flag.
    assert filled["kd_missing"].tolist()[:2] == [1.0, 0.0]
    assert not {"lb_missing", "radar_missing"} & set(filled.columns)
    assert not filled.isna().any().any()


@pytest.mark.parametrize("kind", ["level", "change"])
def test_no_icon_variant_never_reads_icon_columns(kind: TargetKind) -> None:
    dataset = _linear_dataset(hours=200)
    model = Ridge(SETTINGS, kind=kind, with_icon=False)
    model.fit(dataset.iloc[:150])
    icon = [c for p in ICON_PREFIXES for c in contract.lead_columns(p, LEADS)]
    test = _without_targets(dataset.iloc[150:]).drop(columns=icon)
    assert model.predict(test).shape == (50, LEADS)


def test_icon_variant_uses_icon_columns() -> None:
    model = Ridge(SETTINGS)
    model.fit(_linear_dataset(hours=100))
    assert any(c.startswith("icon") for c in model._imputer.columns)


def test_registry_has_four_ridge_variants_with_unique_names() -> None:
    names = [factory(SETTINGS).name for factory in MODELS]
    assert len(names) == len(set(names))
    assert {"ridge:level", "ridge:change", "ridge:level:no_icon", "ridge:change:no_icon"} <= set(
        names
    )


def test_validation_rows_start_a_full_embargo_after_the_fit_rows_in_any_row_order() -> None:
    dataset = eval_dataset(hours=300).sample(frac=1, random_state=0)
    early, late = Ridge(SETTINGS)._split_by_time(dataset)
    gap = late[contract.ISSUED_AT].min() - early[contract.ISSUED_AT].max()
    assert gap >= pd.Timedelta(hours=LEADS)
    assert len(late) == pytest.approx(0.2 * len(dataset), abs=1)

import numpy as np
import pandas as pd
import pytest
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.models.simple import (
    DampedTrend,
    Recession,
    Upstream,
    kupferdreh_change_3h,
)

SETTINGS = load_config().evaluation
LEADS = SETTINGS.leads_hours
TARGETS = contract.lead_columns(contract.TARGET, LEADS)
FACTORS = np.linspace(0.9, 0.1, LEADS)


def _with_targets(dataset: pd.DataFrame, change: np.ndarray) -> pd.DataFrame:
    """Targets that are exactly the last level plus `change` (shape rows, leads)."""
    last = dataset[[contract.KD_LAST_CM]].to_numpy()
    dataset[TARGETS] = last + change
    return dataset


def test_recession_recovers_its_factors() -> None:
    dataset = eval_dataset(hours=100)
    distance = (dataset[contract.KD_LAST_CM] - dataset[contract.KD_BASE_30D_CM]).to_numpy()
    # base + a_k * (last - base) is the last level plus (a_k - 1) * (last - base).
    dataset = _with_targets(dataset, np.outer(distance, FACTORS - 1))
    model = Recession(SETTINGS)
    model.fit(dataset)
    np.testing.assert_allclose(model.coefficients[0], FACTORS - 1, atol=1e-9)
    np.testing.assert_allclose(model.predict(dataset), dataset[TARGETS].to_numpy())


def test_damped_trend_recovers_its_factors() -> None:
    dataset = eval_dataset(hours=100)
    dataset = _with_targets(dataset, np.outer(kupferdreh_change_3h(dataset), FACTORS))
    model = DampedTrend(SETTINGS)
    model.fit(dataset)
    np.testing.assert_allclose(model.coefficients[0], FACTORS, atol=1e-9)


def test_upstream_recovers_both_factors() -> None:
    dataset = eval_dataset(hours=100)
    langenberg = (dataset["lb_lag_0"] - dataset["lb_lag_3"]).to_numpy()
    nierenhof = (dataset["nh_lag_0"] - dataset["nh_lag_3"]).to_numpy()
    change = np.outer(langenberg, FACTORS) + np.outer(nierenhof, 1 - FACTORS)
    model = Upstream(SETTINGS)
    model.fit(_with_targets(dataset, change))
    np.testing.assert_allclose(model.coefficients, [FACTORS, 1 - FACTORS], atol=1e-9)


def test_change_3h_pairs_the_last_level_with_the_lag_three_hours_older() -> None:
    dataset = eval_dataset(hours=3)
    issued_at = dataset[contract.ISSUED_AT]
    dataset[contract.KD_LAST_AT] = [
        issued_at[0] - pd.Timedelta(minutes=10),  # in lag 0, pairs with lag 3
        issued_at[1] - pd.Timedelta(minutes=70),  # in lag 1, pairs with lag 4
        issued_at[2] - pd.Timedelta(hours=21),  # lag 24 is beyond the window
    ]
    change = kupferdreh_change_3h(dataset)
    last = dataset[contract.KD_LAST_CM]
    assert change[0] == pytest.approx(last[0] - dataset["kd_lag_3"][0])
    assert change[1] == pytest.approx(last[1] - dataset["kd_lag_4"][1])
    assert np.isnan(change[2])


@pytest.mark.parametrize("model_class", [Recession, DampedTrend, Upstream])
def test_a_missing_input_falls_back_to_persistence(model_class: type) -> None:
    dataset = eval_dataset(hours=100)
    model = model_class(SETTINGS)
    model.fit(dataset)
    rows = dataset.drop(columns=TARGETS).copy()
    rows.loc[0, [contract.KD_BASE_30D_CM, "kd_lag_3", "lb_lag_3", "nh_lag_3"]] = np.nan
    forecast = model.predict(rows)
    assert forecast.shape == (len(rows), LEADS)
    assert (forecast[0] == rows[contract.KD_LAST_CM][0]).all()
    assert (forecast[1:] != rows[[contract.KD_LAST_CM]].to_numpy()[1:]).any()


def test_fit_skips_rows_without_a_target() -> None:
    dataset = eval_dataset(hours=100)
    distance = (dataset[contract.KD_LAST_CM] - dataset[contract.KD_BASE_30D_CM]).to_numpy()
    dataset = _with_targets(dataset, np.outer(distance, FACTORS - 1))
    # A NaN anywhere in a lead's rows would make its least squares NaN.
    dataset.loc[:9, TARGETS] = np.nan
    dataset.loc[20:29, "target_5"] = np.nan
    model = Recession(SETTINGS)
    model.fit(dataset)
    np.testing.assert_allclose(model.coefficients[0], FACTORS - 1, atol=1e-9)

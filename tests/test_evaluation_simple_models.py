import numpy as np
import pandas as pd
from eval_factory import eval_dataset

from pegel.config import load_config
from pegel.evaluation import contract
from pegel.evaluation.models.simple import Upstream

SETTINGS = load_config().evaluation
LEADS = SETTINGS.leads_hours
TARGETS = contract.lead_columns(contract.TARGET, LEADS)
FACTORS = np.linspace(0.9, 0.1, LEADS)


def _with_targets(dataset: pd.DataFrame, change: np.ndarray) -> pd.DataFrame:
    """Targets that are exactly the last level plus `change` (shape rows, leads)."""
    last = dataset[[contract.KD_LAST_CM]].to_numpy()
    dataset[TARGETS] = last + change
    return dataset


def test_upstream_recovers_both_factors() -> None:
    dataset = eval_dataset(hours=100)
    langenberg = (dataset["lb_lag_0"] - dataset["lb_lag_3"]).to_numpy()
    nierenhof = (dataset["nh_lag_0"] - dataset["nh_lag_3"]).to_numpy()
    change = np.outer(langenberg, FACTORS) + np.outer(nierenhof, 1 - FACTORS)
    model = Upstream(SETTINGS)
    dataset = _with_targets(dataset, change)
    model.fit(dataset)
    np.testing.assert_allclose(model.coefficients, [FACTORS, 1 - FACTORS], atol=1e-9)
    np.testing.assert_allclose(model.predict(dataset), dataset[TARGETS].to_numpy())


def test_a_missing_input_falls_back_to_persistence() -> None:
    dataset = eval_dataset(hours=100)
    model = Upstream(SETTINGS)
    model.fit(dataset)
    rows = dataset.drop(columns=TARGETS).copy()
    rows.loc[0, "lb_lag_3"] = np.nan
    forecast = model.predict(rows)
    assert forecast.shape == (len(rows), LEADS)
    assert (forecast[0] == rows[contract.KD_LAST_CM][0]).all()
    others = rows.iloc[1:]
    expected = others[[contract.KD_LAST_CM]].to_numpy() + model.inputs(others) @ model.coefficients
    np.testing.assert_allclose(forecast[1:], expected)


def test_fit_skips_rows_without_a_target() -> None:
    dataset = eval_dataset(hours=100)
    langenberg = (dataset["lb_lag_0"] - dataset["lb_lag_3"]).to_numpy()
    nierenhof = (dataset["nh_lag_0"] - dataset["nh_lag_3"]).to_numpy()
    dataset = _with_targets(
        dataset, np.outer(langenberg, FACTORS) + np.outer(nierenhof, 1 - FACTORS)
    )
    # A NaN anywhere in a lead's rows would make its least squares NaN.
    dataset.loc[:9, TARGETS] = np.nan
    dataset.loc[20:29, "target_5"] = np.nan
    model = Upstream(SETTINGS)
    model.fit(dataset)
    np.testing.assert_allclose(model.coefficients, [FACTORS, 1 - FACTORS], atol=1e-9)
